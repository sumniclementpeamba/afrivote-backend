from rest_framework import serializers
from .models import AuditLog

class AuditLogSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = AuditLog
        fields = ['id', 'organization', 'organization_name', 'user', 'user_email',
                  'action', 'model_name', 'object_id', 'details', 'ip_address', 'created_at']