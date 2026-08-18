import uuid
import requests
import datetime
from decimal import Decimal
from django.db.models import Sum
from django.conf import settings
from django.http import Http404, JsonResponse
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework.decorators import api_view, permission_classes

from .models import Organization, OrganizationSettings, WithdrawalRequest
from .serializers import OrganizationBrandingSerializer, OrganizationSerializer, OrganizationDetailSerializer
from .permissions import IsSuperAdmin, IsOrgAdmin
from audit.utils import log_audit

User = get_user_model()

# ─── Paystack Payout Helpers ─────────────────────────────────────────────────
PAYSTACK_BASE = 'https://api.paystack.co'

def create_transfer_recipient(recipient_type, name, account_number, bank_code):
    """Create a transfer recipient on Paystack and return the recipient_code."""
    headers = {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'type': 'mobile_money' if recipient_type == 'momo' else 'nuban',
        'name': name,
        'account_number': account_number,
        'bank_code': bank_code,
        'currency': 'GHS'
    }
    response = requests.post(f'{PAYSTACK_BASE}/transferrecipient', json=payload, headers=headers)
    data = response.json()
    if data.get('status'):
        return data['data']['recipient_code']
    raise Exception(data.get('message', 'Failed to create recipient'))

def initiate_transfer(amount, recipient_code, reason):
    """Initiate a Paystack transfer and return the transfer data."""
    headers = {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'source': 'balance',
        'amount': int(float(amount) * 100),
        'recipient': recipient_code,
        'currency': 'GHS',
        'reason': reason
    }
    response = requests.post(f'{PAYSTACK_BASE}/transfer', json=payload, headers=headers)
    data = response.json()
    if data.get('status'):
        return data['data']
    raise Exception(data.get('message', 'Transfer failed'))


# ─── Public Registration (creates org after payment) ───
@api_view(['POST'])
@permission_classes([AllowAny])
def public_register(request):
    data = request.data
    org_name = data.get('organization_name')
    admin_email = data.get('email')
    admin_first_name = data.get('first_name')
    admin_last_name = data.get('last_name')
    password = data.get('password')
    phone = data.get('phone', '')
    transaction_ref = data.get('transaction_ref', '')

    if not all([org_name, admin_email, admin_first_name, admin_last_name, password, transaction_ref]):
        return Response({"error": "All fields are required, including payment reference."}, status=400)

    if User.objects.filter(email=admin_email).exists():
        return Response({"error": "An account with this email already exists."}, status=400)

    org = Organization.objects.create(
        name=org_name,
        email=admin_email,
        phone=phone,
        status='PENDING',
        setup_fee_paid=True,
        setup_fee_transaction_ref=transaction_ref,
    )

    User.objects.create_user(
        email=admin_email,
        password=password,
        first_name=admin_first_name,
        last_name=admin_last_name,
        organization=org,
        role='ORG_ADMIN',
        is_verified=True,
    )

    return Response({
        "message": "Registration submitted. You will be notified after approval.",
        "organization_id": str(org.id),
    }, status=201)


# ─── Setup Payment (initiates Paystack checkout) ───
@api_view(['POST'])
@permission_classes([AllowAny])
def create_setup_payment(request):
    email = request.data.get('email')
    organization_name = request.data.get('organization_name')
    first_name = request.data.get('first_name')
    last_name = request.data.get('last_name')
    phone = request.data.get('phone')
    password = request.data.get('password')

    if not email or not organization_name or not first_name or not last_name or not password:
        return Response({"error": "All fields are required."}, status=400)

    amount = 2000  # GHS 20
    reference = f"setup-{uuid.uuid4().hex}"

    payload = {
        'email': email,
        'amount': amount,
        'currency': 'GHS',
        'reference': reference,
        'callback_url': f"{settings.FRONTEND_URL}/register/success?reference={reference}",
        'metadata': {
            'organization_name': organization_name,
            'first_name': first_name,
            'last_name': last_name,
            'phone': phone,
            'password': password,
        }
    }

    headers = {
        'Authorization': f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        'Content-Type': 'application/json',
    }

    res = requests.post('https://api.paystack.co/transaction/initialize', json=payload, headers=headers)
    data = res.json()

    if data.get('status'):
        return Response({'url': data['data']['authorization_url'], 'reference': reference})
    else:
        return Response({'error': data.get('message', 'Payment initialization failed')}, status=400)


# ─── Paystack Webhook (creates org if not already created by frontend) ───
@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def paystack_webhook(request):
    payload = request.data
    if payload.get('event') == 'charge.success':
        data = payload.get('data', {})
        reference = data.get('reference', '')

        if reference.startswith('setup-'):
            metadata = data.get('metadata', {})
            email = metadata.get('email') or data.get('customer', {}).get('email')
            organization_name = metadata.get('organization_name')
            first_name = metadata.get('first_name', 'Org')
            last_name = metadata.get('last_name', 'Admin')
            phone = metadata.get('phone', '')
            password = metadata.get('password', 'Default@123')

            if email and organization_name:
                if not Organization.objects.filter(email=email).exists():
                    org = Organization.objects.create(
                        name=organization_name,
                        email=email,
                        phone=phone,
                        status='PENDING',
                        setup_fee_paid=True,
                        setup_fee_transaction_ref=reference,
                    )

                    User.objects.create_user(
                        email=email,
                        password=password,
                        first_name=first_name,
                        last_name=last_name,
                        organization=org,
                        role='ORG_ADMIN',
                        is_verified=True,
                    )

    return JsonResponse({"status": "ok"})


# ─── Setup Status (tells frontend if org has paid) ───
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def setup_status(request):
    org = request.user.organization
    if not org:
        return Response({"error": "No organisation"}, status=404)
    return Response({
        "setup_fee_paid": org.setup_fee_paid,
        "setup_fee_amount": 20,
        "organization_id": str(org.id),
        "organization_name": org.name,
    })


# ─── Approve Organisation ───
@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSuperAdmin])
def approve_organization(request, pk):
    org = Organization.objects.get(id=pk)
    org.status = 'ACTIVE'
    org.save()
    return Response({"message": "Organisation approved"})


# ─── Mark Organisation as Paid ───
@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSuperAdmin])
def mark_org_paid(request, pk):
    org = Organization.objects.get(id=pk)
    org.setup_fee_paid = True
    org.save()
    return Response({"message": "Organisation marked as paid"})


def activate_subscription(organization, plan_name):
    organization.plan = plan_name
    organization.subscription_ends_at = timezone.now() + datetime.timedelta(days=28)
    organization.save()


# ─── Super Admin: List & Create Organisations ───
class OrganizationList(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        orgs = Organization.objects.filter(is_deleted=False)
        serializer = OrganizationSerializer(orgs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = OrganizationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        org = serializer.save(status='ACTIVE')
        OrganizationSettings.objects.get_or_create(organization=org)

        admin_email = request.data.get('admin_email', '').strip()
        admin_password = request.data.get('admin_password', '').strip()
        if not admin_email or not admin_password:
            return Response({"error": "Admin email and password are required."}, status=400)

        if User.objects.filter(email=admin_email).exists():
            return Response({"error": "A user with this email already exists."}, status=400)

        User.objects.create_user(
            email=admin_email,
            password=admin_password,
            first_name='Org',
            last_name='Admin',
            organization=org,
            role='ORG_ADMIN',
            is_verified=True
        )

        log_audit(request.user, 'CREATE', 'Organization', org.pk, organization=org, request=request)

        return Response({
            'organization': OrganizationSerializer(org).data,
            'admin_credentials': {
                'email': admin_email,
                'password': admin_password
            }
        }, status=201)


# ─── Org Self View ───
class OrganizationSelfView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsOrgAdmin]
    serializer_class = OrganizationDetailSerializer

    def get_object(self):
        org = self.request.user.organization
        if not org:
            raise Http404("You are not associated with any organization.")
        return org

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        if request.user.role != 'SUPER_ADMIN':
            restricted = {'max_voters', 'max_elections', 'plan', 'status'}
            data = request.data.copy()
            for field in restricted:
                data.pop(field, None)
        else:
            data = request.data

        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        log_audit(request.user, 'UPDATE', 'Organization', instance.pk, organization=instance, request=request)
        return Response(serializer.data)


# ─── Org Detail (Super Admin) ───
class OrganizationDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    serializer_class = OrganizationDetailSerializer
    queryset = Organization.objects.filter(is_deleted=False)

    def get_object(self):
        org_id = self.kwargs.get('pk')
        try:
            return Organization.objects.get(id=org_id, is_deleted=False)
        except Organization.DoesNotExist:
            raise Http404("Organization not found.")

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        log_audit(request.user, 'UPDATE', 'Organization', instance.pk, organization=instance, request=request)
        return Response(serializer.data)

    def delete(self, request, *args, **kwargs):
        org = self.get_object()
        org.is_deleted = True
        org.save()
        return Response({"message": "Organisation deleted"}, status=204)


# ─── Org Branding ───
class OrganizationBrandingView(APIView):
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def get(self, request):
        org = request.user.organization
        if not org:
            return Response({'error': 'No organization found'}, status=404)
        serializer = OrganizationBrandingSerializer(org, context={'request': request})
        return Response(serializer.data)

    def put(self, request):
        org = request.user.organization
        if not org:
            return Response({'error': 'No organization found'}, status=404)
        if org.plan == 'FREE':
            return Response({'error': 'Branding requires Standard or Enterprise plan'}, status=403)
        serializer = OrganizationBrandingSerializer(org, data=request.data, partial=True, context={'request': request, 'organization': org})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)


# ─── Wallet & Withdrawal ──────────────────────────────────────────────────────
class WalletBalanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "No organization"}, status=400)

        from elections.models import VoteTransaction

        recent = VoteTransaction.objects.filter(
            election__organization=org, status='success'
        ).order_by('-created_at')[:10]

        data = {
            'wallet_balance': str(org.wallet_balance),
            'total_earned': str(org.total_earned),
            'recent_transactions': [
                {
                    'id': str(t.id),
                    'election': t.election.title,
                    'candidate': t.candidate.name,
                    'votes': t.votes,
                    'amount': str(t.amount_paid),
                    'commission': str(t.commission_amount),
                    'earned': str(t.organizer_earned),
                    'created_at': t.created_at.isoformat(),
                } for t in recent
            ]
        }
        return Response(data)


class RequestWithdrawalView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "No organization"}, status=400)

        amount = Decimal(request.data.get('amount', '0'))
        if amount <= 0:
            return Response({"error": "Amount must be greater than 0"}, status=400)
        if amount > org.wallet_balance:
            return Response({"error": "Insufficient balance"}, status=400)

        recipient_type = request.data.get('recipient_type')
        recipient_account = request.data.get('recipient_account')
        recipient_name = request.data.get('recipient_name')
        recipient_bank_code = request.data.get('recipient_bank_code')

        if recipient_type not in ['momo', 'bank']:
            return Response({"error": "Invalid recipient type"}, status=400)
        if not recipient_account or not recipient_name:
            return Response({"error": "Recipient account and name are required"}, status=400)

        # For mobile money, if no network code is provided, default to MTN
        if recipient_type == 'momo' and not recipient_bank_code:
            recipient_bank_code = 'MTN'

        if recipient_type == 'bank' and not recipient_bank_code:
            return Response({"error": "Bank code is required for bank transfers"}, status=400)

        withdrawal = WithdrawalRequest.objects.create(
            organization=org,
            amount=amount,
            requested_by=request.user,
            status='pending',
            recipient_type=recipient_type,
            recipient_account=recipient_account,
            recipient_name=recipient_name,
            recipient_bank_code=recipient_bank_code,
        )
        return Response({"message": "Withdrawal requested", "id": str(withdrawal.id)})


class AdminWithdrawalListView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        status_filter = request.query_params.get('status', 'pending')
        withdrawals = WithdrawalRequest.objects.filter(status=status_filter).order_by('-created_at')
        data = [{
            'id': str(w.id),
            'organization': w.organization.name,
            'amount': str(w.amount),
            'status': w.status,
            'requested_by': w.requested_by.email if w.requested_by else '',
            'created_at': w.created_at.isoformat(),
            'recipient_type': w.recipient_type,
            'recipient_account': w.recipient_account,
            'recipient_name': w.recipient_name,
            'recipient_bank_code': w.recipient_bank_code,
            'transfer_reference': w.transfer_reference,
        } for w in withdrawals]
        return Response(data)


class AdminProcessWithdrawalView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def post(self, request, pk):
        withdrawal = get_object_or_404(WithdrawalRequest, pk=pk)
        action = request.data.get('action')

        if action == 'approve':
            if withdrawal.status != 'pending':
                return Response({"error": "Only pending withdrawals can be approved"}, status=400)

            # TEMPORARY: Default to simulation for local testing.
            # In production, set SIMULATE_PAYOUTS=False or remove this line.
            simulate = getattr(settings, 'DEBUG', False) or getattr(settings, 'SIMULATE_PAYOUTS', True)

            transfer_reference = ''

            if simulate:
                # Simulate organization payout
                fake_org_ref = f"SIMU-ORG-{uuid.uuid4().hex[:10]}"
                transfer_reference = fake_org_ref
                # Simulate commission payout (no real API call)
                print(f"Simulated commission payout for withdrawal {withdrawal.id}")
            else:
                # Real Paystack transfers
                try:
                    # 1. Create recipient for organization
                    org_recipient_code = create_transfer_recipient(
                        withdrawal.recipient_type,
                        withdrawal.recipient_name,
                        withdrawal.recipient_account,
                        withdrawal.recipient_bank_code
                    )
                except Exception as e:
                    return Response({"error": f"Failed to create organization recipient: {str(e)}"}, status=500)

                try:
                    # 2. Transfer to organization
                    transfer_org = initiate_transfer(
                        withdrawal.amount,
                        org_recipient_code,
                        f"Withdrawal for {withdrawal.organization.name}"
                    )
                    transfer_reference = transfer_org.get('reference', '')
                except Exception as e:
                    return Response({"error": f"Failed to transfer to organization: {str(e)}"}, status=500)

                # 3. Transfer 20% commission to super admin
                commission = withdrawal.amount * Decimal('0.20')
                if commission > 0:
                    try:
                        super_admin_payout_mode = getattr(settings, 'SUPER_ADMIN_PAYOUT_MODE', 'momo')
                        super_admin_payout_name = getattr(settings, 'SUPER_ADMIN_PAYOUT_NAME', 'AfriVote')
                        super_admin_payout_account = getattr(settings, 'SUPER_ADMIN_PAYOUT_ACCOUNT', '')
                        super_admin_payout_bank_code = getattr(settings, 'SUPER_ADMIN_PAYOUT_BANK_CODE', 'MTN')

                        if not super_admin_payout_account:
                            raise Exception("Super admin payout account is not set in environment variables.")

                        admin_recipient_code = create_transfer_recipient(
                            super_admin_payout_mode,
                            super_admin_payout_name,
                            super_admin_payout_account,
                            super_admin_payout_bank_code
                        )
                        initiate_transfer(
                            commission,
                            admin_recipient_code,
                            f"Commission from withdrawal {withdrawal.id}"
                        )
                    except Exception as e:
                        return Response({"error": f"Failed to process commission: {str(e)}"}, status=500)

            # Update withdrawal status
            withdrawal.status = 'approved'
            withdrawal.resolved_at = timezone.now()
            withdrawal.transfer_reference = transfer_reference
            withdrawal.save()

            # Deduct from organization wallet
            org = withdrawal.organization
            if org.wallet_balance >= withdrawal.amount:
                org.wallet_balance -= withdrawal.amount
                org.save()
            else:
                return Response({"error": "Organization has insufficient balance"}, status=400)

            if simulate:
                return Response({"message": "Withdrawal approved (simulated payout)"})
            else:
                return Response({"message": "Withdrawal approved and payout initiated"})

        elif action == 'reject':
            withdrawal.status = 'rejected'
            withdrawal.resolved_at = timezone.now()
            withdrawal.save()
            return Response({"message": "Withdrawal rejected"})

        return Response({"error": "Invalid action"}, status=400)

class OrgWithdrawalListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "No organization"}, status=400)

        withdrawals = WithdrawalRequest.objects.filter(organization=org).order_by('-created_at')
        data = [{
            'id': str(w.id),
            'amount': str(w.amount),
            'status': w.status,
            'created_at': w.created_at.isoformat(),
            'resolved_at': w.resolved_at.isoformat() if w.resolved_at else None,
            'recipient_type': w.recipient_type,
            'recipient_account': w.recipient_account,
            'recipient_name': w.recipient_name,
            'transfer_reference': w.transfer_reference,
        } for w in withdrawals]
        return Response(data)


class SuperAdminEarningsView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        from elections.models import VoteTransaction

        total_commission = VoteTransaction.objects.filter(
            status='success'
        ).aggregate(total=Sum('commission_amount'))['total'] or Decimal('0')

        total_amount_processed = VoteTransaction.objects.filter(
            status='success'
        ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0')

        total_paid_votes = VoteTransaction.objects.filter(
            status='success'
        ).aggregate(total=Sum('votes'))['total'] or 0

        return Response({
            'total_commission': str(total_commission),
            'total_amount_processed': str(total_amount_processed),
            'total_paid_votes': total_paid_votes,
        })