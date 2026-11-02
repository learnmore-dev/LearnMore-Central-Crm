from importlib import import_module
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from leads.services import create_lead
from routing.services import transfer_lead
from branches.models import Branch
from contacts.models import Contact


class BranchEnquiryIDTests(TestCase):
    def setUp(self):
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()

    def lead(self, branch=None, contact=None):
        return create_lead(actor=self.management, contact=contact or self.contact, branch=branch or self.a, title='Python')

    def test_three_branch_codes_and_shared_unique_number_sequence(self):
        kn = Branch.objects.create(name='Kalyan Nagar', code='kalyan-nagar')
        leads = [self.lead(branch=b) for b in [self.a, self.b, kn]]
        self.assertTrue(leads[0].lead_id.startswith('LMT-MT-L-'))
        self.assertTrue(leads[1].lead_id.startswith('LMT-BTM-L-'))
        self.assertTrue(leads[2].lead_id.startswith('LMT-KN-L-'))
        self.assertEqual(len({l.lead_id.rsplit('-', 1)[-1] for l in leads}), 3)

    def test_transfer_preserves_origin_and_id(self):
        lead = self.lead()
        original = lead.lead_id
        transfer_lead(lead=lead, actor=self.management, branch=self.b, reason='Student prefers BTM')
        lead.refresh_from_db()
        self.assertEqual(lead.branch_id, self.b.pk)
        self.assertEqual(lead.origin_branch_id, self.a.pk)
        self.assertEqual(lead.origin_branch_code, 'MT')
        self.assertEqual(lead.lead_id, original)
        lead.origin_branch_code = 'BTM'
        with self.assertRaises(ValidationError):
            lead.save()

    def test_existing_id_migration_uses_earliest_assignment_and_keeps_alias(self):
        lead = self.lead()
        transfer_lead(lead=lead, actor=self.management, branch=self.b, reason='Transfer')
        migration = import_module('common.migrations.0005_branch_enquiry_ids')
        with transaction.atomic():
            editor = connection.schema_editor()
            migration.backwards(apps, editor)
            lead.refresh_from_db()
            old = lead.lead_id
            self.assertTrue(old.startswith('LMT-L-'))
            migration.forwards(apps, editor)
            lead.refresh_from_db()
            self.assertEqual(lead.legacy_lead_id, old)
            self.assertTrue(lead.lead_id.startswith('LMT-MT-L-'))
            self.assertEqual(lead.branch_id, self.b.pk)
            self.assertTrue(lead.origin_branch_verified)
            client = APIClient(); client.force_authenticate(self.management)
            self.assertEqual(client.get('/api/v1/leads/', {'search': old}).data['count'], 1)
            self.assertEqual(client.get('/api/v1/leads/', {'search': old.replace('LMT-', 'LM-')}).data['count'], 1)
            row = client.get(f'/api/v1/leads/{lead.pk}/').data
            self.assertEqual(row['origin_branch_code'], 'MT')
            self.assertEqual(row['branch_name'], self.b.name)
