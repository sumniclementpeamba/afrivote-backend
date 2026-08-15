from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static
from elections.public_views import public_results
from .views import ElectionViewSet, PositionViewSet, CandidateViewSet, VoterViewSet, system_stats
from .views import (
    ElectionViewSet, PositionViewSet,
    CandidateViewSet, VoterViewSet,
)

router = DefaultRouter()
router.register(r'elections', ElectionViewSet, basename='election')
router.register(r'positions', PositionViewSet, basename='position')
router.register(r'candidates', CandidateViewSet, basename='candidate')
router.register(r'voters', VoterViewSet, basename='voter')

urlpatterns = [
    path('', include(router.urls)),
    path('system-stats/', system_stats, name='system-stats'),
    path('share/<uuid:token>/', public_results, name='public-results'),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
