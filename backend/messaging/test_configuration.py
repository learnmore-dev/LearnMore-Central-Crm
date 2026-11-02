import hashlib
import hmac
import json
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from .configuration import credentials, CredentialError
from .models import Channel, WhatsAppConnection, Message, WebhookDelivery
from .provider import ProviderError, graph_request


@override_settings(WHATSAPP_MODE='mock', WHATSAPP_LIVE_SENDS_ENABLED=False, WHATSAPP_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                   WHATSAPP_ACCESS_TOKEN='', WHATSAPP_APP_SECRET='', WHATSAPP_VERIFY_TOKEN='', WHATSAPP_GRAPH_VERSION='')
class ConnectionSetupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, _ = crm_fixtures()
        self.channel = Channel.objects.create(branch=self.a, name='LearnMore', phone_number_id='12345', waba_id='67890')
        self.client = APIClient()
        self.client.force_authenticate(self.management)
        self.data = {'graph_version': 'v25.0', 'access_token': 'private-access-token', 'app_secret': 'private-app-secret',
                     'verify_token': 'private-verify-token', 'webhook_url': 'https://crm.example.com/api/v1/whatsapp/webhook/'}

    def save(self, **changes):
        return self.client.patch('/api/v1/whatsapp/settings/', {**self.data, **changes}, format='json')

    def test_credentials_are_encrypted_write_only_and_never_enable_sending(self):
        result = self.save()
        self.assertEqual(result.status_code, 200, result.data)
        row = WhatsAppConnection.objects.get()
        self.assertNotIn('private-', row.access_token_encrypted)
        self.assertEqual(credentials()['access_token'], self.data['access_token'])
        self.assertEqual(row.updated_by, self.management)
        for response in (result, self.client.get('/api/v1/whatsapp/settings/')):
            self.assertNotIn('private-', str(response.data))
            self.assertEqual(response.data['mode'], 'mock')
            self.assertFalse(response.data['live_sends_enabled'])
        self.assertEqual(Message.objects.count(), 0)

    def test_blank_secrets_preserve_values_and_changes_reset_webhook_verification(self):
        self.save()
        challenge = self.client.get('/api/v1/whatsapp/webhook/', {'hub.mode': 'subscribe', 'hub.verify_token': self.data['verify_token'], 'hub.challenge': 'test-challenge'})
        self.assertEqual(challenge.content, b'test-challenge')
        self.assertIsNotNone(WhatsAppConnection.objects.get().webhook_verified_at)
        result = self.save(access_token='', app_secret='', verify_token='')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(credentials()['verify_token'], self.data['verify_token'])
        self.assertIsNotNone(WhatsAppConnection.objects.get().webhook_verified_at)
        self.save(verify_token='replacement-token')
        self.assertIsNone(WhatsAppConnection.objects.get().webhook_verified_at)

    def test_only_global_admins_can_save_or_check_and_no_gate_fields_accepted(self):
        for user in (self.owner, self.manager):
            self.client.force_authenticate(user)
            self.assertEqual(self.save().status_code, 403)
            self.assertEqual(self.client.post('/api/v1/whatsapp/settings/check/', {'channel': str(self.channel.pk)}, format='json').status_code, 403)
        self.client.force_authenticate(self.management)
        self.assertEqual(self.save(live_sends_enabled=True).status_code, 400)
        self.assertEqual(self.save(mode='live').status_code, 400)
        self.assertEqual(self.save(graph_version='https://example.com').status_code, 400)
        self.assertEqual(self.save(webhook_url='http://localhost/api/v1/whatsapp/webhook/').status_code, 400)
        self.assertFalse(WhatsAppConnection.objects.exists())

    def test_storage_key_is_required_and_wrong_key_fails_closed(self):
        with override_settings(WHATSAPP_ENCRYPTION_KEY=''):
            self.assertEqual(self.save().status_code, 400)
        self.save()
        with override_settings(WHATSAPP_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            with self.assertRaises(CredentialError):
                credentials()
            self.assertEqual(self.client.get('/api/v1/whatsapp/webhook/').status_code, 503)

    def test_saved_secrets_are_used_for_signed_webhooks(self):
        self.save()
        payload = json.dumps({'object': 'whatsapp_business_account', 'entry': []}).encode()
        signature = 'sha256=' + hmac.new(self.data['app_secret'].encode(), payload, hashlib.sha256).hexdigest()
        response = self.client.post('/api/v1/whatsapp/webhook/', payload, content_type='application/json', HTTP_X_HUB_SIGNATURE_256=signature)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WebhookDelivery.objects.count(), 1)

    def test_connection_check_is_read_only_and_checks_membership(self):
        self.save()
        with patch('messaging.provider.graph_request', return_value={'data': [{'id': '12345', 'verified_name': 'LearnMore', 'display_phone_number': '+919876543210'}]}) as request:
            result = self.client.post('/api/v1/whatsapp/settings/check/', {'channel': str(self.channel.pk)}, format='json')
        self.assertTrue(result.data['connected'])
        self.assertEqual(result.data['verified_name'], 'LearnMore')
        self.assertEqual(request.call_args.args[0], '67890/phone_numbers')
        self.assertNotIn('payload', request.call_args.kwargs)
        self.assertEqual(Message.objects.count(), 0)
        with patch('messaging.provider.graph_request', return_value={'data': [{'id': '99999'}]}):
            result = self.client.post('/api/v1/whatsapp/settings/check/', {'channel': str(self.channel.pk)}, format='json')
        self.assertFalse(result.data['connected'])
        self.assertEqual(result.data['code'], 'phone_number_not_in_account')

    def test_check_paginates_without_following_provider_urls(self):
        self.save()
        with patch('messaging.provider.graph_request', side_effect=[
            {'data': [], 'paging': {'next': 'https://untrusted.example/', 'cursors': {'after': 'cursor'}}},
            {'data': [{'id': '12345'}]},
        ]) as request:
            result = self.client.post('/api/v1/whatsapp/settings/check/', {'channel': str(self.channel.pk)}, format='json')
        self.assertTrue(result.data['connected'])
        self.assertEqual(request.call_args.args[0], '67890/phone_numbers')
        self.assertEqual(request.call_args.kwargs['params']['after'], 'cursor')

    def test_error_redaction_and_inactive_account_rejection(self):
        with patch('messaging.provider.check_connection', side_effect=ProviderError('graph_190')):
            result = self.client.post('/api/v1/whatsapp/settings/check/', {'channel': str(self.channel.pk)}, format='json')
        self.assertFalse(result.data['connected'])
        self.assertNotIn('private-', str(result.data))
        self.channel.is_active = False
        self.channel.save()
        self.assertEqual(self.client.post('/api/v1/whatsapp/settings/check/', {'channel': str(self.channel.pk)}, format='json').status_code, 404)

    def test_graph_transport_uses_saved_token_with_fixed_https_host(self):
        self.save()
        with patch('messaging.provider.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"data":[]}'
            graph_request('67890/phone_numbers')
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://graph.facebook.com/v25.0/67890/phone_numbers')
        self.assertEqual(request.get_header('Authorization'), 'Bearer private-access-token')
        self.assertEqual(request.method, 'GET')
