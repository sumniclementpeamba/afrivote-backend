from django.db import models
from organizations.models import Organization
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()

class Subscription(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('past_due', 'Past Due'),
        ('canceled', 'Canceled'),
        ('incomplete', 'Incomplete'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name='subscription'
    )
    payment_gateway = models.CharField(max_length=20, default='paystack')
    gateway_subscription_id = models.CharField(max_length=255, blank=True)
    gateway_customer_id = models.CharField(max_length=255, blank=True)
    plan = models.CharField(max_length=20, choices=Organization.PLAN_CHOICES, default='FREE')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='incomplete')
    current_period_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    subscription_ends_at = models.DateTimeField(null=True, blank=True)   # <-- ADD

    def __str__(self):
        return f"{self.organization.name} - {self.plan}"


class PlanUpgradeRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='upgrade_requests')
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    current_plan = models.CharField(max_length=20, choices=Organization.PLAN_CHOICES)
    requested_plan = models.CharField(max_length=20, choices=Organization.PLAN_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.organization.name} → {self.requested_plan} ({self.status})"