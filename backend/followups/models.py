import uuid
from django.conf import settings
from django.db import models
from common.deadlines import DeadlineTracked


class FollowUpTask(DeadlineTracked):
    class Kind(models.TextChoices):
        ACKNOWLEDGEMENT = 'acknowledgement', 'Assignment acknowledgement'
        FOLLOW_UP = 'follow_up', 'Follow-up'
        CALLBACK = 'callback', 'Missed-call callback'
        APPOINTMENT = 'appointment', 'Demo or counselling appointment'
        UNASSIGNED = 'unassigned', 'Unassigned enquiry alert'
        ESCALATION = 'escalation', 'Manager escalation'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'
        ESCALATED = 'escalated', 'Escalated'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey('leads.Lead', on_delete=models.PROTECT, related_name='tasks')
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='followup_tasks')
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='followup_tasks')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=500)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    due_at = models.DateTimeField()
    assignment_version = models.PositiveBigIntegerField(default=0)
    dedupe_key = models.CharField(max_length=160, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='created_followup_tasks')
    resolution = models.TextField(blank=True, max_length=2000)
    completed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_at', 'id']
        indexes = [models.Index(fields=['status', 'due_at']), models.Index(fields=['branch', 'status'])]


class DeadlineMiss(models.Model):
    origin = models.CharField(max_length=20)
    task_id = models.UUIDField()
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    lead = models.ForeignKey('leads.Lead', null=True, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    course = models.CharField(max_length=200)
    title = models.CharField(max_length=500)
    target = models.CharField(max_length=250)
    due_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['origin', 'task_id'], name='unique_task_deadline_miss')]
        indexes = [models.Index(fields=['branch', 'due_at'])]
