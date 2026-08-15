from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone
import uuid


class Election(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SCHEDULED', 'Scheduled'),
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    ELECTION_TYPE_CHOICES = [
        ('SINGLE', 'Single Position'),
        ('MULTIPLE', 'Multiple Positions'),
        ('REFERENDUM', 'Referendum'),
        ('SURVEY', 'Survey'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='elections'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    election_type = models.CharField(max_length=20, choices=ELECTION_TYPE_CHOICES)

    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    is_anonymous = models.BooleanField(default=True)
    allow_write_ins = models.BooleanField(default=False)
    require_voter_verification = models.BooleanField(default=True)
    show_results_during_election = models.BooleanField(default=False)
    show_results_after_election = models.BooleanField(default=True)

    eligible_voter_count = models.IntegerField(default=0)
    minimum_voter_age = models.IntegerField(default=0)
    allowed_domains = models.TextField(blank=True)

    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_elections'
    )
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'elections'
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['start_date', 'end_date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F('start_date')),
                name='end_date_after_start_date'
            )
        ]

    def __str__(self):
        return f"{self.title} - {self.organization.name}"

    def save(self, *args, **kwargs):
        if self.start_date and self.end_date:
            if self.end_date <= self.start_date:
                # Auto-fix: set end_date to start_date + 1 hour (or 1 day)
                from datetime import timedelta
                self.end_date = self.start_date + timedelta(days=1)
        super().save(*args, **kwargs)

    @property
    def is_active(self):
        now = timezone.now()
        return (self.status == 'ACTIVE' and
                self.start_date <= now <= self.end_date)

    @property
    def total_votes_cast(self):
        return Vote.objects.filter(
            position__election=self
        ).count()


class Position(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    election = models.ForeignKey(
        Election,
        on_delete=models.CASCADE,
        related_name='positions'
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    max_selections = models.IntegerField(default=1)
    order = models.IntegerField(default=0)
    is_required = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'positions'
        ordering = ['display_order', 'created_at']
        unique_together = ['election', 'title']

    def __str__(self):
        return f"{self.title} - {self.election.title}"


class Candidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        related_name='candidates'
    )

    name = models.CharField(max_length=255)
    biography = models.TextField(blank=True)
    biography_file = models.FileField(upload_to='candidates/biography/', null=True, blank=True)
    manifesto = models.TextField(blank=True)
    manifesto_file = models.FileField(upload_to='candidates/manifesto/', null=True, blank=True)
    photo = models.ImageField(upload_to='candidates/', null=True, blank=True)

    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    department = models.CharField(max_length=100, blank=True)

    is_approved = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    # New field for drag‑and‑drop ordering
    order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'candidates'
        ordering = ['order', 'name']   # order by custom order, then name
        unique_together = ['position', 'email']

    def __str__(self):
        return f"{self.name} - {self.position.title}"

    @property
    def vote_count(self):
        return Vote.objects.filter(candidate=self).count()


class Voter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='voters'
    )
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='voter_profile'
    )

    voter_id = models.CharField(max_length=50, unique=True)
    email = models.EmailField()
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True)

    department = models.CharField(max_length=100, blank=True)
    grade_level = models.CharField(max_length=50, blank=True)
    registration_number = models.CharField(max_length=50, blank=True)

    is_verified = models.BooleanField(default=False)
    verification_code = models.CharField(max_length=10, blank=True)
    qr_code = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    has_voted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'voters'
        unique_together = ['organization', 'email']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['voter_id']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.voter_id})"


class Vote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE
    )
    election = models.ForeignKey(
        Election,
        on_delete=models.CASCADE,
        related_name='votes'
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        related_name='votes'
    )
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name='votes'
    )

    vote_hash = models.CharField(max_length=255, unique=True)

    voted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        db_table = 'votes'
        constraints = [
            models.UniqueConstraint(
                fields=['election', 'position', 'vote_hash'],
                name='unique_vote_per_position'
            )
        ]
        indexes = [
            models.Index(fields=['election', 'position']),
            models.Index(fields=['voted_at']),
        ]

    def __str__(self):
        return f"Vote in {self.election.title} - {self.position.title}"


class VoterRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE
    )
    voter = models.ForeignKey(
        Voter,
        on_delete=models.CASCADE,
        related_name='voting_records'
    )
    election = models.ForeignKey(
        Election,
        on_delete=models.CASCADE,
        related_name='voter_records'
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        null=True,
        related_name='voter_records'
    )
    vote_hash = models.CharField(max_length=255)

    voted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'voter_records'
        constraints = [
            models.UniqueConstraint(
                fields=['voter', 'election', 'position'],
                name='one_vote_per_voter_per_election_per_position'
            )
        ]

    def __str__(self):
        return f"{self.voter} voted in {self.election}"


# ---------- SIGNAL to clean up votes when a voter is deleted ----------
@receiver(pre_delete, sender=Voter)
def delete_voter_votes(sender, instance, **kwargs):
    Vote.objects.filter(
        vote_hash__in=VoterRecord.objects.filter(voter=instance).values('vote_hash')
    ).delete()
    VoterRecord.objects.filter(voter=instance).delete()


class ElectionShareLink(models.Model):
    election = models.OneToOneField(Election, on_delete=models.CASCADE, related_name='share_link')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self):
        if not self.is_active:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True