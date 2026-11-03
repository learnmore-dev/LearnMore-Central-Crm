from unittest.mock import patch
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from .models import Channel, Template, Message
from .provider import ProviderError, fetch_templates
from .services import sync_templates


@override_settings(WHATSAPP_MODE='mock', WHATSAPP_LIVE_SENDS_ENABLED=False)
class TemplateCatalogueTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, _ = crm_fixtures()
        self.channel = Channel.objects.create(name='Central', branch=self.a, phone_number_id='12345', waba_id='67890')
        self.hidden = Channel.objects.create(name='Other', branch=self.b, phone_number_id='23456', waba_id='78901')
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        for name, category, status, mode in [('reminder','UTILITY','APPROVED','live'), ('course_offer','MARKETING','PENDING','live'), ('otp','AUTHENTICATION','REJECTED','live'), ('mock_welcome','','APPROVED','mock')]:
            Template.objects.create(channel=self.channel, provider_id=name, name=name, language='en_US', category=category,
                status=status, body='Hello {{1}}', parameter_count=1, supported=True, source_mode=mode, synced_at=timezone.now())
        Template.objects.create(channel=self.hidden, provider_id='hidden', name='hidden', language='en_US', category='UTILITY', status='APPROVED', source_mode='live', synced_at=timezone.now())

    def test_category_and_status_filters_are_combined_and_branch_scoped(self):
        response = self.client.get('/api/v1/whatsapp/templates/?category=UTILITY,MARKETING&status=APPROVED,PENDING')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual({item['name'] for item in response.data['results']}, {'reminder','course_offer'})
        response = self.client.get('/api/v1/whatsapp/templates/?category=AUTHENTICATION&status=APPROVED')
        self.assertEqual(response.data['count'], 0)
        response = self.client.get('/api/v1/whatsapp/templates/?category=OTHER')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['source_mode'], 'mock')
        self.assertEqual(self.client.get('/api/v1/whatsapp/templates/?category=made-up').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/whatsapp/templates/?status=made-up').status_code, 400)

    def test_sync_requires_global_administrator_and_an_active_channel(self):
        url = '/api/v1/whatsapp/templates/sync/'
        with patch('messaging.services.fetch_templates') as fetch:
            self.assertEqual(self.client.post(url, {'channel':str(self.channel.pk)}, format='json').status_code, 403)
            fetch.assert_not_called()
        self.client.force_authenticate(self.management)
        self.channel.is_active=False; self.channel.save()
        self.assertEqual(self.client.post(url, {'channel':str(self.channel.pk)}, format='json').status_code, 404)

    def test_sync_reads_meta_categories_without_enabling_sending_or_reclassifying_mock_data(self):
        self.client.force_authenticate(self.management)
        rows=[{'id':'real-1','name':'reminder','language':'en_US','status':'APPROVED','category':'UTILITY','components':[{'type':'BODY','text':'Hello {{1}}'}]},
              {'id':'real-2','name':'course_offer','language':'en_US','status':'REJECTED','category':'MARKETING','components':[{'type':'BODY','text':'Course information'}]}]
        with patch('messaging.services.fetch_templates', return_value=rows), patch('messaging.services.dispatch_outbox') as send:
            response=self.client.post('/api/v1/whatsapp/templates/sync/', {'channel':str(self.channel.pk)}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 2)
        send.assert_not_called()
        self.assertFalse(Message.objects.exists())
        self.assertEqual(Template.objects.get(channel=self.channel,name='reminder').category, 'UTILITY')
        self.assertEqual(Template.objects.get(channel=self.channel,name='course_offer').status, 'REJECTED')
        self.assertEqual(Template.objects.get(channel=self.channel,name='otp').status, 'MISSING')
        mock=Template.objects.get(channel=self.channel,name='mock_welcome')
        self.assertEqual(mock.source_mode,'mock');self.assertEqual(mock.category,'');self.assertEqual(mock.status,'APPROVED')

    def test_provider_fetch_is_get_only_and_requests_categories_even_in_mock_mode(self):
        with patch('messaging.provider.graph_request', return_value={'data':[]}) as request:
            self.assertEqual(fetch_templates(self.channel), [])
        self.assertEqual(request.call_args.args[0], '67890/message_templates')
        self.assertIn('category',request.call_args.kwargs['params']['fields'])
        self.assertNotIn('payload', request.call_args.kwargs)

    def test_failed_or_malformed_sync_preserves_previous_approvals(self):
        self.client.force_authenticate(self.management)
        with patch('messaging.services.fetch_templates', side_effect=ProviderError('graph_190')):
            response=self.client.post('/api/v1/whatsapp/templates/sync/', {'channel':str(self.channel.pk)}, format='json')
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.data['code'],'graph_190')
        self.assertEqual(Template.objects.get(channel=self.channel,name='reminder').status,'APPROVED')
        with patch('messaging.services.fetch_templates',return_value=[{'id':'bad','name':'bad','language':'en_US','status':'APPROVED','category':{},'components':[]} ]):
            with self.assertRaises(ProviderError): sync_templates(self.channel)
        self.assertEqual(Template.objects.get(channel=self.channel,name='reminder').status,'APPROVED')

    def test_future_categories_and_statuses_are_preserved_and_available_under_other(self):
        with patch('messaging.services.fetch_templates',return_value=[{'id':'future','name':'future','language':'en_US','status':'FUTURE_STATUS','category':'FUTURE_CATEGORY','components':[]} ]):
            sync_templates(self.channel)
        response=self.client.get('/api/v1/whatsapp/templates/?category=OTHER&status=OTHER')
        self.assertEqual(response.data['count'],1)
        self.assertEqual(response.data['results'][0]['category'],'FUTURE_CATEGORY')
