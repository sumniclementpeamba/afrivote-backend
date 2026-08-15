from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import ElectionShareLink
from .views import generate_election_results_pdf

@api_view(['GET'])
@permission_classes([AllowAny])
def public_results(request, token):
    link = get_object_or_404(ElectionShareLink, token=token)
    if not link.is_valid():
        return Response({"error": "Link is no longer valid."}, status=404)
    # Return the PDF inline – opens directly in the browser
    return generate_election_results_pdf(link.election, request, disposition='inline')