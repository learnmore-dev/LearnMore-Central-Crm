import uuid
from django.conf import settings
from django.db import models


class CallLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    client_key = models.CharField(max_length=100)
    request_hash = models.CharField(max_length=64)
    origin = models.CharField(max_length=20, default='manual', editable=False)
    caller_phone = models.CharField(max_length=20)
    caller_name = models.CharField(max_length=200, blank=True)
    business_phone = models.CharField(max_length=20, blank=True)
    direction = models.CharField(max_length=10, choices=[('incoming', 'Incoming'), ('outgoing', 'Outgoing')], default='incoming')
    status = models.CharField(max_length=10, choices=[('answered', 'Answered'), ('missed', 'Missed'), ('voicemail', 'Voicemail')])
    started_at = models.DateTimeField()
    duration_seconds = models.PositiveIntegerField(default=0)
    forwarded_to = models.CharField(max_length=200, blank=True)
    notes = models.CharField(max_length=2000, blank=True)
    contact = models.ForeignKey('contacts.Contact', null=True, on_delete=models.PROTECT, related_name='call_logs')
    review = models.OneToOneField('contacts.DuplicateReview', null=True, on_delete=models.PROTECT)
    lead = models.OneToOneField('leads.Lead', null=True, on_delete=models.PROTECT, related_name='origin_call')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-started_at', '-id']
        constraints = [models.UniqueConstraint(fields=['branch', 'client_key'], name='unique_manual_call_request')]
        indexes = [models.Index(fields=['branch', 'status', 'started_at'])]
