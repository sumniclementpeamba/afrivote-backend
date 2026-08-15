from rest_framework import serializers
from .models import Organization, OrganizationSettings

class OrganizationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSettings
        fields = [
            'allow_public_results', 'require_voter_verification',
            'voting_anonymity', 'max_candidates_per_position',
            'require_2fa_for_admins', 'ip_restriction_enabled',
            'allowed_ips', 'email_notifications', 'sms_notifications',
            'custom_domain', 'primary_color', 'secondary_color'
        ]

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'email', 'organization_type', 'status', 'plan',
                  'max_voters', 'max_elections', 'description', 'phone', 'website', 'address']
        read_only_fields = ['id', 'slug']

class OrganizationDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'email', 'phone', 'website', 'address',
            'organization_type', 'description',
            'max_voters', 'max_elections', 'plan', 'status',
        ]
        read_only_fields = ['id']

class OrganizationBrandingSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ['logo', 'primary_color', 'logo_url']
        extra_kwargs = {
            'logo': {'required': False},
            'primary_color': {'required': False},
        }

    def get_logo_url(self, obj):
        if obj.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.logo.url)
            return obj.logo.url
        return None

    def validate(self, data):
        org = self.context['organization']
        if org.plan == 'FREE':
            raise serializers.ValidationError("Branding customization is not available on the Free plan.")
        return data