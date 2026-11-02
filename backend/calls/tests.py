from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from contacts.models import Contact, ContactIdentifier
from leads.models import Lead
from .models import CallLog


class CallLogTests(TestCase):
    def setUp(self):
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.payload = {'branch': str(self.a.pk), 'client_key': 'call-1', 'caller_phone': '9876543210',
            'caller_name': 'Phone Student', 'direction': 'incoming', 'status': 'answered',
            'started_at': timezone.now().isoformat(), 'duration_seconds': 90, 'forwarded_to': 'Manager 1', 'notes': 'Interested in Python'}

    def record(self, **changes):
        return self.client.post('/api/v1/call-logs/', {**self.payload, **changes}, format='json')

    def test_new_number_creates_contact_but_no_enquiry_until_clicked(self):
        self.assertEqual(self.record().status_code, 201)
        call = CallLog.objects.get()
        self.assertEqual(call.contact.full_name, 'Phone Student')
        self.assertEqual(call.contact.source, 'call')
        self.assertEqual(call.caller_phone, '+919876543210')
        self.assertFalse(Lead.objects.exists())
        self.assertTrue(call.contact.activities.filter(body__contains='Manager 1').exists())

    def test_unique_existing_number_links_without_renaming_contact(self):
        ContactIdentifier.objects.create(contact=self.contact, kind='phone', value='9876543210')
        self.record()
        self.assertEqual(CallLog.objects.get().contact, self.contact)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.full_name, 'Test Person')
        self.assertEqual(Contact.objects.count(), 1)

    def test_retries_do_not_duplicate_calls_or_contacts(self):
        first, second = self.record(), self.record()
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(CallLog.objects.count(), 1)
        self.assertEqual(self.record(notes='Changed').status_code, 400)

    def test_create_enquiry_is_routed_linked_and_idempotent(self):
        pk = self.record().data['id']
        url = f'/api/v1/call-logs/{pk}/create-enquiry/'
        first = self.client.post(url, {'title': 'Python enquiry'}, format='json')
        second = self.client.post(url, {'title': 'Python enquiry'}, format='json')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['lead'], second.data['lead'])
        lead = Lead.objects.get()
        self.assertEqual(lead.source, 'call')
        self.assertEqual(lead.owner, self.owner)
        self.assertTrue(lead.activities.filter(body__contains='Interested in Python').exists())

    def test_shared_number_requires_manager_review(self):
        for contact in [self.contact, Contact.objects.create(full_name='Shared phone', branch=self.a)]:
            ContactIdentifier.objects.create(contact=contact, kind='phone', value='9876543210')
        pk = self.record().data['id']
        self.assertIsNone(CallLog.objects.get().contact)
        self.assertEqual(self.client.post(f'/api/v1/call-logs/{pk}/create-enquiry/', {'title': 'Course'}, format='json').status_code, 400)
        url = f'/api/v1/call-logs/{pk}/resolve-contact/'
        data = {'decision': 'linked', 'reason': 'Verified caller', 'contact': str(self.contact.pk)}
        self.assertEqual(self.client.post(url, data, format='json').status_code, 403)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(url, data, format='json').status_code, 200)
        self.assertEqual(CallLog.objects.get().contact, self.contact)

    def test_cross_branch_candidates_are_redacted(self):
        hidden = Contact.objects.create(full_name='Private other branch', branch=self.b)
        ContactIdentifier.objects.create(contact=hidden, kind='phone', value='9876543210')
        data = self.record().data
        self.assertIsNone(data['contact'])
        self.assertEqual(data['candidates'], [])
        self.assertNotIn('Private other branch', str(data))

    def test_permissions_scope_validation_and_filters(self):
        self.assertEqual(self.record(caller_phone='invalid').status_code, 400)
        self.assertEqual(self.record(contact=str(self.contact.pk)).status_code, 400)
        self.assertEqual(self.record(origin='myoperator').status_code, 400)
        self.assertEqual(self.record(branch=str(self.b.pk)).status_code, 400)
        pk = self.record(status='missed', duration_seconds=0).data['id']
        self.assertEqual(self.client.get('/api/v1/call-logs/?status=missed&search=Manager').data['count'], 1)
        self.assertEqual(self.client.get('/api/v1/call-logs/?status=answered').data['count'], 0)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/call-logs/').data['count'], 0)
        self.assertEqual(self.client.post(f'/api/v1/call-logs/{pk}/create-enquiry/', {'title': 'Hijack'}, format='json').status_code, 404)
