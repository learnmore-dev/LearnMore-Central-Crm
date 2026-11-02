from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.utils import timezone
from common.test_utils import crm_fixtures
from contacts.models import Contact
from followups.models import FollowUpTask
from followups.services import process_task
from leads.models import Lead
from leads.services import create_lead
from .models import CounsellorProfile, AssignmentHistory
from .services import route_lead, transfer_lead


class PostgreSQLRoutingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Routing concurrency requires real PostgreSQL row locks.')
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()

    def run_workers(self, worker, count=6):
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
            return [future.result(timeout=60) for future in futures]

    def test_concurrent_intake_never_exceeds_capacity_and_queues_remainder(self):
        CounsellorProfile.objects.filter(user__branch=self.a).update(max_active_leads=1)
        contacts = [Contact.objects.create(full_name='Student %s' % i, branch=self.a) for i in range(6)]
        results = self.run_workers(lambda index: create_lead(actor=self.manager, branch=self.a,
            contact=contacts[index], title='Concurrent enquiry'))
        self.assertEqual(sum(lead.owner_id is not None for lead in results), 2)
        self.assertEqual(Lead.objects.filter(owner=self.owner).count(), 1)
        self.assertEqual(Lead.objects.filter(owner=self.manager).count(), 1)
        self.assertEqual(Lead.objects.filter(owner__isnull=True).count(), 4)
        self.assertEqual(AssignmentHistory.objects.count(), 6)
        self.assertEqual(FollowUpTask.objects.filter(kind='unassigned').count(), 4)

    def test_same_lead_concurrent_routing_preserves_single_assignment(self):
        lead = create_lead(actor=self.manager, branch=self.a, contact=self.contact, title='Route race')
        CounsellorProfile.objects.filter(user=self.owner).update(is_available=False)
        results = self.run_workers(lambda _: route_lead(lead=Lead(pk=lead.pk), actor=self.manager))
        self.assertTrue(all(result.owner_id == self.manager.pk for result in results))
        self.assertEqual(lead.assignment_history.count(), 2)
        self.assertEqual(lead.tasks.filter(kind='acknowledgement', status='pending').count(), 1)

    def test_simultaneous_overdue_workers_reassign_and_escalate_once(self):
        lead = create_lead(actor=self.manager, branch=self.a, contact=self.contact, title='SLA race')
        task = lead.tasks.get(kind='acknowledgement')
        now = timezone.now()
        FollowUpTask.objects.filter(pk=task.pk).update(due_at=now)
        results = self.run_workers(lambda _: process_task(task.pk, now))
        self.assertEqual(sum(results), 1)
        lead.refresh_from_db()
        self.assertEqual(lead.assignment_version, 2)
        self.assertEqual(lead.assignment_history.filter(status='escalated').count(), 1)
        self.assertEqual(lead.tasks.filter(kind='escalation').count(), 1)

    def test_opposite_branch_transfers_lock_branches_in_consistent_order(self):
        first = create_lead(actor=self.management, branch=self.a, contact=self.contact, title='A enquiry')
        second = create_lead(actor=self.management, branch=self.b, contact=self.contact, title='B enquiry')
        leads, destinations = [first, second], [self.b, self.a]
        results = self.run_workers(lambda index: transfer_lead(lead=leads[index], actor=self.management,
            branch=destinations[index], reason='Authorized cross-branch transfer'), count=2)
        self.assertEqual(results[0].branch_id, self.b.pk)
        self.assertEqual(results[1].branch_id, self.a.pk)
        self.assertEqual(AssignmentHistory.objects.filter(status='transferred').count(), 2)
