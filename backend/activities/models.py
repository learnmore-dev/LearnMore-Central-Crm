import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Activity(models.Model):
    class Kind(models.TextChoices):
        CONTACT_CREATED = 'contact_created', 'Contact created'
        CONTACT_UPDATED = 'contact_updated', 'Contact updated'
        IDENTIFIER_ADDED = 'identifier_added', 'Identifier added'
        LEAD_CREATED = 'lead_created', 'Lead created'
        LEAD_UPDATED = 'lead_updated', 'Lead updated'
        DUPLICATE_RESOLVED = 'duplicate_resolved', 'Duplicate reviewed'
        NOTE = 'note', 'Internal note'
        ASSIGNMENT = 'assignment', 'Lead assignment'
        SLA_ESCALATED = 'sla_escalated', 'SLA escalated'
        TASK_COMPLETED = 'task_completed', 'Task completed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT, related_name='activities')
    lead = models.ForeignKey('leads.Lead', null=True, blank=True, on_delete=models.PROTECT, related_name='activities')
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='activities')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='activities')
    kind = models.CharField(max_length=24, choices=Kind.choices)
    body = models.TextField(max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['contact', 'created_at']), models.Index(fields=['branch', 'created_at'])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Timeline entries cannot be edited.')
        if self.lead_id and (self.lead.contact_id != self.contact_id or self.lead.branch_id != self.branch_id):
            raise ValidationError('Activity must use its lead contact and branch.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Timeline entries cannot be deleted.')
