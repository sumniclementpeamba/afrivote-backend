# organizations/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static

from .views import (
    OrganizationBrandingView,
    OrganizationDetailView,
    OrganizationList,
    OrganizationSelfView,
    approve_organization,
    create_setup_payment,
    mark_org_paid,
    paystack_webhook,
    public_register,
    setup_status,
    WalletBalanceView,
    RequestWithdrawalView,
    AdminWithdrawalListView,
    AdminProcessWithdrawalView,
    OrgWithdrawalListView,
    SuperAdminEarningsView,
)
from elections.views import VoterViewSet

router = DefaultRouter()
router.register(r'voters', VoterViewSet)

urlpatterns = [
    # Router endpoints (optional; only if you want voters under organizations)
    path('api/', include(router.urls)),

    # Organisation self & branding (specific paths first)
    path('me/', OrganizationSelfView.as_view(), name='organization-self'),
    path('me/branding/', OrganizationBrandingView.as_view(), name='organization-branding'),

    # Setup & registration
    path('setup-status/', setup_status, name='organization-setup-status'),
    path('setup-payment/', create_setup_payment, name='organization-setup-payment'),
    path('public-register/', public_register, name='organization-public-register'),
    path('payments/paystack-webhook/', paystack_webhook, name='paystack-webhook'),

    # Wallet & withdrawals
    path('wallet/', WalletBalanceView.as_view(), name='wallet'),
    path('withdraw/', RequestWithdrawalView.as_view(), name='withdraw'),
    path('admin/withdrawals/', AdminWithdrawalListView.as_view(), name='admin-withdrawals'),
    path('admin/withdrawals/<int:pk>/process/', AdminProcessWithdrawalView.as_view(), name='admin-withdraw-process'),
    path('withdrawals/', OrgWithdrawalListView.as_view(), name='org-withdrawals'),
    path('earnings/', SuperAdminEarningsView.as_view(), name='super-admin-earnings'),

    # Admin organisation actions (specific UUID routes)
    path('<uuid:pk>/approve/', approve_organization, name='organization-approve'),
    path('<uuid:pk>/mark-paid/', mark_org_paid, name='organization-mark-paid'),

    # Organisation detail (fallback for UUID)
    path('<uuid:pk>/', OrganizationDetailView.as_view(), name='organization-detail'),

    # Organisation list (empty path)
    path('', OrganizationList.as_view(), name='organization-list'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)