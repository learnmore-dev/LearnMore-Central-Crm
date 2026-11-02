from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from common.test_utils import crm_fixtures
from leads.services import create_lead
from .models import AutomationRun, AutomationTask
from .services import save_rule, enroll, process_run


class PostgreSQLAutomationConcurrencyTests(TransactionTestCase):
    def test_duplicate_workers_enroll_and_process_once(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requires PostgreSQL row locks.')
        a, b, owner, manager, other, management, contact = crm_fixtures()
        rule = save_rule(manager, {'branch': a, 'name': 'Race', 'is_active': True, 'business_hours': False, 'acknowledgement_minutes': 0})
        lead = create_lead(actor=manager, branch=a, contact=contact, title='Python')
        barrier = Barrier(4)

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                run = enroll(rule=rule, lead=lead)
                process_run(run.pk)
                return run.pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker) for _ in range(4)]
            ids = [f.result(timeout=60) for f in futures]
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(AutomationRun.objects.count(), 1)
        self.assertEqual(AutomationTask.objects.count(), 1)
        self.assertEqual(AutomationRun.objects.get().events.filter(code='message_simulated').count(), 1)
