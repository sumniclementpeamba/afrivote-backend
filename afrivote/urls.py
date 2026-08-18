from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from elections.public_views import public_results
from elections.views import system_stats
from django.conf import settings
from django.conf.urls.static import static
from elections.views import ElectionViewSet, PositionViewSet, CandidateViewSet, VoterViewSet

router = DefaultRouter()
router.register(r'elections', ElectionViewSet, basename='election')
router.register(r'positions', PositionViewSet, basename='position')
router.register(r'candidates', CandidateViewSet, basename='candidate')
router.register(r'voters', VoterViewSet, basename='voter')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('elections.urls')),
    path('api/organizations/', include('organizations.urls')),
    path('api/system-stats/', system_stats, name='system-stats'),
    path('api/audit-logs/', include('audit.urls')),
    path('api/subscriptions/', include('subscriptions.urls')),

    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    path('share/<uuid:token>/', public_results, name='public-results'),
]

# Serve media files only in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)