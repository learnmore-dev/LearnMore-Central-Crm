import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class Channel(models.Model):
    """Non-secret identifiers only. One Meta phone number belongs to one branch."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    phone_number_id = models.CharField(max_length=40, unique=True)
    waba_id = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)
    business_phone = models.CharField(max_length=20, blank=True)
    intake_actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='whatsapp_intake_channels')
    auto_intake = models.BooleanField(default=True)

    class Meta:
        ordering = ['name', 'id']


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name='conversations')
    wa_id = models.CharField(max_length=20)
    contact = models.ForeignKey('contacts.Contact', null=True, on_delete=models.PROTECT)
    lead = models.ForeignKey('leads.Lead', null=True, blank=True, on_delete=models.PROTECT, related_name='whatsapp_conversations')
    review = models.OneToOneField('contacts.DuplicateReview', null=True, blank=True, on_delete=models.PROTECT, related_name='whatsapp_conversation')
    identity_status = models.CharField(max_length=12, default='unlinked', choices=[('unlinked', 'Not linked'), ('new', 'New contact'), ('matched', 'Existing contact'), ('review', 'Identity review'), ('rejected', 'Identity rejected'), ('blocked', 'Intake needs configuration')])
    intake_note = models.CharField(max_length=250, blank=True)
    last_inbound_at = models.DateTimeField(null=True)
    consent = models.CharField(max_length=10, choices=[('unknown', 'Unknown'), ('granted', 'Granted'), ('revoked', 'Revoked')], default='unknown')
    consent_evidence = models.CharField(max_length=1000, blank=True)
    consent_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-updated_at', '-id']
        constraints = [models.UniqueConstraint(fields=['channel', 'wa_id'], name='unique_wa_conversation')]


class ConsentEvent(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name='consent_events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    state = models.CharField(max_length=10)
    evidence = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)


class Template(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name='templates')
    provider_id = models.CharField(max_length=100)
    name = models.CharField(max_length=512)
    language = models.CharField(max_length=20)
    status = models.CharField(max_length=40)
    category = models.CharField(max_length=40, blank=True, default='')
    body = models.TextField(blank=True)
    parameter_count = models.PositiveSmallIntegerField(default=0)
    supported = models.BooleanField(default=False)
    source_mode = models.CharField(max_length=4)
    synced_at = models.DateTimeField()

    class Meta:
        ordering = ['name', 'language', 'id']
        constraints = [models.UniqueConstraint(fields=['channel', 'name', 'language'], name='unique_wa_template')]


class Message(models.Model):
    class QueueStatus(models.TextChoices):
        RECEIVED = 'received', 'Received'
        QUEUED = 'queued', 'Queued'
        RETRY = 'retry', 'Retry scheduled'
        SENDING = 'sending', 'Dispatch in progress'
        SENT = 'sent', 'Accepted by provider'
        FAILED = 'failed', 'Failed'
        BLOCKED = 'blocked', 'Policy blocked'
        UNKNOWN = 'unknown', 'Outcome unknown; reconcile before resending'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name='messages')
    direction = models.CharField(max_length=8, choices=[('inbound', 'Inbound'), ('outbound', 'Outbound')])
    kind = models.CharField(max_length=30, default='text')
    text = models.TextField(blank=True)
    template = models.ForeignKey(Template, null=True, on_delete=models.PROTECT)
    parameters = models.JSONField(default=list)
    client_key = models.CharField(max_length=100, null=True)
    request_hash = models.CharField(max_length=64, blank=True)
    provider_id = models.CharField(max_length=254, null=True, unique=True)
    mode = models.CharField(max_length=4)
    queue_status = models.CharField(max_length=10, choices=QueueStatus.choices, default=QueueStatus.QUEUED)
    delivery_status = models.CharField(max_length=10, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    claimed_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-occurred_at', '-id']
        constraints = [models.UniqueConstraint(fields=['conversation', 'client_key'], name='unique_wa_outbound_request')]
        indexes = [models.Index(fields=['queue_status', 'next_attempt_at'])]


class WebhookDelivery(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    status = models.CharField(max_length=10, default='pending')
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        indexes = [models.Index(fields=['status', 'next_attempt_at'])]


class WebhookEvent(models.Model):
    key = models.CharField(max_length=64, unique=True)
    delivery = models.ForeignKey(WebhookDelivery, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class CannedMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    title = models.CharField(max_length=100)
    body = models.TextField(max_length=4096)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['title', 'id']


class Campaign(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT)
    name = models.CharField(max_length=150)
    template = models.ForeignKey(Template, on_delete=models.PROTECT)
    parameters = models.JSONField(default=list)
    recipients = models.ManyToManyField(Conversation)
    messages = models.ManyToManyField(Message)
    status = models.CharField(max_length=10, default='draft')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class AdDraft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    name = models.CharField(max_length=150)
    destination = models.URLField(max_length=1000)
    platform = models.CharField(max_length=20, choices=[('facebook', 'Facebook'), ('instagram', 'Instagram')])
    campaign_tag = models.SlugField(max_length=100)
    notes = models.CharField(max_length=1000, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

class WhatsAppConnection(models.Model):
    """Single organization-wide encrypted credential configuration; sending gates stay server-owned."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    access_token_encrypted = models.TextField(blank=True)
    app_secret_encrypted = models.TextField(blank=True)
    verify_token_encrypted = models.TextField(blank=True)
    graph_version = models.CharField(max_length=16, blank=True)
    webhook_url = models.URLField(max_length=500, blank=True)
    webhook_verified_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='one_whatsapp_connection')]
