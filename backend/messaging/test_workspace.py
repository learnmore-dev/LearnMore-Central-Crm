from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from .models import Channel, Conversation, Template, Message, Campaign, CannedMessage, AdDraft


@override_settings(WHATSAPP_MODE='mock', WHATSAPP_LIVE_SENDS_ENABLED=False)
class WhatsAppWorkspaceTests(TestCase):
    def setUp(self):
        self.a, self.b, self.owner, self.manager, self.other, self.management, _ = crm_fixtures()
        self.channel = Channel.objects.create(name='Central', branch=self.a, phone_number_id='12345', waba_id='67890')
        self.other_channel = Channel.objects.create(name='Private', branch=self.b, phone_number_id='23456', waba_id='78901')
        self.template = Template.objects.create(channel=self.channel, name='welcome', provider_id='t1', language='en_US',
            status='APPROVED', body='Hello {{1}}', parameter_count=1, supported=True, source_mode='mock', synced_at=timezone.now())
        self.conversations = [Conversation.objects.create(channel=self.channel, wa_id=f'91987654321{i}', consent='granted') for i in range(2)]
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def create_campaign(self):
        return self.client.post('/api/v1/whatsapp/campaigns/', {'name': 'Synthetic campaign', 'channel': str(self.channel.pk),
            'template': str(self.template.pk), 'parameters': ['Student'], 'recipients': [str(c.pk) for c in self.conversations]}, format='json')

    def test_campaign_mock_queue_is_idempotent_and_has_real_progress(self):
        response = self.create_campaign()
        self.assertEqual(response.status_code, 201)
        url = f'/api/v1/whatsapp/campaigns/{response.data["id"]}/queue-mock/'
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 200)
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 200)
        self.assertEqual(Message.objects.count(), 2)
        self.assertEqual(set(Message.objects.values_list('mode', flat=True)), {'mock'})
        self.assertEqual(self.client.get('/api/v1/whatsapp/campaigns/').data['results'][0]['progress']['pending'], 2)

    def test_revoked_consent_rolls_back_the_entire_campaign_queue(self):
        response = self.create_campaign()
        Conversation.objects.filter(pk=self.conversations[-1].pk).update(consent='revoked')
        result = self.client.post(f'/api/v1/whatsapp/campaigns/{response.data["id"]}/queue-mock/', {}, format='json')
        self.assertEqual(result.status_code, 400)
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(Campaign.objects.get().status, 'draft')

    @override_settings(WHATSAPP_MODE='live', WHATSAPP_LIVE_SENDS_ENABLED=True)
    def test_live_bulk_queue_is_disabled_even_if_individual_sends_are_enabled(self):
        response = self.create_campaign()
        result = self.client.post(f'/api/v1/whatsapp/campaigns/{response.data["id"]}/queue-mock/', {}, format='json')
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Message.objects.exists())

    def test_campaign_permissions_and_recipient_channel_validation(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.create_campaign().status_code, 403)
        self.client.force_authenticate(self.manager)
        self.conversations.append(Conversation.objects.create(channel=self.other_channel, wa_id='919876543299', consent='granted'))
        self.assertEqual(self.create_campaign().status_code, 400)

    def test_canned_reply_scope_edit_and_read_only_staff(self):
        data = {'branch': str(self.a.pk), 'title': 'Welcome', 'body': 'How can we help?'}
        response = self.client.post('/api/v1/whatsapp/canned-messages/', data, format='json')
        self.assertEqual(response.status_code, 201)
        pk = response.data['id']
        self.assertEqual(self.client.patch(f'/api/v1/whatsapp/canned-messages/{pk}/', {'body': 'Updated welcome'}, format='json').status_code, 200)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post('/api/v1/whatsapp/canned-messages/', data, format='json').status_code, 403)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/whatsapp/canned-messages/').data['count'], 0)

    def test_account_public_phone_validation_and_immutable_provider_identity(self):
        self.client.force_authenticate(self.management)
        url = f'/api/v1/whatsapp/channels/{self.channel.pk}/'
        self.assertEqual(self.client.patch(url, {'business_phone': '9876543210'}, format='json').data['business_phone'], '+919876543210')
        self.assertEqual(self.client.patch(url, {'phone_number_id': '999'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'business_phone': 'invalid'}, format='json').status_code, 400)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.patch(url, {'is_active': False}, format='json').status_code, 403)

    def test_mock_template_install_and_no_live_approval_spoofing(self):
        self.client.force_authenticate(self.management)
        url = f'/api/v1/whatsapp/channels/{self.channel.pk}/mock-template/'
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 200)
        self.assertEqual(Template.objects.get(name='mock_welcome').source_mode, 'mock')
        with override_settings(WHATSAPP_MODE='live'):
            self.assertEqual(self.client.post(url, {}, format='json').status_code, 400)

    def test_settings_only_exposes_readiness_flags(self):
        with override_settings(WHATSAPP_ACCESS_TOKEN='never-return-this-token', WHATSAPP_APP_SECRET='never-return-this-secret'):
            response = self.client.get('/api/v1/whatsapp/settings/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['access_token_configured'])
        self.assertFalse(response.data['bulk_sends_enabled'])
        self.assertNotIn('never-return', str(response.data))

    def test_ad_drafts_create_tracking_urls_and_do_not_publish(self):
        data = {'branch': str(self.a.pk), 'name': 'Python ad draft', 'destination': 'https://learnmoretech.in/courses/python',
            'platform': 'instagram', 'campaign_tag': 'python-october'}
        response = self.client.post('/api/v1/whatsapp/ad-drafts/', data, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIn('utm_source=instagram', response.data['tracking_url'])
        self.assertIn('utm_campaign=python-october', response.data['tracking_url'])
        self.assertEqual(AdDraft.objects.count(), 1)
        self.assertEqual(self.client.post('/api/v1/whatsapp/ad-drafts/', {**data, 'destination': 'https://unapproved.example/'}, format='json').status_code, 400)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/whatsapp/ad-drafts/').data['count'], 0)

    def test_message_trail_and_conversations_remain_scoped(self):
        Message.objects.create(conversation=self.conversations[0], direction='outbound', text='Draft reply', mode='mock')
        response = self.client.get('/api/v1/whatsapp/messages/?direction=outbound')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['channel_name'], 'Central')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/whatsapp/messages/').data['count'], 0)
