from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient
from activities.models import Activity
from common.test_utils import crm_fixtures
from contacts.models import Contact
from .models import Lead
from .services import create_lead, update_lead


class LeadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def create(self, **extra):
        data = {'actor': self.owner, 'contact': self.contact, 'branch': self.a, 'owner': self.owner,
                'title': 'Python course', 'next_action': 'Call about demo', 'next_action_at': timezone.now()}
        data.update(extra)
        return create_lead(**data)

    def test_distinct_enquiries_have_separate_ids_and_preserved_history(self):
        first, second = self.create(), self.create(title='Data Science course')
        self.assertNotEqual(first.lead_id, second.lead_id)
        self.assertRegex(first.lead_id, r'^LMT-MT-L-\d{6,}$')
        self.assertEqual(self.contact.leads.count(), 2)
        self.assertEqual(self.contact.activities.filter(kind='lead_created').count(), 2)
        self.assertEqual(self.contact.activities.filter(kind='assignment').count(), 2)

    def test_active_lead_action_and_unassigned_requirements(self):
        for extra in ({'next_action': '', 'next_action_at': None}, {'next_action_at': None},
                      {'no_followup_reason': 'Not required'}, {'unassigned_reason': 'Awaiting routing'}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                self.create(**extra)
        queued = self.create(owner=None, unassigned_reason='Awaiting branch routing')
        self.assertIsNotNone(queued.owner)  # Milestone 3 now routes all new enquiries.
        self.assertEqual(queued.unassigned_reason, '')
        nofollowup = self.create(next_action='', next_action_at=None, no_followup_reason='Waiting for student to finish exams')
        self.assertTrue(nofollowup.no_followup_reason)

    def test_database_rejects_active_lead_without_action_and_unowned_without_reason(self):
        for extra in ({'owner': self.owner}, {'next_action': 'Call', 'next_action_at': timezone.now()}):
            with self.subTest(extra=extra), self.assertRaises(IntegrityError), transaction.atomic():
                Lead.objects.create(contact=self.contact, branch=self.a, title='Invalid direct write', **extra)

    def test_owner_must_be_active_in_branch_and_sales_role(self):
        self.owner.is_active = False
        self.owner.save()
        with self.assertRaises(ValidationError):
            self.create(actor=self.manager)
        for owner in (self.other, self.management):
            with self.subTest(owner=owner.pk), self.assertRaises(ValidationError):
                self.create(actor=self.manager, owner=owner)

    def test_counsellor_cannot_assign_another_person_or_edit_their_lead(self):
        with self.assertRaises(PermissionDenied):
            self.create(owner=self.manager)
        lead = self.create(actor=self.manager, owner=self.manager)
        with self.assertRaises(PermissionDenied):
            update_lead(actor=self.owner, lead=lead, title='Hijacked')

    def test_partial_updates_record_timeline_and_keep_owner_and_branch(self):
        lead = self.create()
        updated = update_lead(actor=self.owner, lead=lead, status='contacted')
        self.assertEqual(updated.owner, self.owner)
        self.assertEqual(updated.branch, self.a)
        self.assertEqual(updated.activities.filter(kind='lead_updated').count(), 1)
        self.assertEqual(updated.activities.filter(kind='assignment').count(), 1)
        with self.assertRaises(ValidationError):
            update_lead(actor=self.management, lead=lead, branch=self.b)
        with self.assertRaises(ValidationError):
            update_lead(actor=self.manager, lead=lead, owner=self.manager)

    def test_api_creation_partial_updates_filters_and_rejection_of_transfer(self):
        payload = {'contact': str(self.contact.pk), 'owner': str(self.owner.pk), 'title': 'API enquiry',
                   'next_action': 'Schedule demo', 'next_action_at': timezone.now().isoformat()}
        response = self.client.post('/api/v1/leads/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        url = '/api/v1/leads/%s/' % response.data['id']
        self.assertEqual(self.client.patch(url, {'status': 'qualified'}, format='json').status_code, 200)
        for extra in ({'branch': str(self.b.pk)}, {'owner': str(self.manager.pk)}, {'contact': str(self.contact.pk)},
                      {'lead_id': 'LMT-L-100000'}, {'created_by': str(self.other.pk)}):
            self.assertEqual(self.client.patch(url, extra, format='json').status_code, 400)
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.assertEqual(self.client.get('/api/v1/leads/?status=qualified').data['count'], 1)
        self.assertEqual(self.client.get('/api/v1/leads/?owner=bad').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/leads/?status=unknown').status_code, 400)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/leads/?branch=%s' % self.a.pk).data['count'], 0)

    def test_contact_shared_across_branches_does_not_expose_other_leads(self):
        first = self.create()
        second = self.create(actor=self.management, branch=self.b, owner=self.other)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/contacts/%s/' % self.contact.pk).status_code, 200)
        self.assertEqual(self.client.get('/api/v1/leads/%s/' % first.pk).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/leads/%s/' % second.pk).status_code, 200)
        self.assertEqual(self.client.patch('/api/v1/contacts/%s/' % self.contact.pk, {'full_name': 'Branch overwrite'}).status_code, 403)

    def test_all_roles_have_scoped_reads_but_accounts_and_support_cannot_write(self):
        lead = self.create()
        for role in ('super_admin', 'management', 'branch_manager', 'counsellor', 'accounts', 'support'):
            with self.subTest(role=role):
                user = get_user_model().objects.create_user(username='role_' + role, role=role, branch=self.a)
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get('/api/v1/contacts/').status_code, 200)
                self.assertEqual(self.client.get('/api/v1/leads/').status_code, 200)
                self.assertEqual(self.client.get('/api/v1/activities/').status_code, 200)
                if role in ('accounts', 'support'):
                    for endpoint in ('contacts', 'contact-identifiers', 'leads', 'activities'):
                        self.assertEqual(self.client.post('/api/v1/%s/' % endpoint, {}, format='json').status_code, 403)
        self.client.force_authenticate(None)
        for endpoint in ('contacts', 'contact-identifiers', 'duplicate-reviews', 'leads', 'activities'):
            self.assertEqual(self.client.get('/api/v1/%s/' % endpoint).status_code, 403)

    def test_inactive_branch_cannot_receive_new_enquiries(self):
        self.a.is_active = False
        self.a.save()
        with self.assertRaises(ValidationError):
            self.create()
