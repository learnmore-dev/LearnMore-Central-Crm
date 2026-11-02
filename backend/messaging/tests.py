import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from .models import Channel, Conversation, Message, Template, WebhookDelivery, WebhookEvent
from . import services
from .provider import ProviderError


@override_settings(WHATSAPP_MODE='mock', WHATSAPP_LIVE_SENDS_ENABLED=False,
                   WHATSAPP_APP_SECRET='synthetic-app-secret', WHATSAPP_VERIFY_TOKEN='synthetic-verify-token')
class MessagingTests(TestCase):
    def setUp(self):
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.channel = Channel.objects.create(branch=self.a, name='Central inbox', phone_number_id='12345', waba_id='67890')
        self.conversation = Conversation.objects.create(channel=self.channel, wa_id='919876543210', contact=self.contact,
            last_inbound_at=timezone.now(), consent='granted', consent_evidence='Synthetic test consent')
        self.template = Template.objects.create(channel=self.channel, provider_id='tpl1', name='welcome', language='en_US',
            status='APPROVED', body='Hello {{1}}', parameter_count=1, supported=True, synced_at=timezone.now(), source_mode='mock')
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def payload(self, messages=None, statuses=None):
        return {'object': 'whatsapp_business_account', 'entry': [{'id': '67890', 'changes': [{'field': 'messages', 'value': {
            'metadata': {'phone_number_id': '12345'}, 'messages': messages or [], 'statuses': statuses or []}}]}]}

    def post_hook(self, payload, signature=True):
        raw = json.dumps(payload).encode()
        digest = 'sha256=' + hmac.new(b'synthetic-app-secret', raw, hashlib.sha256).hexdigest()
        return self.client.post('/api/v1/whatsapp/webhook/', raw, content_type='application/json',
                                HTTP_X_HUB_SIGNATURE_256=digest if signature else 'sha256=invalid')

    def queue(self, **kwargs):
        return services.enqueue(actor=self.owner, conversation=self.conversation, client_key=kwargs.pop('client_key', 'key-1'), **kwargs)

    def test_webhook_handshake_and_signature_before_persistence(self):
        self.assertEqual(self.client.get('/api/v1/whatsapp/webhook/', {'hub.mode': 'subscribe', 'hub.verify_token': 'wrong', 'hub.challenge': 'abc'}).status_code, 403)
        response = self.client.get('/api/v1/whatsapp/webhook/', {'hub.mode': 'subscribe', 'hub.verify_token': 'synthetic-verify-token', 'hub.challenge': 'abc'})
        self.assertEqual(response.content, b'abc')
        self.assertEqual(self.post_hook(self.payload(), False).status_code, 403)
        self.assertEqual(WebhookDelivery.objects.count(), 0)

    def test_durable_inbound_dedup_across_distinct_envelopes(self):
        timestamp = int(timezone.now().timestamp())
        incoming = {'id': 'wamid.in', 'from': self.conversation.wa_id, 'type': 'text', 'timestamp': str(timestamp), 'text': {'body': 'Hello'}}
        payload = self.payload(messages=[incoming])
        self.assertEqual(self.post_hook(payload).status_code, 200)
        self.assertEqual(self.post_hook(payload).status_code, 200)
        self.assertEqual(WebhookDelivery.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 0)
        services.process_webhooks()
        payload['entry'][0]['changes'][0]['value']['contacts'] = [{'wa_id': incoming['from']}]
        self.post_hook(payload)
        services.process_webhooks()
        self.assertEqual(Message.objects.filter(direction='inbound').count(), 1)
        self.assertEqual(WebhookEvent.objects.count(), 1)
        self.conversation.refresh_from_db()
        self.assertEqual(int(self.conversation.last_inbound_at.timestamp()), timestamp)

    def test_window_checked_at_enqueue_and_dispatch(self):
        self.conversation.last_inbound_at = timezone.now() - timedelta(hours=24)
        self.conversation.save()
        with self.assertRaisesMessage(Exception, '24-hour'):
            self.queue(text='Hi')
        self.conversation.last_inbound_at = timezone.now()
        self.conversation.save()
        message = self.queue(text='Hi')
        Conversation.objects.filter(pk=self.conversation.pk).update(last_inbound_at=timezone.now()-timedelta(hours=25))
        services.dispatch_message(message.pk)
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'blocked')

    def test_mock_queue_idempotency_and_payload_conflict(self):
        message = self.queue(text='Hello')
        self.assertEqual(self.queue(text='Hello').pk, message.pk)
        with self.assertRaisesMessage(Exception, 'different'):
            self.queue(text='Changed')
        with patch('messaging.provider.build_opener') as network:
            services.dispatch_message(message.pk)
            services.dispatch_message(message.pk)
            network.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'sent')
        self.assertTrue(message.provider_id.startswith('mock.'))
        self.assertEqual(message.attempts, 1)

    def test_template_consent_approval_and_parameters(self):
        Conversation.objects.filter(pk=self.conversation.pk).update(last_inbound_at=None, consent='unknown')
        self.conversation.refresh_from_db()
        with self.assertRaisesMessage(Exception, 'consent'):
            self.queue(template=self.template, parameters=['Student'])
        self.conversation.consent = 'granted'
        self.conversation.save()
        with self.assertRaisesMessage(Exception, 'parameters'):
            self.queue(template=self.template, parameters=[])
        message = self.queue(template=self.template, parameters=['Student'])
        Template.objects.filter(pk=self.template.pk).update(status='PAUSED')
        services.dispatch_message(message.pk)
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'blocked')

    def test_stop_blocks_queued_message(self):
        message = self.queue(text='Hello')
        self.post_hook(self.payload(messages=[{'id': 'stop-id', 'from': self.conversation.wa_id, 'type': 'text',
            'timestamp': str(int(timezone.now().timestamp())), 'text': {'body': 'STOP'}}]))
        services.process_webhooks()
        services.dispatch_message(message.pk)
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'blocked')

    @override_settings(WHATSAPP_MODE='live', WHATSAPP_LIVE_SENDS_ENABLED=False)
    def test_live_gate_and_mock_messages_never_become_live(self):
        with self.assertRaisesMessage(Exception, 'disabled'):
            self.queue(text='Hello')
        with override_settings(WHATSAPP_MODE='mock'):
            message = self.queue(text='Mock')
        with patch('messaging.provider.build_opener') as network:
            services.dispatch_message(message.pk)
            network.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'blocked')

    def test_retry_backoff_and_ambiguous_timeout(self):
        message = self.queue(text='Hello')
        with patch('messaging.services.send_message', side_effect=ProviderError('rate_limited', retryable=True)):
            services.dispatch_message(message.pk)
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'retry')
        self.assertGreater(message.next_attempt_at, timezone.now())
        Message.objects.filter(pk=message.pk).update(next_attempt_at=timezone.now())
        with patch('messaging.services.send_message', side_effect=ProviderError('uncertain', ambiguous=True)):
            services.dispatch_message(message.pk)
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'unknown')
        with patch('messaging.services.send_message') as send:
            services.dispatch_message(message.pk)
            send.assert_not_called()

    def test_status_order_dedup_and_unknown_reconciliation(self):
        message = self.queue(text='Hello')
        Message.objects.filter(pk=message.pk).update(queue_status='unknown')
        statuses = [{'id': 'wamid.out', 'recipient_id': self.conversation.wa_id, 'status': status,
            'timestamp': str(int(timezone.now().timestamp())), 'biz_opaque_callback_data': str(message.pk)} for status in ['read', 'sent', 'delivered', 'read']]
        self.post_hook(self.payload(statuses=statuses))
        services.process_webhooks()
        message.refresh_from_db()
        self.assertEqual(message.delivery_status, 'read')
        self.assertEqual(message.queue_status, 'sent')
        self.assertEqual(message.provider_id, 'wamid.out')

    def test_api_scope_and_protected_fields(self):
        url = '/api/v1/whatsapp/conversations/'
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).data['count'], 0)
        self.assertEqual(self.client.get(url + str(self.conversation.pk) + '/').status_code, 404)
        self.client.force_authenticate(self.owner)
        response = self.client.post('/api/v1/whatsapp/messages/', {'conversation': str(self.conversation.pk), 'text': 'Hi', 'client_key': 'api-1', 'queue_status': 'sent'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.client.force_authenticate(self.other)
        response = self.client.post('/api/v1/whatsapp/messages/', {'conversation': str(self.conversation.pk), 'text': 'Hi', 'client_key': 'api-1'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_template_revocation_webhook_requires_authenticated_resync(self):
        payload = {'object': 'whatsapp_business_account', 'entry': [{'id': self.channel.waba_id, 'changes': [{
            'field': 'message_template_status_update', 'value': {'event': 'PAUSED', 'message_template_id': self.template.provider_id}}]}]}
        self.post_hook(payload)
        services.process_webhooks()
        self.template.refresh_from_db()
        self.assertEqual(self.template.status, 'PAUSED')
        payload['entry'][0]['changes'][0]['value']['event'] = 'APPROVED'
        self.post_hook(payload)
        services.process_webhooks()
        self.template.refresh_from_db()
        self.assertEqual(self.template.status, 'SYNC_REQUIRED')

    def test_stale_claim_and_maximum_retry_attempts(self):
        message = self.queue(text='Hello')
        Message.objects.filter(pk=message.pk).update(queue_status='sending', claimed_at=timezone.now()-timedelta(minutes=6))
        with patch('messaging.services.send_message') as send:
            services.dispatch_outbox()
            send.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'unknown')
        Message.objects.filter(pk=message.pk).update(queue_status='retry', attempts=4, next_attempt_at=timezone.now())
        with patch('messaging.services.send_message', side_effect=ProviderError('limited', retryable=True)):
            services.dispatch_message(message.pk)
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'failed')
        self.assertEqual(message.attempts, 5)

    def test_old_inbound_does_not_reopen_window_and_poison_receipts_are_retained(self):
        old = timezone.now()-timedelta(hours=26)
        Conversation.objects.filter(pk=self.conversation.pk).update(last_inbound_at=old)
        self.post_hook(self.payload(messages=[{'id': 'old', 'from': self.conversation.wa_id, 'type': 'text',
            'timestamp': str(int(old.timestamp())), 'text': {'body': 'Delayed webhook'}}]))
        services.process_webhooks()
        self.conversation.refresh_from_db()
        self.assertFalse(services.window_open(self.conversation))
        self.post_hook(self.payload(messages=[{'id': 'broken', 'from': self.conversation.wa_id, 'timestamp': 'invalid'}]))
        services.process_webhooks()
        self.assertTrue(WebhookDelivery.objects.filter(status='failed', error_code='invalid_payload').exists())
        self.assertFalse(Message.objects.filter(provider_id='broken').exists())

    def test_consent_and_contact_link_permissions_and_audit(self):
        from django.contrib.auth import get_user_model
        from .models import ConsentEvent
        support = get_user_model().objects.create_user(username='messaging_support', role='support', branch=self.a)
        self.client.force_authenticate(support)
        response = self.client.post(f'/api/v1/whatsapp/conversations/{self.conversation.pk}/consent/',
            {'state': 'granted', 'evidence': 'Customer signed consent form'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ConsentEvent.objects.get().actor, support)
        response = self.client.post(f'/api/v1/whatsapp/conversations/{self.conversation.pk}/link/', {'contact': str(self.contact.pk)}, format='json')
        self.assertEqual(response.status_code, 403)
        accounts = get_user_model().objects.create_user(username='messaging_accounts', role='accounts', branch=self.a)
        self.client.force_authenticate(accounts)
        self.assertEqual(self.client.get('/api/v1/whatsapp/conversations/').status_code, 403)
        self.client.force_authenticate(self.manager)
        response = self.client.post(f'/api/v1/whatsapp/conversations/{self.conversation.pk}/link/', {'contact': str(self.contact.pk)}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_status_cannot_reconcile_a_different_recipient(self):
        message = self.queue(text='Hello')
        Message.objects.filter(pk=message.pk).update(queue_status='unknown')
        self.post_hook(self.payload(statuses=[{'id': 'wamid.wrong', 'recipient_id': '919876543211', 'status': 'read',
            'timestamp': str(int(timezone.now().timestamp())), 'biz_opaque_callback_data': str(message.pk)}]))
        services.process_webhooks()
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'unknown')
        self.assertIsNone(message.provider_id)
        self.assertTrue(WebhookDelivery.objects.filter(status='retry').exists())

    def test_mixed_webhook_preserves_valid_items_and_replay_is_idempotent(self):
        payload = self.payload(messages=[
            {'id': 'valid', 'from': self.conversation.wa_id, 'type': 'text', 'timestamp': str(int(timezone.now().timestamp())), 'text': {'body': 'Valid'}},
            {'id': 'bad', 'from': self.conversation.wa_id, 'type': 'text', 'timestamp': 'invalid', 'text': {'body': 'Invalid'}},
        ])
        self.post_hook(payload)
        services.process_webhooks()
        self.assertEqual(Message.objects.filter(provider_id='valid').count(), 1)
        self.assertFalse(Message.objects.filter(provider_id='bad').exists())
        delivery = WebhookDelivery.objects.get()
        self.assertEqual(delivery.status, 'failed')
        delivery.status, delivery.next_attempt_at = 'retry', timezone.now()
        delivery.save()
        services.process_webhooks()
        self.assertEqual(Message.objects.filter(provider_id='valid').count(), 1)

    def test_channel_management_and_session_csrf_boundary(self):
        data = {'branch': str(self.a.pk), 'name': 'New inbox', 'phone_number_id': '7777', 'waba_id': '67890'}
        self.assertEqual(self.client.post('/api/v1/whatsapp/channels/', data, format='json').status_code, 403)
        self.client.force_authenticate(self.management)
        self.assertEqual(self.client.post('/api/v1/whatsapp/channels/', data, format='json').status_code, 201)
        self.assertEqual(self.client.post('/api/v1/whatsapp/channels/', data, format='json').status_code, 400)
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        response = csrf_client.post('/api/v1/whatsapp/messages/', {'conversation': str(self.conversation.pk), 'text': 'Hi', 'client_key': 'csrf'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Message.objects.exists())

    def test_stale_template_and_inactive_sender_are_blocked(self):
        Template.objects.filter(pk=self.template.pk).update(synced_at=timezone.now()-timedelta(hours=25))
        with self.assertRaisesMessage(Exception, 'refreshed'):
            self.queue(template=self.template, parameters=['Student'])
        message = self.queue(text='Hello')
        self.owner.is_active = False
        self.owner.save()
        with patch('messaging.services.send_message') as send:
            services.dispatch_message(message.pk)
            send.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'blocked')
