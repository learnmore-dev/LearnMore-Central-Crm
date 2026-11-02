from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
import uuid
from django.db import close_old_connections, connections, connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from common.test_utils import crm_fixtures
from contacts.models import Contact
from leads.services import create_lead
from .models import Demo, DemoTask
from .services import book_demo, process_demos


class PostgreSQLEducationConcurrencyTests(TransactionTestCase):
    def test_simultaneous_bookings_cannot_double_book_one_counsellor(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requires PostgreSQL row locks.')
        a, b, owner, manager, other, management, contact = crm_fixtures()
        second = Contact.objects.create(branch=a, full_name='Another student')
        leads = [create_lead(actor=manager, branch=a, contact=c, owner=owner, title='Python') for c in (contact, second)]
        start = timezone.now()+timedelta(days=2)
        barrier = Barrier(2)

        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                try:
                    book_demo(manager, leads[index], course='Python', mode='classroom', location='Central', starts_at=start, duration_minutes=60, client_key=uuid.uuid4())
                    process_demos()
                    return True
                except ValidationError:
                    return False
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, i) for i in range(2)]
            results = [f.result(timeout=60) for f in futures]
        self.assertEqual(sum(results), 1)
        self.assertEqual(Demo.objects.count(), 1)
        self.assertEqual(DemoTask.objects.count(), 2)
