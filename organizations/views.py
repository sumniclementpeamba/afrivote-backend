import uuid
import requests
from django.conf import settings
from django.http import Http404, JsonResponse
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import api_view, permission_classes
from .models import Organization, OrganizationSettings
from .serializers import OrganizationBrandingSerializer, OrganizationSerializer, OrganizationDetailSerializer
from .permissions import IsSuperAdmin, IsOrgAdmin
from audit.utils import log_audit
import datetime
from django.utils import timezone

User = get_user_model()


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

    # Create organisation as PENDING
    org = Organization.objects.create(
        name=org_name,
        email=admin_email,
        phone=phone,
        status='PENDING',
        setup_fee_paid=True,
        setup_fee_transaction_ref=transaction_ref,
    )

    # Create admin user
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
                # Only create if not already exists
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