from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from contacts.models import Contact, DuplicateReview
from contacts.services import create_contact, resolve_review
from rest_framework.exceptions import ValidationError
from leads.models import Lead
from .identifiers import next_identifier
from .test_utils import crm_fixtures


class PostgreSQLConcurrencyTests(TransactionTestCase):
    """Real transactions and one independent database connection per worker."""
    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Row locks and concurrent intake must be tested on PostgreSQL.')
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()

    def run_concurrently(self, worker, count=6):
        barrier = Barrier(count)

        def run(index):
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                return worker(index)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=count) as pool:
            futures = [pool.submit(run, index) for index in range(count)]
            return [future.result(timeout=45) for future in futures]

    def test_concurrent_contact_and_lead_allocation(self):
        contacts = self.run_concurrently(lambda index: Contact.objects.create(full_name='Worker %s' % index, branch_id=self.a.pk).contact_id)
        leads = self.run_concurrently(lambda index: Lead.objects.create(contact_id=self.contact.pk, branch_id=self.a.pk,
            owner_id=self.owner.pk, title='Enquiry %s' % index, next_action='Call', next_action_at=timezone.now()).lead_id)
        self.assertEqual(len(set(contacts)), 6)
        self.assertEqual(len(set(leads)), 6)
        self.assertTrue(all(value.startswith('LMT-C-') for value in contacts))
        self.assertTrue(all(value.startswith('LMT-MT-L-') for value in leads))

    def test_concurrent_same_phone_intake_creates_one_contact_and_reviews(self):
        results = self.run_concurrently(lambda index: create_contact(actor=self.owner, branch=self.a, full_name='Intake %s' % index,
            identifiers=[{'kind': 'phone', 'value': '9876543210'}]))
        self.assertEqual(sum(isinstance(result, Contact) for result in results), 1)
        self.assertEqual(sum(isinstance(result, DuplicateReview) for result in results), 5)
        self.assertEqual(Contact.objects.filter(identifiers__normalized_value='+919876543210').count(), 1)

    def test_sequence_rollback_and_deleted_records_do_not_collide(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                next_identifier('lead', 'LMT-L')
                raise RuntimeError('Rollback')
        values = self.run_concurrently(lambda index: next_identifier('lead', 'LMT-L'))
        self.assertEqual(len(set(values)), 6)

    def test_concurrent_duplicate_resolution_can_create_only_one_person(self):
        identifiers = [{'kind': 'phone', 'value': '9876543210'}]
        create_contact(actor=self.owner, branch=self.a, full_name='First', identifiers=identifiers)
        review = create_contact(actor=self.owner, branch=self.a, full_name='Family member', identifiers=identifiers)

        def resolve(index):
            try:
                resolve_review(actor=self.manager, review=DuplicateReview.objects.get(pk=review.pk),
                               decision='separate', reason='Confirmed distinct person')
                return 'resolved'
            except ValidationError:
                return 'already_resolved'

        self.assertCountEqual(self.run_concurrently(resolve, count=2), ['resolved', 'already_resolved'])
        self.assertEqual(Contact.objects.filter(identifiers__normalized_value='+919876543210').count(), 2)
