from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from leads.services import create_lead, update_lead
from routing.models import CounsellorProfile, RoutingPolicy
from routing.services import acknowledge, manual_assign
from .models import FollowUpTask
from .services import process_slas, create_task, complete_task


class SLATests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.lead = create_lead(actor=self.manager, contact=self.contact, branch=self.a, title='New enquiry')
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def overdue_ack(self):
        now = timezone.now()
        self.lead.tasks.filter(kind='acknowledgement').update(due_at=now - timedelta(seconds=1))
        return now

    def test_assignment_creates_ack_and_new_enquiry_followup_deadlines(self):
        ack = self.lead.tasks.get(kind='acknowledgement')
        followup = self.lead.tasks.get(kind='follow_up')
        self.assertEqual(ack.due_at, self.lead.acknowledgement_due_at)
        self.assertEqual(followup.due_at, self.lead.next_action_at)
        self.assertEqual(ack.assignee_id, self.owner.pk)
        self.assertGreater(followup.due_at, ack.due_at)

    def test_ack_timeout_reassigns_and_escalates_once(self):
        now = self.overdue_ack()
        self.assertEqual(process_slas(now), 1)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.owner_id, self.manager.pk)
        self.assertEqual(self.lead.routing_attempts, 1)
        self.assertEqual(self.lead.assignment_version, 2)
        self.assertEqual(self.lead.assignment_history.filter(status='escalated').count(), 1)
        self.assertEqual(self.lead.tasks.filter(kind='acknowledgement', status='pending').count(), 1)
        self.assertEqual(self.lead.tasks.filter(kind='escalation').count(), 1)
        process_slas(now)
        self.assertEqual(self.lead.assignment_history.filter(status='escalated').count(), 1)
        self.assertEqual(self.lead.tasks.filter(kind='escalation').count(), 1)

    def test_ack_timeout_without_alternative_falls_back_to_queue(self):
        CounsellorProfile.objects.filter(user=self.manager).update(is_available=False)
        process_slas(self.overdue_ack())
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.owner_id)
        self.assertTrue(self.lead.unassigned_reason)
        self.assertTrue(self.lead.tasks.filter(kind='unassigned').exists())
        self.assertTrue(self.lead.tasks.filter(kind='escalation').exists())

    def test_maximum_reassignments_stop_rotation_and_alert_manager(self):
        RoutingPolicy.objects.filter(branch=self.a).update(max_reassignments=0)
        process_slas(self.overdue_ack())
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.owner_id, self.owner.pk)
        self.assertEqual(self.lead.routing_attempts, 0)
        self.assertEqual(self.lead.assignment_version, 1)
        self.assertEqual(self.lead.tasks.get(kind='acknowledgement').status, 'escalated')
        self.assertEqual(self.lead.tasks.filter(kind='escalation').count(), 1)

    def test_acknowledged_lead_is_not_reassigned_and_closed_tasks_cancel(self):
        acknowledge(lead=self.lead, actor=self.owner)
        process_slas(timezone.now() + timedelta(minutes=20))
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.owner_id, self.owner.pk)
        update_lead(actor=self.owner, lead=self.lead, status='won')
        self.assertFalse(self.lead.tasks.filter(status='pending').exists())

    def test_overdue_followup_escalates_without_changing_owner(self):
        acknowledge(lead=self.lead, actor=self.owner)
        now = timezone.now()
        self.lead.tasks.filter(kind='follow_up').update(due_at=now - timedelta(minutes=1))
        process_slas(now)
        process_slas(now)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.owner_id, self.owner.pk)
        self.assertEqual(self.lead.tasks.get(kind='follow_up').status, 'escalated')
        self.assertEqual(self.lead.tasks.filter(kind='escalation').count(), 1)

    def test_next_action_change_reschedules_existing_task(self):
        deadline = timezone.now() + timedelta(days=1)
        update_lead(actor=self.owner, lead=self.lead, next_action='Demo appointment', next_action_at=deadline)
        task = self.lead.tasks.get(kind='follow_up', status='pending')
        self.assertEqual(task.title, 'Demo appointment')
        self.assertEqual(task.due_at, deadline)
        update_lead(actor=self.owner, lead=self.lead, next_action='', next_action_at=None, no_followup_reason='Student requested no calls')
        task.refresh_from_db()
        self.assertEqual(task.status, 'cancelled')

    def test_obsolete_assignment_tasks_do_not_affect_new_owner(self):
        self.overdue_ack()
        old_ack = self.lead.tasks.get(kind='acknowledgement')
        moved = manual_assign(lead=self.lead, actor=self.manager, owner=self.manager, reason='Coverage')
        old_ack.refresh_from_db()
        self.assertEqual(old_ack.status, 'cancelled')
        process_slas(timezone.now())
        moved.refresh_from_db()
        self.assertEqual(moved.owner_id, self.manager.pk)
        self.assertEqual(moved.assignment_version, 2)

    def test_completing_current_next_action_requires_and_creates_a_new_plan(self):
        task = self.lead.tasks.get(kind='follow_up')
        with self.assertRaises(ValidationError):
            complete_task(actor=self.owner, task=task, resolution='Reached student')
        result = complete_task(actor=self.owner, task=task, resolution='Reached student',
            next_action='Arrange demo', next_action_at=timezone.now() + timedelta(days=1))
        self.assertEqual(result.status, 'completed')
        pending = self.lead.tasks.get(kind='follow_up', status='pending')
        self.assertNotEqual(pending.pk, task.pk)
        self.assertEqual(pending.title, 'Arrange demo')

    def test_reopening_lead_creates_a_fresh_assignment_and_tasks(self):
        acknowledge(lead=self.lead, actor=self.owner)
        update_lead(actor=self.owner, lead=self.lead, status='lost')
        reopened = update_lead(actor=self.manager, lead=self.lead, status='new')
        self.assertEqual(reopened.assignment_version, 2)
        self.assertIsNone(reopened.acknowledged_at)
        self.assertEqual(reopened.tasks.filter(kind='follow_up', status='pending').count(), 1)

    def test_callback_and_appointment_tasks_owner_completion_and_permissions(self):
        for kind in ('callback', 'appointment'):
            task = create_task(actor=self.owner, lead=self.lead, kind=kind, title='Arrange demo', due_at=timezone.now())
            with self.assertRaises(PermissionDenied):
                complete_task(actor=self.other, task=task, resolution='Wrong branch')
            result = complete_task(actor=self.owner, task=task, resolution='Spoke to student')
            self.assertEqual(result.status, 'completed')
            complete_task(actor=self.owner, task=task, resolution='Repeated request')
        self.assertEqual(self.lead.activities.filter(kind='task_completed').count(), 2)

    def test_task_api_cannot_spoof_system_tasks_and_alerts_are_manager_only(self):
        payload = {'lead': str(self.lead.pk), 'kind': 'callback', 'title': 'Missed-call callback', 'due_at': timezone.now().isoformat()}
        response = self.client.post('/api/v1/follow-up-tasks/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        url = '/api/v1/follow-up-tasks/%s/complete/' % response.data['id']
        self.assertEqual(self.client.post(url, {'resolution': 'Reached student'}, format='json').status_code, 200)
        for extra in ({'kind': 'acknowledgement'}, {'assignee': str(self.other.pk)}, {'status': 'completed'}):
            data = dict(payload, **extra)
            self.assertEqual(self.client.post('/api/v1/follow-up-tasks/', data, format='json').status_code, 400)
        CounsellorProfile.objects.filter(user__branch=self.a).update(is_available=False)
        queued = create_lead(actor=self.manager, contact=self.contact, branch=self.a, title='Queued enquiry')
        alert = queued.tasks.get(kind='unassigned')
        self.assertEqual(self.client.get('/api/v1/follow-up-tasks/%s/' % alert.pk).status_code, 404)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.get('/api/v1/follow-up-tasks/%s/' % alert.pk).status_code, 200)

    def test_command_and_celery_wrappers_use_same_services_without_external_sends(self):
        output = StringIO()
        call_command('process_slas', stdout=output)
        self.assertIn('Processed', output.getvalue())
        from .tasks import process_sla_tasks, retry_unassigned_tasks
        with patch('followups.tasks.process_slas', return_value=3) as process:
            self.assertEqual(process_sla_tasks.run(), 3)
            process.assert_called_once_with()
        with patch('followups.tasks.retry_unassigned', return_value=2):
            self.assertEqual(retry_unassigned_tasks.run(), 2)
