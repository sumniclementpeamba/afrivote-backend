# organizations/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrganizationBrandingView, OrganizationDetailView, OrganizationList, OrganizationSelfView, approve_organization, create_setup_payment, mark_org_paid, paystack_webhook, public_register, setup_status
from elections.views import VoterViewSet

router = DefaultRouter()
router.register(r'voters', VoterViewSet)

urlpatterns = [
    path('api/', include(router.urls)),
    path('me/', OrganizationSelfView.as_view(), name='organization-self'),
    path('<uuid:pk>/', OrganizationDetailView.as_view(), name='organization-detail'),
    path('', OrganizationList.as_view(), name='organization-list'),
    path('me/branding/', OrganizationBrandingView.as_view(), name='organization-branding'),
    path('setup-status/', setup_status, name='organization-setup-status'),
    path('payments/paystack-webhook/', paystack_webhook, name='paystack-webhook'),
    path('public-register/', public_register, name='organization-public-register'),
    path('<uuid:pk>/approve/', approve_organization, name='organization-approve'),
    path('<uuid:pk>/mark-paid/', mark_org_paid, name='organization-mark-paid'),
    path('setup-payment/', create_setup_payment, name='organization-setup-payment'),
    path('<uuid:pk>/mark-paid/', mark_org_paid, name='organization-mark-paid'),
]