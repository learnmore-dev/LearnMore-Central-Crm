import hashlib
import json
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from common.access import require_manager
from common.permissions import has_global_scope
from .models import Channel, Conversation, ConsentEvent, Message, Template, WebhookDelivery, WebhookEvent
from .provider import ProviderError, send_message, fetch_templates

MAX_ATTEMPTS = 5


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def window_open(conversation):
    now = timezone.now()
    return bool(conversation.last_inbound_at and now - timedelta(hours=24) < conversation.last_inbound_at <= now)


def require_messaging(actor, channel):
    if not actor.is_authenticated or not actor.is_active or not (has_global_scope(actor) or actor.role in ('branch_manager', 'counsellor', 'support')):
        raise PermissionDenied('Messaging access is required.')
    if not has_global_scope(actor) and actor.branch_id != channel.branch_id:
        raise PermissionDenied('This inbox belongs to another branch.')
    if not channel.is_active or not channel.branch.is_active:
        raise ValidationError('This inbox is inactive.')


def check_policy(conversation, *, mode, template=None, parameters=None):
    if mode != settings.WHATSAPP_MODE:
        raise ValidationError('Provider mode changed; this message is blocked.')
    if mode not in ('mock', 'live'):
        raise ValidationError('Invalid WhatsApp mode.')
    if mode == 'live' and not settings.WHATSAPP_LIVE_SENDS_ENABLED:
        raise ValidationError('Live sends are disabled pending approval.')
    if not conversation.channel.is_active or not conversation.channel.branch.is_active:
        raise ValidationError('This inbox is inactive.')
    if conversation.consent == 'revoked':
        raise ValidationError('Customer opted out. Record new explicit consent before sending.')
    if template is None:
        if not window_open(conversation):
            raise ValidationError('The 24-hour customer-service window is closed. Use an approved template.')
        return
    if conversation.consent != 'granted':
        raise ValidationError('Explicit consent with evidence is required for template messages.')
    if template.channel_id != conversation.channel_id or template.status != 'APPROVED' or not template.supported:
        raise ValidationError('Choose a supported approved template for this inbox.')
    if template.source_mode != mode or template.synced_at < timezone.now() - timedelta(hours=24):
        raise ValidationError('Template approval must be refreshed from the current provider within 24 hours.')
    if not isinstance(parameters, list) or len(parameters) != template.parameter_count or any(
            not isinstance(p, str) or not p.strip() or len(p) > 1024 for p in parameters):
        raise ValidationError('Supply the required text parameters for this template.')


@transaction.atomic
def enqueue(*, actor, conversation, client_key, text='', template=None, parameters=None):
    channel = Channel.objects.select_for_update().select_related('branch').get(pk=conversation.channel_id)
    require_messaging(actor, channel)
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    conversation.channel = channel
    if not isinstance(client_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', client_key):
        raise ValidationError('A unique client_key is required.')
    parameters = parameters if parameters is not None else []
    if template:
        template = Template.objects.get(pk=template.pk)
        if text:
            raise ValidationError('Send either text or a template.')
    elif not isinstance(text, str) or not text.strip() or len(text) > 4096 or parameters:
        raise ValidationError('Text messages require 1–4096 characters and no template parameters.')
    digest = fingerprint({'text': text, 'template': str(template.pk) if template else None, 'parameters': parameters})
    previous = Message.objects.filter(conversation=conversation, client_key=client_key).first()
    if previous:
        if previous.request_hash != digest:
            raise ValidationError('This client_key was already used for a different message.')
        return previous
    check_policy(conversation, mode=settings.WHATSAPP_MODE, template=template, parameters=parameters)
    message = Message.objects.create(conversation=conversation, direction='outbound', kind='template' if template else 'text',
        text=text, template=template, parameters=parameters, client_key=client_key, request_hash=digest,
        mode=settings.WHATSAPP_MODE, created_by=actor)
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=['updated_at'])
    return message


@transaction.atomic
def set_consent(*, actor, conversation, state, evidence):
    channel = Channel.objects.select_for_update().select_related('branch').get(pk=conversation.channel_id)
    require_messaging(actor, channel)
    if state not in ('granted', 'revoked') or not evidence.strip() or len(evidence) > 1000:
        raise ValidationError('Record explicit consent or revocation with evidence.')
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    conversation.consent, conversation.consent_evidence, conversation.consent_at = state, evidence, timezone.now()
    conversation.save(update_fields=['consent', 'consent_evidence', 'consent_at'])
    ConsentEvent.objects.create(conversation=conversation, state=state, evidence=evidence, actor=actor)
    return conversation


@transaction.atomic
def link_contact(*, actor, conversation, contact):
    channel = Channel.objects.select_for_update().select_related('branch').get(pk=conversation.channel_id)
    require_manager(actor, channel.branch)
    if contact.branch_id != channel.branch_id:
        raise ValidationError('Choose a contact in this inbox branch.')
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    if conversation.review_id and conversation.review.status == 'pending':
        raise ValidationError('Resolve the pending identity review before linking a contact.')
    if conversation.contact_id and conversation.contact_id != contact.pk:
        raise ValidationError('An existing contact link cannot be replaced.')
    conversation.contact = contact
    conversation.save(update_fields=['contact'])
    if conversation.last_inbound_at:
        from .intake import receive
        receive(conversation)
    return conversation


def dispatch_message(message_id):
    # Lock order is channel -> conversation -> message, shared with webhook processing.
    channel_id, conversation_id = Message.objects.values_list('conversation__channel_id', 'conversation_id').get(pk=message_id)
    with transaction.atomic():
        channel = Channel.objects.select_for_update().select_related('branch').get(pk=channel_id)
        conversation = Conversation.objects.select_for_update().get(pk=conversation_id)
        message = Message.objects.select_for_update(of=('self',)).select_related('template', 'created_by').get(pk=message_id)
        if message.queue_status not in ('queued', 'retry') or message.next_attempt_at > timezone.now():
            return
        message.conversation = conversation
        conversation.channel = channel
        try:
            require_messaging(message.created_by, channel)
            check_policy(message.conversation, mode=message.mode, template=message.template, parameters=message.parameters)
        except (ValidationError, PermissionDenied):
            message.queue_status, message.error_code = 'blocked', 'policy_changed'
            message.save(update_fields=['queue_status', 'error_code'])
            return
        message.queue_status, message.claimed_at = 'sending', timezone.now()
        message.attempts += 1
        message.save(update_fields=['queue_status', 'claimed_at', 'attempts'])
    # Claim is durable BEFORE network I/O. A crashed claim is never blindly resent.
    try:
        provider_id = send_message(message)
        failure = None
    except ProviderError as error:
        failure, provider_id = error, None
    except Exception:
        failure, provider_id = ProviderError('unexpected_dispatch_error', ambiguous=True), None
    with transaction.atomic():
        saved = Message.objects.select_for_update().get(pk=message_id)
        if saved.queue_status != 'sending':
            return  # a delivery webhook may already have reconciled this send
        if not failure:
            saved.provider_id, saved.queue_status = provider_id, 'sent'
            saved.error_code = ''
        else:
            saved.error_code = failure.code
            if failure.ambiguous:
                saved.queue_status = 'unknown'
            elif failure.retryable and saved.attempts < MAX_ATTEMPTS:
                saved.queue_status = 'retry'
                saved.next_attempt_at = timezone.now() + timedelta(seconds=max(failure.retry_after, min(3600, 30 * 2 ** (saved.attempts - 1))))
            else:
                saved.queue_status = 'failed'
        saved.save(update_fields=['provider_id', 'queue_status', 'error_code', 'next_attempt_at'])


def dispatch_outbox(limit=100):
    Message.objects.filter(queue_status='sending', claimed_at__lt=timezone.now()-timedelta(minutes=5)).update(
        queue_status='unknown', error_code='stale_dispatch_claim')
    ids = list(Message.objects.filter(direction='outbound', queue_status__in=['queued', 'retry'],
        next_attempt_at__lte=timezone.now()).order_by('created_at').values_list('pk', flat=True)[:limit])
    for pk in ids:
        dispatch_message(pk)
    return len(ids)


def event_time(value):
    try:
        result = datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (ValueError, TypeError, OSError, OverflowError):
        raise ValueError('invalid_event_timestamp') from None
    if result > timezone.now() + timedelta(minutes=5):
        raise ValueError('future_event_timestamp')
    return min(result, timezone.now())


def inbound(channel, item, profile_name=''):
    wa_id, provider_id = item.get('from', ''), item.get('id', '')
    if not re.fullmatch(r'[1-9][0-9]{6,14}', wa_id) or not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 254:
        raise ValueError('invalid_inbound_identity')
    occurred = event_time(item.get('timestamp'))
    conversation, _ = Conversation.objects.get_or_create(channel=channel, wa_id=wa_id)
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    kind = item.get('type', 'unsupported')
    text = item.get('text', {}).get('body', '') if kind == 'text' else f'[{str(kind)[:25]} message: media preview unavailable]'
    if not isinstance(text, str):
        raise ValueError('invalid_message_text')
    message, fresh = Message.objects.get_or_create(provider_id=provider_id, defaults={'conversation': conversation, 'direction': 'inbound',
        'kind': str(kind)[:30], 'text': text[:4096], 'mode': 'live', 'queue_status': 'received', 'occurred_at': occurred})
    if message.conversation_id != conversation.pk or message.direction != 'inbound':
        raise ValueError('inbound_provider_id_conflict')
    latest = not conversation.last_inbound_at or occurred >= conversation.last_inbound_at
    if not conversation.last_inbound_at or occurred > conversation.last_inbound_at:
        conversation.last_inbound_at = occurred
    conversation.updated_at = max(conversation.updated_at, occurred)
    # Opt-out is deliberately conservative even when an older STOP arrives late.
    if kind == 'text' and text.strip().casefold() in ('stop', 'unsubscribe', 'cancel', 'end', 'quit'):
        conversation.consent, conversation.consent_evidence, conversation.consent_at = 'revoked', 'Inbound opt-out: ' + provider_id, timezone.now()
        ConsentEvent.objects.create(conversation=conversation, state='revoked', evidence=conversation.consent_evidence)
    conversation.save()
    from .intake import receive
    if fresh and latest:
        receive(conversation, profile_name, received_at=occurred)


def delivery_status(channel, item):
    status = item.get('status')
    if status not in ('sent', 'delivered', 'read', 'failed'):
        return
    event_time(item.get('timestamp'))
    provider_id = item.get('id')
    recipient = item.get('recipient_id')
    if not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 254:
        raise ValueError('invalid_status_id')
    rows = Message.objects.filter(direction='outbound', conversation__channel=channel, conversation__wa_id=recipient)
    # Callback data is correlation only, never authorization; channel+recipient are mandatory.
    message = rows.filter(provider_id=provider_id).first()
    callback = item.get('biz_opaque_callback_data')
    if not message and isinstance(callback, str):
        try:
            import uuid
            message = rows.filter(pk=uuid.UUID(callback), provider_id__isnull=True,
                queue_status__in=['sending', 'unknown']).first()
        except ValueError:
            pass
    if not message:
        raise LookupError('unmatched_delivery_status')
    message = Message.objects.select_for_update().get(pk=message.pk)
    ranks = {'': 0, 'sent': 1, 'failed': 2, 'delivered': 3, 'read': 4}
    if ranks[status] > ranks.get(message.delivery_status, 0):
        message.delivery_status = status
        errors = item.get('errors', [])
        code = errors[0].get('code') if isinstance(errors, list) and errors and isinstance(errors[0], dict) else None
        message.error_code = f'delivery_{code}' if status == 'failed' and isinstance(code, int) else 'delivery_failed' if status == 'failed' else ''
    message.provider_id, message.queue_status = provider_id, 'sent'
    message.save(update_fields=['provider_id', 'queue_status', 'delivery_status', 'error_code'])


@transaction.atomic
def process_delivery(pk):
    delivery = WebhookDelivery.objects.select_for_update().get(pk=pk)
    if delivery.status not in ('pending', 'retry') or delivery.next_attempt_at > timezone.now():
        return
    pending_error = None
    invalid = False
    for entry in delivery.payload['entry']:
        waba_id = str(entry.get('id', ''))
        for change in entry.get('changes', []):
            field, value = change.get('field'), change.get('value', {})
            if field == 'message_template_status_update':
                # Revoke immediately. Approval always requires a fresh authenticated template sync.
                key = fingerprint(['template', waba_id, entry.get('time'), value])
                _, fresh = WebhookEvent.objects.get_or_create(key=key, defaults={'delivery': delivery})
                if not fresh:
                    continue
                status = str(value.get('event', 'UNKNOWN'))
                Template.objects.filter(channel__waba_id=waba_id, provider_id=str(value.get('message_template_id'))).update(
                    status=status if status != 'APPROVED' else 'SYNC_REQUIRED')
                continue
            if field != 'messages':
                continue
            phone = value.get('metadata', {}).get('phone_number_id')
            channel = Channel.objects.select_for_update().filter(phone_number_id=phone, waba_id=waba_id).first()
            if not channel:
                pending_error = 'unknown_webhook_channel'
                continue
            for kind, items in [('message', value.get('messages', [])), ('status', value.get('statuses', []))]:
                if not isinstance(items, list):
                    raise ValueError('invalid_webhook_items')
                for item in items:
                    try:
                        # Savepoints let valid items survive another item's malformed data
                        # or a delivery status that precedes its outbound response.
                        with transaction.atomic():
                            key = fingerprint([channel.phone_number_id, kind, item.get('id') if kind == 'message' else item])
                            _, fresh = WebhookEvent.objects.get_or_create(key=key, defaults={'delivery': delivery})
                            if fresh:
                                if kind == 'message':
                                    names = {c.get('wa_id'): c.get('profile', {}).get('name', '') for c in value.get('contacts', []) if isinstance(c, dict) and isinstance(c.get('profile', {}), dict)}
                                    profile_name = names.get(item.get('from'), '')
                                    inbound(channel, item, profile_name if isinstance(profile_name, str) else '')
                                else:
                                    delivery_status(channel, item)
                    except (ValueError, TypeError, KeyError, AttributeError):
                        invalid = True
                    except LookupError:
                        pending_error = 'unmatched_delivery_status'
    delivery.attempts += 1
    delivery.status = 'failed' if invalid or (pending_error and delivery.attempts >= MAX_ATTEMPTS) else 'retry' if pending_error else 'done'
    delivery.error_code = 'invalid_payload' if invalid else pending_error or ''
    delivery.next_attempt_at = timezone.now() + timedelta(seconds=min(3600, 30 * 2 ** (delivery.attempts - 1)))
    delivery.save(update_fields=['status', 'attempts', 'error_code', 'next_attempt_at'])


def process_webhooks(limit=100):
    ids = list(WebhookDelivery.objects.filter(status__in=['pending', 'retry'], next_attempt_at__lte=timezone.now()).values_list('pk', flat=True)[:limit])
    for pk in ids:
        try:
            process_delivery(pk)
        except Exception as error:
            with transaction.atomic():
                delivery = WebhookDelivery.objects.select_for_update().get(pk=pk)
                if delivery.status == 'done':
                    continue
                delivery.attempts += 1
                delivery.status = 'failed' if isinstance(error, (ValueError, TypeError, KeyError, AttributeError)) or delivery.attempts >= MAX_ATTEMPTS else 'retry'
                delivery.error_code = 'invalid_payload' if delivery.status == 'failed' else 'processing_retry'
                delivery.next_attempt_at = timezone.now() + timedelta(seconds=min(3600, 30 * 2 ** (delivery.attempts - 1)))
                delivery.save(update_fields=['attempts', 'status', 'error_code', 'next_attempt_at'])
    return len(ids)


def sync_templates(channel):
    if not channel.is_active or not channel.branch.is_active:
        raise ProviderError('inactive_template_account')
    rows = fetch_templates(channel)  # Fetch and validate every page before changing approvals.
    prepared = []
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) and row[key]
                for key in ('id', 'name', 'language', 'status')):
            raise ProviderError('invalid_template_record')
        category = row.get('category', '')
        components = row.get('components', [])
        if not isinstance(category, str) or len(category) > 40 or not isinstance(components, list) or any(not isinstance(c, dict) for c in components):
            raise ProviderError('invalid_template_record')
        if any(len(row[key]) > maximum for key, maximum in [('id', 100), ('name', 512), ('language', 20), ('status', 40)]):
            raise ProviderError('invalid_template_record')
        body = next((c.get('text', '') for c in components if c.get('type') == 'BODY'), '')
        if not isinstance(body, str):
            raise ProviderError('invalid_template_record')
        slots = re.findall(r'\{\{(\d+)\}\}', body)
        indexes = sorted(set(int(i) for i in slots))
        supported = bool(body) and all(c.get('type') in ('BODY', 'FOOTER') for c in components)
        supported = supported and indexes == list(range(1, len(indexes)+1)) and '{{' not in re.sub(r'\{\{\d+\}\}', '', body)
        prepared.append((row, category.strip().upper(), body, len(indexes), supported))
    with transaction.atomic():
        channel = Channel.objects.select_for_update().select_related('branch').get(pk=channel.pk)
        if not channel.is_active or not channel.branch.is_active:
            raise ProviderError('inactive_template_account')
        Template.objects.filter(channel=channel).exclude(source_mode='mock').update(status='MISSING')
        for row, category, body, count, supported in prepared:
            Template.objects.update_or_create(channel=channel, name=row['name'], language=row['language'], defaults={
                'provider_id': row['id'], 'status': row['status'], 'category': category, 'body': body, 'parameter_count': count,
                'supported': supported, 'synced_at': timezone.now(), 'source_mode': 'live'})
    return len(prepared)
