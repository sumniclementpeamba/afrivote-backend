from rest_framework_simplejwt.authentication import JWTAuthentication

class QueryParamJWTAuthentication(JWTAuthentication):
    """
    Authenticate using a JWT passed as a query parameter `token`.
    """
    def authenticate(self, request):
        token = request.query_params.get('token')
        if token is None:
            return None

        # Validate the token using the standard method
        validated_token = self.get_validated_token(token)
        user = self.get_user(validated_token)
        return (user, validated_token)