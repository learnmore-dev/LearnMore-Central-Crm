from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from common.test_utils import crm_fixtures
from contacts.models import Contact
from leads.models import Lead
from .models import WebsiteSource, WebsiteSubmission
from .services import receive_submission


class WebsiteConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Website intake concurrency requires PostgreSQL row locks.')
        self.a, _, _, _, _, self.management, _ = crm_fixtures()
        self.source = WebsiteSource.objects.create(slug='learnmoretech', default_branch=self.a, actor=self.management)

    def workers(self, function):
        barrier = Barrier(4)
        def run(index):
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                return function(index)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(run, range(4)))

    def test_retried_submission_creates_one_contact_and_one_enquiry(self):
        data = {'submission_id': 'same', 'full_name': 'Concurrent website student', 'phone': '+919876543210', 'email': ''}
        ids = self.workers(lambda _: receive_submission(self.source, data)[0].pk)
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(WebsiteSubmission.objects.count(), 1)
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(Contact.objects.filter(full_name=data['full_name']).count(), 1)

    def test_distinct_enquiries_do_not_silently_merge_shared_identities(self):
        self.workers(lambda i: receive_submission(self.source, {'submission_id': f'distinct-{i}',
            'full_name': f'Website student {i}', 'phone': '+919876543210', 'email': ''}))
        self.assertEqual(WebsiteSubmission.objects.count(), 4)
        self.assertEqual(WebsiteSubmission.objects.filter(status='review').count(), 3)
        self.assertEqual(Lead.objects.count(), 1)
