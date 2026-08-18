from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static

from . import views as election_views
from elections.public_views import public_results
from .views import (
    ElectionViewSet,
    PositionViewSet,
    CandidateViewSet,
    VoterViewSet,
    system_stats,
    InitiatePaidVoteView,
    VerifyPaidVoteView,
    PublicElectionResultsView,
    PublicElectionDetailView,
    PublicElectionDetailBySlugView,
    PublicPaidElectionsListView,
)

router = DefaultRouter()
router.register(r'elections', ElectionViewSet, basename='election')
router.register(r'positions', PositionViewSet, basename='position')
router.register(r'candidates', CandidateViewSet, basename='candidate')
router.register(r'voters', VoterViewSet, basename='voter')

urlpatterns = [
    path('', include(router.urls)),
    path('system-stats/', system_stats, name='system-stats'),
    path('share/<uuid:token>/', public_results, name='public-share-results'),

    # Public paid election detail – full path: /api/public/elections/<election_id>/
    path('public/elections/<uuid:election_id>/', PublicElectionDetailView.as_view(), name='public-election-detail'),
    path('public/elections/slug/<slug:slug>/', PublicElectionDetailBySlugView.as_view(), name='public-election-detail-by-slug'),
    path('public/elections/', PublicPaidElectionsListView.as_view(), name='public-elections-list'),

    # Paid voting endpoints – full path: /api/<election_id>/initiate-paid-vote/ etc.
    path('<uuid:election_id>/initiate-paid-vote/', InitiatePaidVoteView.as_view(), name='initiate-paid-vote'),
    path('<uuid:election_id>/verify-paid-vote/', VerifyPaidVoteView.as_view(), name='verify-paid-vote'),
    path('<uuid:election_id>/public-results/', PublicElectionResultsView.as_view(), name='election-public-results'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)