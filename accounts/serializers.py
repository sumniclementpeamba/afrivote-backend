from rest_framework import serializers
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    profile_picture = serializers.SerializerMethodField()
    organization_plan = serializers.CharField(source='organization.plan', read_only=True, allow_null=True)
    organization_status = serializers.CharField(source='organization.status', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'role', 'organization', 'profile_picture', 'organization_plan', 'organization_status']
        read_only_fields = fields

    def get_profile_picture(self, obj):
        """Return absolute URL for profile picture."""
        if obj.profile_picture:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_picture.url)
            return obj.profile_picture.url
        return None


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user

        if user.role == 'ORG_ADMIN':
            org = user.organization
            if not org or org.status != 'ACTIVE':
                raise serializers.ValidationError(
                    "Your organisation is pending approval. You will be notified once approved."
                )

        return data