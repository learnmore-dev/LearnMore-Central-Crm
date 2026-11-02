from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from contacts.models import Contact, ContactIdentifier, DuplicateReview
from leads.models import Lead
from leads.services import create_lead
from activities.models import Activity
from calls.models import CallLog
from .models import Channel, Conversation, Message
from .services import inbound


class WhatsAppIntakeTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.channel = Channel.objects.create(branch=self.a, name='LearnMore inbox', phone_number_id='1234', waba_id='5678', intake_actor=self.management)
        self.phone = '919876543210'
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def receive(self, key='message-1', phone=None, body='Interested in Python', channel=None, seconds=0):
        channel = channel or self.channel
        inbound(channel, {'from': phone or self.phone, 'id': key, 'type': 'text', 'text': {'body': body},
            'timestamp': str(int((timezone.now()+timedelta(seconds=seconds)).timestamp()))}, profile_name='Student A')
        return Conversation.objects.get(channel=channel, wa_id=phone or self.phone)

    def enquiry(self, contact=None):
        return create_lead(actor=self.manager, contact=contact or self.contact, branch=self.a, title='Python', owner=self.owner)

    def test_new_inbound_creates_contact_id_and_routes_one_enquiry(self):
        before = Contact.objects.count()
        row = self.receive()
        self.assertEqual(Contact.objects.count(), before+1)
        self.assertTrue(row.contact.contact_id.startswith('LMT-C'))
        self.assertTrue(row.lead.lead_id.startswith('LMT-MT-L'))
        self.assertIsNotNone(row.lead.owner_id)
        self.assertEqual(row.identity_status, 'new')
        self.assertEqual(row.lead.source, 'whatsapp')
        self.assertTrue(row.lead.tasks.exists())
        owner, lead, contact = row.lead.owner_id, row.lead_id, row.contact_id
        self.receive(); self.receive('message-2')
        row.refresh_from_db()
        self.assertEqual((row.contact_id, row.lead_id, row.lead.owner_id), (contact, lead, owner))
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 2)
        self.assertEqual(row.identity_status, 'matched')

    def test_linked_whatsapp_enquiry_does_not_start_duplicate_automation(self):
        from automation.services import save_rule, process_automations
        from automation.models import AutomationRun
        save_rule(self.manager, dict(branch=self.a, source='whatsapp', name='WhatsApp welcome', is_active=True))
        row = self.receive()
        process_automations()
        self.assertEqual(AutomationRun.objects.count(), 1)
        self.assertEqual(AutomationRun.objects.get().lead_id, row.lead_id)

    def test_signed_webhook_routes_and_uses_profile_name(self):
        import hashlib
        import hmac
        import json
        from django.test import override_settings
        from .services import process_webhooks
        raw = json.dumps({'object': 'whatsapp_business_account', 'entry': [{'id': '5678', 'changes': [{'field': 'messages', 'value': {
            'metadata': {'phone_number_id': '1234'}, 'contacts': [{'wa_id': self.phone, 'profile': {'name': 'Verified display name'}}],
            'messages': [{'id': 'signed-inbound', 'from': self.phone, 'type': 'text', 'text': {'body': 'Course enquiry'}, 'timestamp': str(int(timezone.now().timestamp()))}]
        }}]}]}).encode()
        signature = 'sha256='+hmac.new(b'test-secret', raw, hashlib.sha256).hexdigest()
        with override_settings(WHATSAPP_APP_SECRET='test-secret'):
            response = self.client.post('/api/v1/whatsapp/webhook/', raw, content_type='application/json', HTTP_X_HUB_SIGNATURE_256=signature)
            self.assertEqual(response.status_code, 200)
            process_webhooks()
        row = Conversation.objects.get(wa_id=self.phone)
        self.assertEqual(row.contact.full_name, 'Verified display name')
        self.assertIsNotNone(row.lead_id)

    def test_existing_contact_and_enquiry_keep_original_owner(self):
        ContactIdentifier.objects.create(contact=self.contact, kind='phone', value='+'+self.phone)
        lead = self.enquiry()
        row = self.receive()
        self.assertEqual(row.contact_id, self.contact.pk)
        self.assertEqual(row.identity_status, 'matched')
        self.assertEqual(row.lead_id, lead.pk)
        self.assertEqual(row.lead.owner_id, self.owner.pk)
        self.assertEqual(Lead.objects.count(), 1)

    def test_closed_enquiry_creates_new_enquiry_with_same_contact(self):
        row = self.receive()
        old = row.lead_id
        Lead.objects.filter(pk=old).update(status='won')
        row = self.receive('message-2')
        self.assertNotEqual(row.lead_id, old)
        self.assertEqual(Lead.objects.filter(contact=row.contact).count(), 2)

    def test_multiple_active_courses_require_explicit_enquiry_choice(self):
        ContactIdentifier.objects.create(contact=self.contact, kind='phone', value='+'+self.phone)
        first, second = self.enquiry(), self.enquiry()
        row = self.receive()
        self.assertIsNone(row.lead_id)
        self.assertIn('Multiple active enquiries', row.intake_note)
        response = self.client.post(f'/api/v1/whatsapp/conversations/{row.pk}/enquiry/', {'lead': str(second.pk)}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertEqual(row.lead_id, second.pk)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(f'/api/v1/whatsapp/conversations/{row.pk}/enquiry/', {'lead': str(first.pk)}, format='json').status_code, 403)

    def test_shared_phone_requires_review_and_can_be_resolved(self):
        for contact in (self.contact, Contact.objects.create(full_name='Other student', branch=self.a, created_by=self.manager)):
            ContactIdentifier.objects.create(contact=contact, kind='phone', value='+'+self.phone)
        row = self.receive()
        self.assertEqual(row.identity_status, 'review')
        self.assertIsNone(row.contact_id)
        self.assertEqual(Lead.objects.count(), 0)
        self.receive('message-2')
        self.assertEqual(DuplicateReview.objects.count(), 1)
        response = self.client.post(f'/api/v1/whatsapp/conversations/{row.pk}/resolve-identity/',
            dict(decision='linked', reason='Verified with student', contact=str(self.contact.pk)), format='json')
        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertEqual(row.contact_id, self.contact.pk)
        self.assertIsNotNone(row.lead_id)

    def test_other_branch_identity_is_not_disclosed_to_branch_manager(self):
        contact = Contact.objects.create(full_name='Private other branch', branch=self.b, created_by=self.other)
        ContactIdentifier.objects.create(contact=contact, kind='phone', value='+'+self.phone)
        row = self.receive()
        response = self.client.get(f'/api/v1/whatsapp/conversations/{row.pk}/')
        self.assertEqual(response.data['review_candidates'], [])
        self.assertIsNone(response.data['contact_label'])
        self.client.force_authenticate(self.management)
        response = self.client.post(f'/api/v1/whatsapp/conversations/{row.pk}/resolve-identity/',
            dict(decision='linked', reason='Confirmed identity across branches', contact=str(contact.pk)), format='json')
        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertEqual(row.contact_id, contact.pk)
        self.assertEqual(row.lead.branch_id, self.a.pk)

    def test_optout_disabled_channel_and_missing_actor_do_not_start_work(self):
        row = self.receive(body='STOP')
        self.assertEqual(row.consent, 'revoked')
        self.assertIsNone(row.lead_id)
        self.channel.intake_actor = None; self.channel.save()
        row = self.receive('message-2', phone='919876543211')
        self.assertEqual(row.identity_status, 'blocked')
        self.assertIsNone(row.contact_id)
        self.channel.intake_actor = self.management; self.channel.is_active = False; self.channel.save()
        row = self.receive('message-3', phone='919876543212')
        self.assertIsNone(row.contact_id)
        self.assertEqual(Message.objects.count(), 3)

    def test_no_capacity_goes_to_manager_queue_and_other_channels_reuse_identity(self):
        from routing.models import CounsellorProfile
        CounsellorProfile.objects.all().update(is_available=False)
        row = self.receive()
        self.assertIsNone(row.lead.owner_id)
        self.assertTrue(row.lead.unassigned_reason)
        channel = Channel.objects.create(branch=self.a, name='Second inbox', phone_number_id='3333', waba_id='5678', intake_actor=self.management)
        second = self.receive('second-channel-message', channel=channel)
        self.assertEqual(second.contact_id, row.contact_id)
        self.assertEqual(second.lead_id, row.lead_id)

    def test_ownership_search_mine_filter_and_new_course_retries(self):
        row = self.receive()
        response = self.client.get('/api/v1/whatsapp/conversations/', {'search': row.contact.contact_id})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['ownership']['lead_label'], row.lead.lead_id)
        self.client.force_authenticate(row.lead.owner)
        self.assertEqual(self.client.get('/api/v1/whatsapp/conversations/', {'mine': 'true'}).data['count'], 1)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f'/api/v1/whatsapp/conversations/{row.pk}/').status_code, 404)
        self.client.force_authenticate(self.manager)
        for _ in range(2):
            response = self.client.post(f'/api/v1/whatsapp/conversations/{row.pk}/enquiry/', {'title': 'Java training'}, format='json')
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Lead.objects.filter(contact=row.contact).count(), 2)

    def test_combined_history_contains_chats_calls_notes_and_is_scoped(self):
        row = self.receive()
        CallLog.objects.create(branch=self.a, contact=row.contact, created_by=self.owner, caller_phone='+'+self.phone,
            started_at=timezone.now(), direction='outgoing', status='answered', notes='Discussed weekend batch', client_key='call', request_hash='call')
        Activity.objects.create(contact=row.contact, branch=self.a, actor=self.owner, kind='note', body='Prefers classroom training')
        Activity.objects.create(contact=row.contact, branch=self.b, actor=self.other, kind='note', body='Private other branch discussion')
        url = f'/api/v1/contacts/{row.contact_id}/history/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({r['source'] for r in response.data['results']}, {'whatsapp', 'call', 'activity'})
        self.assertNotIn('Private other branch discussion', str(response.data))
        self.assertIn('Discussed weekend batch', str(response.data))
        response = self.client.get(url, {'source': 'call'})
        self.assertEqual(response.data['count'], 1)
        self.assertIn('%2B', response.data['results'][0]['target'])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_authenticate(self.management)
        self.assertIn('Private other branch discussion', str(self.client.get(url).data))
