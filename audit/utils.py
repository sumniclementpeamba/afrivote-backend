# audit/utils.py
from .models import AuditLog

def log_audit(user, action, model_name, object_id, details=None, organization=None, request=None):
    """
    Create an AuditLog entry. Automatically extracts IP from request if provided.
    """
    ip = None
    if request:
        ip = request.META.get('REMOTE_ADDR')
    AuditLog.objects.create(
        organization=organization,
        user=user,
        action=action,
        model_name=model_name,
        object_id=str(object_id),
        details=details or {},
        ip_address=ip
    )