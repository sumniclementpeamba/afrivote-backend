from rest_framework.permissions import BasePermission

class IsNotVoter(BasePermission):
    """
    Allows access only to non‑voter users (SUPER_ADMIN, ORG_ADMIN, ELECTION_MANAGER).
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role != 'VOTER'

class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'SUPER_ADMIN'

class IsOrgAdmin(BasePermission):
    """
    Allows ORG_ADMIN and SUPER_ADMIN (super admin can do everything an org admin can).
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ['ORG_ADMIN', 'SUPER_ADMIN']