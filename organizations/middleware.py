from django.shortcuts import get_object_or_404
from django.http import Http404
from organizations.models import Organization

class OrganizationMiddleware:
    """
    Ensures all database queries are scoped to the user's organization.
    Adds the organization to the request object.
    """
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Skip organization check for super admins and certain paths
        if hasattr(request, 'user') and request.user.is_authenticated:
            if request.user.is_super_admin:
                # Super admins can access all organizations
                org_slug = request.headers.get('X-Organization-Slug')
                if org_slug:
                    request.organization = get_object_or_404(
                        Organization, 
                        slug=org_slug,
                        is_deleted=False
                    )
                else:
                    request.organization = None
            elif request.user.organization:
                request.organization = request.user.organization
                # Ensure organization is active
                if request.organization.status != 'ACTIVE':
                    raise Http404("Organization is not active")
            else:
                raise Http404("No organization associated with user")
        
        response = self.get_response(request)
        return response