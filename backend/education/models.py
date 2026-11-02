import uuid
from django.conf import settings
from django.db import models
from common.deadlines import DeadlineTracked


class Qualification(models.Model):
    lead = models.OneToOneField('leads.Lead', primary_key=True, on_delete=models.PROTECT, related_name='qualification')
    course_interest = models.CharField(max_length=200, blank=True)
    background = models.CharField(max_length=20, choices=[('unknown', 'Not captured'), ('student', 'Student'), ('working', 'Working professional'), ('job_seeker', 'Job seeker'), ('other', 'Other')], default='unknown')
    training_mode = models.CharField(max_length=12, choices=[('undecided', 'Undecided'), ('online', 'Online'), ('classroom', 'Classroom'), ('hybrid', 'Hybrid')], default='undecided')
    preferred_location = models.CharField(max_length=120, blank=True)
    preferred_schedule = models.CharField(max_length=12, choices=[('undecided', 'Undecided'), ('weekday', 'Weekday'), ('weekend', 'Weekend'), ('flexible', 'Flexible')], default='undecided')
    joining_timeline = models.CharField(max_length=12, choices=[('undecided', 'Undecided'), ('immediate', 'Immediately'), ('month', 'Within a month'), ('quarter', 'Within three months'), ('later', 'Later')], default='undecided')
    readiness = models.CharField(max_length=16, choices=[('exploring', 'Exploring'), ('demo_ready', 'Ready for a demo'), ('admission_ready', 'Ready for admission'), ('later', 'Follow up later')], default='exploring')
    notes = models.CharField(max_length=2000, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)


class Demo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey('leads.Lead', on_delete=models.PROTECT, related_name='demos')
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    course = models.CharField(max_length=200)
    mode = models.CharField(max_length=12, choices=[('online', 'Online'), ('classroom', 'Classroom')])
    location = models.CharField(max_length=250)
    starts_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=60)
    status = models.CharField(max_length=12, choices=[('scheduled', 'Scheduled'), ('attended', 'Attended'), ('no_show', 'Did not attend'), ('cancelled', 'Cancelled')], default='scheduled')
    outcome = models.CharField(max_length=2000, blank=True)
    version = models.PositiveIntegerField(default=1)
    client_key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    last_checked_at = models.DateTimeField(null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['starts_at', 'id']
        constraints = [models.UniqueConstraint(fields=['lead', 'client_key'], name='unique_demo_request'),
            models.UniqueConstraint(fields=['lead'], condition=models.Q(status='scheduled'), name='one_scheduled_demo_per_lead')]
        indexes = [models.Index(fields=['branch', 'status', 'starts_at'])]


class DemoTask(DeadlineTracked):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    demo = models.ForeignKey(Demo, on_delete=models.PROTECT, related_name='tasks')
    version = models.PositiveIntegerField()
    kind = models.CharField(max_length=24, choices=[('reminder', 'Confirm demo with student'), ('attendance', 'Record demo attendance'), ('no_show_followup', 'Rebook missed demo'), ('attended_followup', 'Discuss admission after demo')])
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    due_at = models.DateTimeField()
    status = models.CharField(max_length=12, default='pending', choices=[('pending', 'Pending'), ('completed', 'Completed'), ('cancelled', 'Cancelled')])
    resolution = models.CharField(max_length=2000, blank=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['due_at', 'id']
        constraints = [models.UniqueConstraint(fields=['demo', 'version', 'kind'], name='unique_demo_work')]


class JobHealth(models.Model):
    name = models.CharField(max_length=50, primary_key=True)
    last_attempt_at = models.DateTimeField()
    last_success_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
