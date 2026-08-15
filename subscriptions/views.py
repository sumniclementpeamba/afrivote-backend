from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from organizations.permissions import IsOrgAdmin, IsSuperAdmin
from .models import Subscription, PlanUpgradeRequest
from .payments import create_payment_link, verify_payment
from organizations.models import Organization
from django.utils import timezone
from datetime import timedelta          # <-- NEW import

PLAN_PRICES = {
    'STANDARD': 30,    # GHS 29 per month
    'ENTERPRISE': 100,  # GHS 99 per month
}

SUBSCRIPTION_DAYS = 28   # <-- NEW constant


# ------------------------------------------------------------
# PAYSTACK PAYMENT ENDPOINTS
# ------------------------------------------------------------

class CreatePaymentSessionView(APIView):
    """
    Org admin creates a Paystack payment link for upgrading.
    The requested plan is passed to Paystack so the callback knows which plan to apply.
    """
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def post(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "No organization found"}, status=400)

        plan = request.data.get('plan')
        if plan not in PLAN_PRICES:
            return Response({"error": "Invalid plan"}, status=400)

        amount = PLAN_PRICES[plan]
        # Pass the requested plan as target_plan
        payment_link = create_payment_link(
            org, amount, target_plan=plan,
            redirect_url='http://localhost:3000/dashboard/billing'
        )
        if payment_link:
            return Response({'url': payment_link})
        return Response({'error': 'Failed to create payment'}, status=500)


class VerifyPaymentView(APIView):
    """
    Verify a Paystack payment and upgrade the organisation automatically.
    """
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def post(self, request):
        reference = request.data.get('reference')
        if not reference:
            return Response({"error": "Transaction reference required"}, status=400)

        result = verify_payment(reference)
        if not result or not result.get('status'):
            return Response({"error": "Payment verification failed"}, status=400)

        data = result['data']
        if data['status'] != 'success':
            return Response({"error": "Payment not successful"}, status=400)

        metadata = data.get('metadata', {})
        org_id = metadata.get('organization_id')
        if not org_id:
            return Response({"error": "No organization in metadata"}, status=400)

        try:
            org = Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            return Response({"error": "Organization not found"}, status=404)

        plan = metadata.get('plan', 'STANDARD')

        # Set subscription end date (now + 28 days)
        new_expiry = timezone.now() + timedelta(days=SUBSCRIPTION_DAYS)

        # Update org limits, plan, and expiry
        update_org_limits(org, plan, subscription_ends_at=new_expiry)

        # Update or create subscription record with expiry
        Subscription.objects.update_or_create(
            organization=org,
            defaults={
                'payment_gateway': 'paystack',
                'plan': plan,
                'status': 'active',
                'subscription_ends_at': new_expiry,   # <-- NEW
            }
        )

        return Response({"message": "Payment verified and plan upgraded successfully"})


# ------------------------------------------------------------
# MANUAL UPGRADE REQUEST ENDPOINTS (fallback / offline)
# ------------------------------------------------------------

class RequestUpgradeView(APIView):
    """
    Org admin requests a plan upgrade for manual approval.
    """
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def post(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "No organization found"}, status=400)

        requested_plan = request.data.get('plan')
        if requested_plan not in ['STANDARD', 'ENTERPRISE']:
            return Response({"error": "Invalid plan"}, status=400)

        if requested_plan == org.plan:
            return Response({"error": "You are already on this plan"}, status=400)

        # Check for existing pending request
        if PlanUpgradeRequest.objects.filter(
            organization=org, status='pending'
        ).exists():
            return Response(
                {"error": "You already have a pending upgrade request"},
                status=400
            )

        PlanUpgradeRequest.objects.create(
            organization=org,
            requested_by=request.user,
            current_plan=org.plan,
            requested_plan=requested_plan,
        )

        return Response({"message": "Upgrade request submitted. A super admin will review it."})


class ListUpgradeRequestsView(APIView):
    """
    Super admin lists all pending upgrade requests.
    """
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        status_filter = request.query_params.get('status', 'pending')
        requests = PlanUpgradeRequest.objects.filter(status=status_filter).order_by('-created_at')
        data = []
        for req in requests:
            data.append({
                'id': str(req.id),
                'organization': req.organization.name,
                'organization_id': str(req.organization.id),
                'current_plan': req.current_plan,
                'requested_plan': req.requested_plan,
                'status': req.status,
                'requested_by': req.requested_by.email if req.requested_by else '',
                'created_at': req.created_at.isoformat(),
            })
        return Response(data)


class ProcessUpgradeRequestView(APIView):
    """
    Super admin approves or rejects a manual upgrade request.
    """
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def post(self, request, pk):
        try:
            upgrade_req = PlanUpgradeRequest.objects.get(pk=pk, status='pending')
        except PlanUpgradeRequest.DoesNotExist:
            return Response({"error": "Request not found or already processed"}, status=404)

        action = request.data.get('action')  # 'approve' or 'reject'
        if action == 'approve':
            upgrade_req.status = 'approved'
            upgrade_req.resolved_at = timezone.now()
            upgrade_req.save()

            org = upgrade_req.organization
            new_expiry = timezone.now() + timedelta(days=SUBSCRIPTION_DAYS)   # <-- NEW

            update_org_limits(org, upgrade_req.requested_plan, subscription_ends_at=new_expiry)

            Subscription.objects.update_or_create(
                organization=org,
                defaults={
                    'plan': upgrade_req.requested_plan,
                    'status': 'active',
                    'subscription_ends_at': new_expiry,   # <-- NEW
                }
            )

            return Response({"message": "Upgrade approved and limits updated."})
        elif action == 'reject':
            upgrade_req.status = 'rejected'
            upgrade_req.resolved_at = timezone.now()
            upgrade_req.save()
            return Response({"message": "Upgrade rejected."})
        else:
            return Response({"error": "Invalid action"}, status=400)


# ------------------------------------------------------------
# RECENT UPGRADES (for Super Admin dashboard)
# ------------------------------------------------------------

class RecentUpgradesView(APIView):
    """
    Returns the last 5 active subscriptions (upgrades) for the super admin dashboard.
    """
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        subs = Subscription.objects.filter(status='active').order_by('-updated_at')[:5]
        data = []
        for sub in subs:
            data.append({
                'id': str(sub.id),
                'organization_name': sub.organization.name,
                'plan': sub.plan,
                'status': sub.status,
                'created_at': sub.updated_at.isoformat(),
                'subscription_ends_at': sub.subscription_ends_at.isoformat() if sub.subscription_ends_at else None,  # <-- NEW
            })
        return Response(data)


# ------------------------------------------------------------
# HELPER
# ------------------------------------------------------------
def update_org_limits(organization, plan, subscription_ends_at=None):
    limits = {
        'FREE': {'max_voters': 100, 'max_elections': 3},
        'STANDARD': {'max_voters': 5000, 'max_elections': 15},
        'ENTERPRISE': {'max_voters': 10000, 'max_elections': 30},
    }
    org_limits = limits.get(plan, limits['FREE'])
    organization.max_voters = org_limits['max_voters']
    organization.max_elections = org_limits['max_elections']
    organization.plan = plan
    if subscription_ends_at:                      # <-- NEW
        organization.subscription_ends_at = subscription_ends_at
    organization.save()