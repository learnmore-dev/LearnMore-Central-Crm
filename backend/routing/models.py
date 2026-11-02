import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class CounsellorProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='counsellor_profile')
    is_available = models.BooleanField(default=False)
    can_receive_leads = models.BooleanField(default=True)
    max_active_leads = models.PositiveIntegerField(default=50)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']


class RoutingPolicy(models.Model):
    branch = models.OneToOneField('branches.Branch', primary_key=True, on_delete=models.PROTECT, related_name='routing_policy')
    last_position = models.PositiveBigIntegerField(default=0, editable=False)
    acknowledgement_minutes = models.PositiveIntegerField(default=15)
    followup_minutes = models.PositiveIntegerField(default=60)
    max_reassignments = models.PositiveIntegerField(default=2)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(acknowledgement_minutes__gte=1), name='positive_ack_deadline'),
            models.CheckConstraint(condition=models.Q(followup_minutes__gte=1), name='positive_followup_deadline'),
        ]


class AssignmentHistory(models.Model):
    class Status(models.TextChoices):
        ASSIGNED = 'assigned', 'Assigned'
        REASSIGNED = 'reassigned', 'Reassigned'
        QUEUED = 'queued', 'Queued'
        TRANSFERRED = 'transferred', 'Branch transferred'
        ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
        ESCALATED = 'escalated', 'Escalated'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey('leads.Lead', on_delete=models.PROTECT, related_name='assignment_history')
    previous_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='previous_assignments')
    new_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='new_assignments')
    previous_branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='outgoing_assignments')
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='assignment_history')
    reason = models.TextField(max_length=2000)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='assignment_actions')
    status = models.CharField(max_length=16, choices=Status.choices)
    version = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['branch', 'created_at']), models.Index(fields=['lead', 'version'])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Assignment history is immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Assignment history is immutable.')
