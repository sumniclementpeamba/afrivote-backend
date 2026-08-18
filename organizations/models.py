from django.db import models
from django.utils.text import slugify
import uuid

class Organization(models.Model):
    """
    The central tenant model. Every organization gets its own isolated workspace.
    """
    PLAN_CHOICES = [
        ('FREE', 'Free'),
        ('STANDARD', 'Standard'),
        ('ENTERPRISE', 'Enterprise'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending Approval'),
        ('ACTIVE', 'Active'),
        ('SUSPENDED', 'Suspended'),
        ('INACTIVE', 'Inactive'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to='organization_logos/', null=True, blank=True)
    setup_fee_paid = models.BooleanField(default=False)
    setup_fee_transaction_ref = models.CharField(max_length=100, blank=True)
    free_results_downloads_used = models.IntegerField(default=0)
    
    # Wallet fields for paid voting
    wallet_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_earned = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Organization details
    organization_type = models.CharField(max_length=50, choices=[
        ('SCHOOL', 'School'),
        ('CHURCH', 'Church'),
        ('COMPANY', 'Company'),
        ('NGO', 'NGO'),
        ('ASSOCIATION', 'Association'),
        ('PROFESSIONAL_BODY', 'Professional Body'),
        ('OTHER', 'Other'),
    ])
    
    # Contact information
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    website = models.URLField(blank=True)
    address = models.TextField(blank=True)
    
    # Subscription and status
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='FREE')
    subscription_ends_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    primary_color = models.CharField(max_length=7, default='#4F46E5', help_text='Hex color code, e.g. #4F46E5')
    
    # Limits
    max_voters = models.IntegerField(default=100)
    max_elections = models.IntegerField(default=1)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'organizations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class OrganizationSettings(models.Model):
    """Configuration settings for each organization"""
    organization = models.OneToOneField(
        Organization, 
        on_delete=models.CASCADE, 
        related_name='settings'
    )
    
    # Election settings
    allow_public_results = models.BooleanField(default=False)
    require_voter_verification = models.BooleanField(default=True)
    voting_anonymity = models.BooleanField(default=True)
    max_candidates_per_position = models.IntegerField(default=10)
    
    # Security settings
    require_2fa_for_admins = models.BooleanField(default=False)
    ip_restriction_enabled = models.BooleanField(default=False)
    allowed_ips = models.TextField(blank=True, help_text="Comma-separated IP addresses")
    
    # Notification settings
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    
    # Branding
    custom_domain = models.CharField(max_length=255, blank=True)
    primary_color = models.CharField(max_length=7, default='#0066CC')
    secondary_color = models.CharField(max_length=7, default='#004499')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'organization_settings'
        verbose_name_plural = 'Organization Settings'


class WithdrawalRequest(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, default='pending')  # pending, approved, rejected
    requested_by = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    # NEW: recipient details for payout
    recipient_type = models.CharField(
        max_length=20,
        choices=[('momo', 'Mobile Money'), ('bank', 'Bank Account')],
        default='momo'
    )
    recipient_account = models.CharField(max_length=100, blank=True)  # mobile number or bank account number
    recipient_name = models.CharField(max_length=255, blank=True)
    recipient_bank_code = models.CharField(max_length=20, blank=True)  # bank code or mobile provider code (MTN, VOD, ATL)

    # NEW: transfer reference for tracking
    transfer_reference = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.organization.name} - {self.amount} - {self.status}"