from django.contrib import admin
from .models import Organization, OrganizationSettings

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'plan', 'status', 'created_at')
    list_filter = ('plan', 'status', 'organization_type')
    search_fields = ('name', 'email', 'slug')
    prepopulated_fields = {'slug': ('name',)}

@admin.register(OrganizationSettings)
class OrganizationSettingsAdmin(admin.ModelAdmin):
    list_display = ('organization', 'require_voter_verification', 'email_notifications')