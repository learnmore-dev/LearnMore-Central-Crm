from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from contacts.models import Contact
from leads.models import Lead
from leads.services import create_lead
from .models import Activity


class ActivityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.lead = create_lead(actor=self.owner, contact=self.contact, branch=self.a, owner=self.owner,
            title='Python', next_action='Call', next_action_at=timezone.now())

    def test_note_creation_actor_and_timeline_filter(self):
        response = self.client.post('/api/v1/activities/', {'contact': str(self.contact.pk), 'lead': str(self.lead.pk), 'body': 'Demo requested'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['actor'], self.owner.pk)
        self.assertEqual(response.data['kind'], 'note')
        timeline = self.client.get('/api/v1/activities/?contact=%s' % self.contact.pk)
        self.assertEqual(timeline.data['count'], 3)  # creation, assignment and note
        self.assertEqual(timeline.data['results'][0]['body'], 'Demo requested')
        url = '/api/v1/activities/%s/' % response.data['id']
        self.assertEqual(self.client.patch(url, {'body': 'Edited'}).status_code, 405)
        self.assertEqual(self.client.delete(url).status_code, 405)

    def test_cannot_spoof_events_or_mix_contact_and_lead(self):
        second = Contact.objects.create(full_name='Second', branch=self.a)
        for extra in ({'actor': str(self.manager.pk)}, {'kind': 'lead_created'}, {'created_at': timezone.now().isoformat()},
                      {'contact': str(second.pk), 'lead': str(self.lead.pk)}, {'body': ' '}):
            payload = {'contact': str(self.contact.pk), 'body': 'Note'}
            payload.update(extra)
            self.assertEqual(self.client.post('/api/v1/activities/', payload, format='json').status_code, 400)

    def test_branch_timeline_stays_private_for_shared_contact(self):
        second = create_lead(actor=self.management, contact=self.contact, branch=self.b, owner=self.other,
            title='Another enquiry', next_action='Call', next_action_at=timezone.now())
        response = self.client.get('/api/v1/activities/?contact=%s' % self.contact.pk)
        self.assertEqual(response.data['count'], 2)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/activities/?contact=%s' % self.contact.pk).data['count'], 2)
        self.assertEqual(self.client.get('/api/v1/activities/%s/' % self.lead.activities.first().pk).status_code, 404)
        self.assertEqual(self.client.post('/api/v1/activities/', {'contact': str(self.contact.pk), 'lead': str(self.lead.pk), 'body': 'Leak'}, format='json').status_code, 400)

    def test_model_cannot_edit_or_delete_activity(self):
        activity = self.lead.activities.first()
        activity.body = 'Changed'
        with self.assertRaises(ValidationError):
            activity.save()
        with self.assertRaises(ValidationError):
            activity.delete()

    def test_postgres_blocks_queryset_mutation_and_id_rewrites(self):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL trigger verification requires PostgreSQL.')
        for action in (lambda: self.lead.activities.update(body='Tampered'), lambda: self.lead.activities.all().delete(),
                       lambda: Contact.objects.filter(pk=self.contact.pk).update(contact_id='LM-C-999999'),
                       lambda: Lead.objects.filter(pk=self.lead.pk).update(lead_id='LM-L-999999')):
            with self.assertRaises(DatabaseError), transaction.atomic():
                action()
