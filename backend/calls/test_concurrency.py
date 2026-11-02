from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.utils import timezone
from common.test_utils import crm_fixtures
from contacts.models import Contact
from leads.models import Lead
from .models import CallLog
from .services import record_call, create_enquiry


class CallConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Concurrent call processing requires PostgreSQL row locks.')
        self.a, _, self.owner, _, _, _, _ = crm_fixtures()
        self.data = dict(branch=self.a, client_key='same-call', caller_phone='+919876543210', caller_name='Call student',
            status='answered', direction='incoming', started_at=timezone.now())

    def workers(self, function):
        barrier = Barrier(4)
        def run(_):
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                return function()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(run, range(4)))

    def test_concurrent_call_retries_create_one_record_and_contact(self):
        ids = self.workers(lambda: record_call(actor=self.owner, **self.data).pk)
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(CallLog.objects.count(), 1)
        self.assertEqual(Contact.objects.filter(full_name='Call student').count(), 1)

    def test_concurrent_create_enquiry_clicks_create_one_lead(self):
        call = record_call(actor=self.owner, **self.data)
        ids = self.workers(lambda: create_enquiry(actor=self.owner, call=call, title='Python enquiry').lead_id)
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(Lead.objects.count(), 1)
