from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from contacts.models import Contact
from leads.services import create_lead
from calls.services import record_call, create_enquiry
from intake.models import WebsiteSource, WebsiteSubmission
from intake.services import receive_submission
from messaging.models import Channel, Conversation, Message
from .test_utils import crm_fixtures


class LiveEnquiryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.website = WebsiteSource.objects.create(slug='learnmoretech', default_branch=self.a, actor=self.management)
        self.submission, _ = receive_submission(self.website, {'submission_id': 'web-1', 'full_name': 'Website student',
            'phone': '+919876543210', 'email': '', 'course': 'Python'})
        self.call = record_call(actor=self.manager, branch=self.a, client_key='call-1', caller_phone='+919876543211',
            caller_name='Call student', status='missed', direction='incoming', started_at=timezone.now())
        channel = Channel.objects.create(branch=self.a, name='Central WhatsApp', phone_number_id='12345', waba_id='67890')
        self.conversation = Conversation.objects.create(channel=channel, wa_id='919876543212', last_inbound_at=timezone.now())
        self.inbound = Message.objects.create(conversation=self.conversation, direction='inbound', text='Interested in DevOps', mode='live', queue_status='received')

    def feed(self, suffix=''):
        response = self.client.get('/api/v1/enquiry-dashboard/?period=all' + suffix)
        self.assertEqual(response.status_code, 200, str(response.data))
        return response.data

    def test_all_sources_visible_before_conversion_without_duplicate_leads(self):
        data = self.feed()
        self.assertEqual(data['count'], 3)
        self.assertEqual(data['source_totals']['website'], 1)
        self.assertEqual(data['source_totals']['call'], 1)
        self.assertEqual(data['source_totals']['whatsapp'], 1)
        self.assertEqual(data['totals']['needs_enquiry'], 1)
        self.assertEqual(data['totals']['awaiting_reply'], 1)
        create_enquiry(actor=self.manager, call=self.call, title='Call course')
        data = self.feed()
        self.assertEqual(data['count'], 3)
        call = next(row for row in data['results'] if row['source'] == 'call')
        self.assertIsNotNone(call['lead'])
        self.assertEqual(call['owner_name'], self.manager.username)

    def test_new_inbound_refreshes_one_conversation_and_mock_reply_does_not_resolve_it(self):
        Message.objects.filter(pk=self.inbound.pk).update(created_at=timezone.now()-timedelta(minutes=1))
        Message.objects.create(conversation=self.conversation, direction='inbound', text='New follow-up question', mode='live', queue_status='received')
        Message.objects.create(conversation=self.conversation, direction='outbound', text='Simulated reply', mode='mock', queue_status='sent')
        data = self.feed('&source=whatsapp')
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['preview'], 'New follow-up question')
        self.assertEqual(data['results'][0]['status'], 'awaiting_reply')

    def test_branch_scope_and_whatsapp_role_permissions(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.feed()['count'], 0)
        self.assertEqual(self.client.get(f'/api/v1/enquiry-dashboard/?branch={self.a.pk}').status_code, 400)
        accounts = get_user_model().objects.create_user(username='feed_accounts', role='accounts', branch=self.a)
        self.client.force_authenticate(accounts)
        data = self.feed()
        self.assertEqual(data['count'], 2)
        self.assertNotIn('whatsapp', data['sources'])
        self.assertNotIn('Interested in DevOps', str(data))
        self.assertEqual(self.client.get('/api/v1/enquiry-dashboard/?source=whatsapp').status_code, 403)

    def test_transferred_lead_does_not_expose_other_branch_owner_or_lead_id(self):
        from leads.models import Lead
        Lead.objects.filter(pk=self.submission.lead_id).update(branch=self.b, owner=self.other)
        row = self.feed('&source=website')['results'][0]
        self.assertEqual(row['status'], 'transferred')
        self.assertIsNone(row['lead'])
        self.assertIsNone(row['owner_name'])

    def test_source_status_search_and_today_filters(self):
        self.assertEqual(self.feed('&source=website&search=Python')['count'], 1)
        self.assertEqual(self.feed('&status=awaiting_reply')['count'], 1)
        WebsiteSubmission.objects.filter(pk=self.submission.pk).update(created_at=timezone.now()-timedelta(days=2))
        response = self.client.get('/api/v1/enquiry-dashboard/?period=today&source=website')
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(self.client.get('/api/v1/enquiry-dashboard/?status=invalid').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/enquiry-dashboard/?page=0').status_code, 400)

    def test_manual_leads_and_empty_outbound_conversations(self):
        create_lead(actor=self.manager, branch=self.a, contact=self.contact, title='Walk-in enquiry')
        Conversation.objects.create(channel=self.conversation.channel, wa_id='919876543299')
        data = self.feed()
        self.assertEqual(data['count'], 4)
        self.assertEqual(data['source_totals']['manual'], 1)

    def test_pagination_is_bounded_stable_and_read_only(self):
        from calls.models import CallLog
        for index in range(30):
            CallLog.objects.create(branch=self.a, client_key=f'extra-{index}', request_hash='x', caller_phone='+919876543211',
                status='answered', started_at=timezone.now(), contact=self.contact, created_by=self.manager)
        first, second = self.feed(), self.feed('&page=2')
        self.assertEqual(first['count'], 33)
        self.assertEqual(len(first['results']), 25)
        self.assertEqual(len(second['results']), 8)
        self.assertFalse(set(row['key'] for row in first['results']) & set(row['key'] for row in second['results']))
        self.assertEqual(self.client.post('/api/v1/enquiry-dashboard/', {}, format='json').status_code, 405)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/v1/enquiry-dashboard/').status_code, 403)
