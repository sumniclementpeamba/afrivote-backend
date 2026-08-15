# audit/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import AuditLog
from .serializers import AuditLogSerializer
from organizations.permissions import IsNotVoter

class AuditLogListView(APIView):
    permission_classes = [IsAuthenticated, IsNotVoter]

    def get(self, request):
        user = request.user
        if user.role == 'SUPER_ADMIN':
            queryset = AuditLog.objects.all()
        else:
            queryset = AuditLog.objects.filter(organization=user.organization)
        # Optional: add date filters or limit via query params
        limit = request.query_params.get('limit', 100)
        queryset = queryset[:int(limit)]
        serializer = AuditLogSerializer(queryset, many=True)
        return Response(serializer.data)