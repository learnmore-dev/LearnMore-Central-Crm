import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from common.deadlines import DeadlineTracked


class AutomationRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    name = models.CharField(max_length=150)
    source = models.CharField(max_length=12, choices=[('all', 'All sources'), ('website', 'Website'), ('call', 'Calls'), ('whatsapp', 'WhatsApp'), ('manual', 'Manual')], default='all')
    is_active = models.BooleanField(default=False)
    enabled_at = models.DateTimeField(null=True)
    version = models.PositiveIntegerField(default=1)
    acknowledgement_minutes = models.PositiveIntegerField(default=2)
    acknowledgement_text = models.CharField(max_length=2000, default='Hello {name}, thank you for your interest in {course}. A counsellor will contact you shortly.')
    callback_minutes = models.PositiveIntegerField(default=5)
    business_hours = models.BooleanField(default=True)
    start_hour = models.PositiveSmallIntegerField(default=9)
    end_hour = models.PositiveSmallIntegerField(default=18)
    steps = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [models.UniqueConstraint(fields=['branch', 'source'], condition=models.Q(is_active=True), name='one_active_automation_scope')]


class AutomationRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.ForeignKey(AutomationRule, on_delete=models.PROTECT)
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    lead = models.OneToOneField('leads.Lead', null=True, on_delete=models.PROTECT, related_name='automation_run')
    call = models.OneToOneField('calls.CallLog', null=True, on_delete=models.PROTECT, related_name='automation_run')
    conversation = models.OneToOneField('messaging.Conversation', null=True, on_delete=models.PROTECT, related_name='automation_run')
    snapshot = models.JSONField()
    source = models.CharField(max_length=12)
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    target_key = models.CharField(max_length=100)
    state = models.CharField(max_length=12, default='active', choices=[('active', 'Active'), ('paused', 'Paused'), ('stopped', 'Stopped'), ('completed', 'Completed')])
    reason = models.CharField(max_length=250, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    paused_at = models.DateTimeField(null=True)
    watch_since = models.DateTimeField(default=timezone.now)
    last_checked_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-started_at', '-id']
        constraints = [models.CheckConstraint(condition=(models.Q(lead__isnull=False, call__isnull=True, conversation__isnull=True) |
            models.Q(lead__isnull=True, call__isnull=False, conversation__isnull=True) |
            models.Q(lead__isnull=True, call__isnull=True, conversation__isnull=False)), name='automation_exactly_one_target')]


class AutomationStep(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(AutomationRun, on_delete=models.PROTECT, related_name='scheduled_steps')
    position = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=10)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=2000, blank=True)
    due_at = models.DateTimeField()
    grace_minutes = models.PositiveIntegerField(default=15)
    status = models.CharField(max_length=12, default='pending')

    class Meta:
        ordering = ['due_at', 'position']
        constraints = [models.UniqueConstraint(fields=['run', 'position'], name='unique_automation_step')]
        indexes = [models.Index(fields=['status', 'due_at'])]


class AutomationTask(DeadlineTracked):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(AutomationRun, on_delete=models.PROTECT, related_name='work_items')
    step = models.OneToOneField(AutomationStep, null=True, on_delete=models.PROTECT)
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='automation_tasks')
    title = models.CharField(max_length=200)
    due_at = models.DateTimeField()
    status = models.CharField(max_length=12, default='pending')
    resolution = models.CharField(max_length=2000, blank=True)
    escalated_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['due_at', 'id']
        indexes = [models.Index(fields=['status', 'due_at'])]


class AutomationEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(AutomationRun, on_delete=models.PROTECT, related_name='events')
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    code = models.CharField(max_length=40)
    detail = models.CharField(max_length=2500)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
