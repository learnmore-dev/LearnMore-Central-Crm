import io
import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from django.test import TestCase, override_settings
from django.utils import timezone
from common.test_utils import crm_fixtures
from .models import Channel, Conversation, Message, Template
from .provider import ProviderError, graph_request, send_message, fetch_templates, NoRedirect
from .services import sync_templates


@override_settings(WHATSAPP_MODE='live', WHATSAPP_LIVE_SENDS_ENABLED=True,
                   WHATSAPP_ACCESS_TOKEN='synthetic-token', WHATSAPP_GRAPH_VERSION='v25.0')
class ProviderTests(TestCase):
    """All network boundaries mocked, including tests of enabled live mode."""
    def setUp(self):
        a, _, owner, _, _, _, _ = crm_fixtures()
        self.channel = Channel.objects.create(branch=a, name='Inbox', phone_number_id='12345', waba_id='67890')
        self.conversation = Conversation.objects.create(channel=self.channel, wa_id='919876543210')
        self.message = Message.objects.create(conversation=self.conversation, direction='outbound', text='Hello', mode='live', created_by=owner)

    def test_actual_http_contract_and_no_secret_in_payload(self):
        with patch('messaging.provider.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"messages":[{"id":"wamid.mocked"}]}'
            self.assertEqual(send_message(self.message), 'wamid.mocked')
        args, kwargs = opener.return_value.open.call_args
        request = args[0]
        self.assertEqual(request.full_url, 'https://graph.facebook.com/v25.0/12345/messages')
        self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-token')
        payload = json.loads(request.data)
        self.assertEqual(payload['to'], self.conversation.wa_id)
        self.assertEqual(payload['text'], {'body': 'Hello', 'preview_url': False})
        self.assertEqual(payload['biz_opaque_callback_data'], str(self.message.pk))
        self.assertNotIn('synthetic-token', request.data.decode())
        self.assertEqual(kwargs['timeout'], 15)
        self.assertIsNone(NoRedirect().redirect_request(request, None, 302, '', {}, 'https://example.com'))

    def test_template_payload(self):
        template = Template.objects.create(channel=self.channel, provider_id='1', name='welcome', language='en_US',
            status='APPROVED', body='Hi {{1}}', supported=True, source_mode='live', synced_at=timezone.now(), parameter_count=1)
        self.message.template, self.message.kind, self.message.parameters = template, 'template', ['Student']
        with patch('messaging.provider.graph_request', return_value={'messages': [{'id': 'mocked-id'}]}) as request:
            send_message(self.message)
        self.assertEqual(request.call_args.kwargs['payload']['template'], {'name': 'welcome', 'language': {'code': 'en_US'},
            'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': 'Student'}]}]})

    def test_error_classification_and_redaction(self):
        for status, retry, ambiguous in [(429, True, False), (401, False, False), (500, False, True)]:
            failure = HTTPError('https://graph.facebook.com', status, 'secret provider diagnostic',
                {'Retry-After': '60'}, io.BytesIO(b'{"error":{"code":123,"message":"synthetic-token"}}'))
            with patch('messaging.provider.build_opener') as opener:
                opener.return_value.open.side_effect = failure
                with self.assertRaises(ProviderError) as caught:
                    graph_request('12345/messages', payload={})
            self.assertEqual(caught.exception.retryable, retry)
            self.assertEqual(caught.exception.ambiguous, ambiguous)
            self.assertNotIn('synthetic-token', str(caught.exception))
            self.assertEqual(caught.exception.retry_after, 60)
        with patch('messaging.provider.build_opener') as opener:
            opener.return_value.open.side_effect = URLError('sensitive diagnostic')
            with self.assertRaises(ProviderError) as caught:
                send_message(self.message)
        self.assertTrue(caught.exception.ambiguous)

    def test_invalid_success_is_ambiguous(self):
        with patch('messaging.provider.graph_request', return_value={}):
            with self.assertRaises(ProviderError) as caught:
                send_message(self.message)
        self.assertTrue(caught.exception.ambiguous)

    def test_template_paging_uses_cursor_and_never_remote_next_url(self):
        with patch('messaging.provider.graph_request', side_effect=[
            {'data': [{'id': 'one'}], 'paging': {'next': 'https://attacker.example/token', 'cursors': {'after': 'cursor'}}},
            {'data': [{'id': 'two'}]},
        ]) as request:
            self.assertEqual(len(fetch_templates(self.channel)), 2)
        self.assertEqual(request.call_args.args, ('67890/message_templates',))
        self.assertEqual(request.call_args.kwargs['params']['after'], 'cursor')

    def test_sync_limits_templates_to_supported_components_and_revokes_missing(self):
        old = Template.objects.create(channel=self.channel, provider_id='old', name='old', language='en_US', status='APPROVED', synced_at=timezone.now())
        rows = [
            {'id': '1', 'name': 'welcome', 'language': 'en_US', 'status': 'APPROVED', 'components': [{'type': 'BODY', 'text': 'Hello {{1}}'}]},
            {'id': '2', 'name': 'media', 'language': 'en_US', 'status': 'APPROVED', 'components': [{'type': 'HEADER', 'format': 'IMAGE'}, {'type': 'BODY', 'text': 'Hi'}]},
            {'id': '3', 'name': 'named', 'language': 'en_US', 'status': 'APPROVED', 'components': [{'type': 'BODY', 'text': 'Hi {{name}}'}]},
        ]
        with patch('messaging.services.fetch_templates', return_value=rows):
            self.assertEqual(sync_templates(self.channel), 3)
        self.assertTrue(Template.objects.get(name='welcome').supported)
        self.assertFalse(Template.objects.get(name='media').supported)
        self.assertFalse(Template.objects.get(name='named').supported)
        old.refresh_from_db()
        self.assertEqual(old.status, 'MISSING')
