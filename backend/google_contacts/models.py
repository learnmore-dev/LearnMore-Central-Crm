import uuid
from django.conf import settings
from django.db import models


class GoogleConnection(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    namespace = models.UUIDField(default=uuid.uuid4, editable=False)
    account_id = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    refresh_token_encrypted = models.TextField(blank=True)
    state = models.CharField(max_length=20, default='disconnected')
    automatic = models.BooleanField(default=False)
    interval_minutes = models.PositiveIntegerField(default=15)
    last_scheduled_at = models.DateTimeField(null=True)
    last_success_at = models.DateTimeField(null=True)
    last_worker_at = models.DateTimeField(null=True)
    last_error = models.CharField(max_length=100, blank=True)
    connected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    lease = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)


class GoogleOAuthAttempt(models.Model):
    digest = models.CharField(max_length=64, primary_key=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session_digest = models.CharField(max_length=64)
    verifier_encrypted = models.TextField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)


class GoogleContactLink(models.Model):
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT)
    account_id = models.CharField(max_length=255)
    resource_name = models.CharField(max_length=255, blank=True)
    local_hash = models.CharField(max_length=64, blank=True)
    remote_hash = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=20, default='linked')
    error_code = models.CharField(max_length=100, blank=True)
    synced_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['contact', 'account_id'], name='google_contact_per_account')]


class GoogleSyncJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account_id = models.CharField(max_length=255)
    email = models.EmailField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default='preview')
    automatic = models.BooleanField(default=False)
    error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class GoogleSyncItem(models.Model):
    job = models.ForeignKey(GoogleSyncJob, on_delete=models.CASCADE, related_name='items')
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT)
    action = models.CharField(max_length=20)
    status = models.CharField(max_length=20, default='planned')
    reason = models.CharField(max_length=150, blank=True)
    payload = models.JSONField(default=dict)
    local_hash = models.CharField(max_length=64, blank=True)
    resource_name = models.CharField(max_length=255, blank=True)
    remote_hash = models.CharField(max_length=64, blank=True)
    candidates = models.JSONField(default=list)

    class Meta:
        ordering = ['pk']
        constraints = [models.UniqueConstraint(fields=['job', 'contact'], name='google_sync_job_contact')]
