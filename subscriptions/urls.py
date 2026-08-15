from django.urls import path
from .views import (
    CreatePaymentSessionView,
    VerifyPaymentView,
    RequestUpgradeView,
    ListUpgradeRequestsView,
    ProcessUpgradeRequestView,
    RecentUpgradesView,            
)

urlpatterns = [
    path('create-payment/', CreatePaymentSessionView.as_view(), name='create-payment'),
    path('verify-payment/', VerifyPaymentView.as_view(), name='verify-payment'),
    path('request-upgrade/', RequestUpgradeView.as_view(), name='request-upgrade'),
    path('upgrade-requests/', ListUpgradeRequestsView.as_view(), name='upgrade-requests'),
    path('upgrade-requests/<uuid:pk>/process/', ProcessUpgradeRequestView.as_view(), name='process-upgrade-request'),
    path('recent-upgrades/', RecentUpgradesView.as_view(), name='recent-upgrades'),   # ← this
]