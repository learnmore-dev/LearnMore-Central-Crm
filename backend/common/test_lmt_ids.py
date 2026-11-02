from datetime import timedelta
from importlib import import_module
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from contacts.models import Contact
from leads.services import create_lead, update_lead
from leads.models import Lead


class LMTIdentityAndArrivalTests(TestCase):
    def setUp(self):
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.lead = create_lead(actor=self.manager, contact=self.contact, branch=self.a, owner=self.owner, title='Python')
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def test_new_prefix_and_old_id_search(self):
        self.assertRegex(self.contact.contact_id, r'^LMT-C-\d{6,}$')
        self.assertRegex(self.lead.lead_id, r'^LMT-MT-L-\d{6,}$')
        response = self.client.get('/api/v1/contacts/', {'search': self.contact.contact_id.replace('LMT-', 'LM-')})
        self.assertEqual(response.data['count'], 1)
        response = self.client.get('/api/v1/leads/', {'search': self.lead.lead_id.replace('LMT-', 'LM-')})
        self.assertEqual(response.data['count'], 1)
        self.contact.contact_id = 'LMT-C-999999'
        with self.assertRaises(ValidationError):
            self.contact.save()

    def test_arrival_survives_updates_and_contact_earliest_is_branch_scoped(self):
        original = self.lead.received_at
        update_lead(actor=self.manager, lead=self.lead, title='Python weekend')
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.received_at, original)
        create_lead(actor=self.management, contact=self.contact, branch=self.b, title='Other branch',
            received_at=original-timedelta(days=10), received_via='crm_recorded')
        response = self.client.get(f'/api/v1/contacts/{self.contact.pk}/')
        self.assertEqual(response.data['first_enquiry_at'], original.isoformat())

    def test_controlled_migration_preserves_numbers_relationships_and_old_dates(self):
        migration = import_module('common.migrations.0004_lmt_ids_and_received_dates')
        original_contact, original_lead = self.contact.contact_id, self.lead.lead_id
        with transaction.atomic():
            editor = connection.schema_editor()
            migration.backwards(apps, editor)
            self.contact.refresh_from_db(); self.lead.refresh_from_db()
            self.assertEqual(self.contact.contact_id, original_contact.replace('LMT-', 'LM-'))
            migration.forwards(apps, editor)
            self.contact.refresh_from_db(); self.lead.refresh_from_db()
            self.assertEqual(self.contact.contact_id, original_contact)
            self.assertEqual(self.lead.lead_id, original_lead)
            self.assertEqual(self.lead.contact_id, self.contact.pk)
            self.assertEqual(self.lead.received_at, self.lead.created_at)
            self.assertEqual(self.lead.received_via, 'crm_recorded')

    def test_source_timestamp_is_independent_of_crm_creation(self):
        from calls.models import CallLog
        from calls.services import create_enquiry
        when = timezone.now()-timedelta(days=2)
        call = CallLog.objects.create(branch=self.a, contact=self.contact, created_by=self.owner,
            caller_phone='+919876543210', status='answered', started_at=when, client_key='arrival', request_hash='arrival')
        call = create_enquiry(actor=self.manager, call=call, title='AWS')
        self.assertEqual(call.lead.received_at, when)
        self.assertEqual(call.lead.received_via, 'call_started')
        self.assertGreater(call.lead.created_at, when)
