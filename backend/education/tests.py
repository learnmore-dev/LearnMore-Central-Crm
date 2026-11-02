from datetime import timedelta
from unittest.mock import patch
import uuid
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError, PermissionDenied
from common.test_utils import crm_fixtures
from leads.models import Lead
from leads.services import create_lead
from contacts.models import Contact
from messaging.models import Channel, Conversation, Message
from .models import Qualification, Demo, DemoTask, JobHealth
from .services import book_demo, change_demo, complete_demo_task, process_demos, save_qualification
from .jobs import run_cycle


class EducationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.lead = create_lead(actor=self.manager, branch=self.a, contact=self.contact, owner=self.owner, title='Python')
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def book(self, lead=None, **extra):
        data = {'course': 'Python', 'mode': 'classroom', 'location': 'Marathahalli', 'starts_at': timezone.now()+timedelta(days=2), 'duration_minutes': 60, 'client_key': uuid.uuid4()}
        data.update(extra)
        return book_demo(self.manager, lead or self.lead, **data)

    def test_qualification_defaults_and_partial_update_preserve_values(self):
        path = f'/api/v1/education/qualifications/{self.lead.pk}/'
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['missing_fields']), 4)
        self.assertFalse(Qualification.objects.exists())
        response = self.client.patch(path, {'course_interest': 'Python', 'background': 'working', 'training_mode': 'online', 'joining_timeline': 'month'}, format='json')
        self.assertEqual(response.data['missing_fields'], [])
        self.client.patch(path, {'notes': 'Prefers weekend'}, format='json')
        item = Qualification.objects.get()
        self.assertEqual(item.course_interest, 'Python')
        self.assertEqual(item.notes, 'Prefers weekend')
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'new')
        self.assertEqual(self.lead.activities.filter(body__startswith='Student qualification updated').count(), 2)

    def test_qualification_permissions_choices_and_spoofed_fields(self):
        path = f'/api/v1/education/qualifications/{self.lead.pk}/'
        for data in ({'training_mode': 'invalid'}, {'lead': str(self.lead.pk)}, {'updated_by': str(self.owner.pk)}):
            self.assertEqual(self.client.patch(path, data, format='json').status_code, 400)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(path).status_code, 404)
        with self.assertRaises(PermissionDenied):
            save_qualification(self.other, self.lead, {'notes': 'Forbidden'})
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.patch(path, {'readiness': 'demo_ready'}, format='json').status_code, 200)

    def test_booking_idempotency_and_no_outbound_messages(self):
        key = uuid.uuid4()
        start = timezone.now()+timedelta(days=2)
        first = self.book(client_key=key, starts_at=start)
        same = self.book(client_key=key, starts_at=start)
        self.assertEqual(first.pk, same.pk)
        self.assertEqual(first.tasks.count(), 2)
        self.assertEqual(first.tasks.get(kind='reminder').due_at, start-timedelta(hours=1))
        self.assertEqual(first.tasks.get(kind='attendance').due_at, start+timedelta(hours=1))
        self.assertEqual(Message.objects.count(), 0)
        with self.assertRaises(ValidationError):
            self.book(client_key=key, starts_at=start, course='Different')
        with self.assertRaises(ValidationError):
            self.book()

    def test_past_invalid_duration_and_read_only_input_rejected(self):
        data = {'lead': str(self.lead.pk), 'course': 'Python', 'mode': 'online', 'location': 'Meeting link', 'starts_at': (timezone.now()+timedelta(days=2)).isoformat(), 'duration_minutes': 60, 'client_key': str(uuid.uuid4())}
        for extra in ({'starts_at': timezone.now().isoformat()}, {'duration_minutes': 200}, {'status': 'attended'}, {'created_by': str(self.manager.pk)}, {'location': ''}):
            response = self.client.post('/api/v1/education/demos/', {**data, **extra}, format='json')
            self.assertEqual(response.status_code, 400)
        self.assertEqual(Demo.objects.count(), 0)

    def test_booking_conflicts_with_same_counsellor_but_allows_adjacent(self):
        first = self.book()
        contact = Contact.objects.create(branch=self.a, full_name='Second Student')
        other_lead = create_lead(actor=self.manager, branch=self.a, contact=contact, owner=self.owner, title='Java')
        with self.assertRaises(ValidationError):
            self.book(lead=other_lead, starts_at=first.starts_at+timedelta(minutes=30))
        self.book(lead=other_lead, starts_at=first.starts_at+timedelta(minutes=60))
        self.assertEqual(Demo.objects.count(), 2)

    def test_reschedule_cancels_old_tasks_and_creates_new_revision_once(self):
        demo = self.book()
        old_ids = list(demo.tasks.values_list('pk', flat=True))
        new_time = demo.starts_at+timedelta(days=1)
        changed = change_demo(self.owner, demo, action='reschedule', version=1, reason='Student requested weekend', starts_at=new_time)
        self.assertEqual(changed.version, 2)
        self.assertEqual(DemoTask.objects.filter(pk__in=old_ids, status='cancelled').count(), 2)
        self.assertEqual(demo.tasks.filter(status='pending').count(), 2)
        process_demos()
        process_demos()
        self.assertEqual(demo.tasks.count(), 4)
        with self.assertRaises(ValidationError):
            change_demo(self.owner, demo, action='cancelled', version=1, reason='Stale browser')

    def test_attendance_cannot_be_guessed_before_demo_and_no_show_follows_up(self):
        demo = self.book()
        with self.assertRaises(ValidationError):
            change_demo(self.owner, demo, action='no_show', version=1, reason='Not here')
        Demo.objects.filter(pk=demo.pk).update(starts_at=timezone.now()-timedelta(hours=2))
        changed = change_demo(self.owner, demo, action='no_show', version=1, reason='Student did not join')
        self.assertEqual(changed.status, 'no_show')
        self.assertEqual(demo.tasks.filter(status='pending', kind='no_show_followup').count(), 1)
        process_demos()
        self.assertEqual(demo.tasks.filter(kind='no_show_followup').count(), 1)

    def test_attended_demo_creates_admission_discussion_without_winning_lead(self):
        demo = self.book()
        Demo.objects.filter(pk=demo.pk).update(starts_at=timezone.now()-timedelta(hours=2))
        change_demo(self.owner, demo, action='attended', version=1, reason='Interested in weekend batch')
        self.assertEqual(demo.tasks.filter(status='pending', kind='attended_followup').count(), 1)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'new')

    def test_cancel_closure_and_transfer_cancel_pending_work(self):
        demo = self.book()
        change_demo(self.owner, demo, action='cancelled', version=1, reason='Requested cancellation')
        self.assertFalse(demo.tasks.filter(status='pending').exists())
        for changes in ({'status': 'lost'}, {'branch': self.b}):
            lead = create_lead(actor=self.manager, branch=self.a, contact=self.contact, owner=self.owner, title='New demo')
            item = self.book(lead=lead, starts_at=timezone.now()+timedelta(days=3+Demo.objects.count()))
            Lead.objects.filter(pk=lead.pk).update(**changes)
            process_demos()
            item.refresh_from_db()
            self.assertEqual(item.status, 'cancelled')
            self.assertFalse(item.tasks.filter(status='pending').exists())

    def test_reassignment_follows_current_owner_and_stale_owner_loses_access(self):
        demo = self.book()
        Lead.objects.filter(pk=self.lead.pk).update(owner=self.manager)
        process_demos()
        self.assertTrue(all(t.assignee_id == self.manager.pk for t in demo.tasks.all()))
        self.assertEqual(self.client.get('/api/v1/education/demos/').data['count'], 0)
        with self.assertRaises(PermissionDenied):
            complete_demo_task(self.owner, demo.tasks.get(kind='reminder'), 'Called')

    def test_tasks_require_outcome_and_attendance_uses_demo_action(self):
        demo = self.book()
        task = demo.tasks.get(kind='reminder')
        path = f'/api/v1/education/tasks/{task.pk}/complete/'
        self.assertEqual(self.client.post(path, {'resolution': ''}, format='json').status_code, 400)
        self.assertEqual(self.client.post(path, {'resolution': 'Student confirmed'}, format='json').status_code, 200)
        self.assertEqual(self.client.post(path, {'resolution': 'Student confirmed'}, format='json').status_code, 200)
        attendance = demo.tasks.get(kind='attendance')
        self.assertEqual(self.client.post(f'/api/v1/education/tasks/{attendance.pk}/complete/', {'resolution': 'Guessed'}, format='json').status_code, 400)
        self.assertEqual(self.lead.activities.filter(body__startswith='Demo task completed').count(), 1)

    def test_monitor_is_manager_only_scoped_and_uses_actual_counts(self):
        self.book()
        self.assertEqual(self.client.get('/api/v1/education/attention/').status_code, 403)
        self.client.force_authenticate(self.manager)
        response = self.client.get('/api/v1/education/attention/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['counts']['qualification_needed'], 1)
        self.assertEqual(response.data['source_results'][0]['demo_booked'], 1)
        self.assertIsNone(response.data['job'])
        self.assertEqual(self.client.get(f'/api/v1/education/attention/?branch={self.b.pk}').status_code, 400)
        self.client.force_authenticate(self.other)
        for path in ('demos', 'tasks'):
            self.assertEqual(self.client.get(f'/api/v1/education/{path}/').data['count'], 0)

    def test_monitor_whatsapp_reply_and_failed_message_counts_are_branch_scoped(self):
        channel = Channel.objects.create(branch=self.a, name='Test', phone_number_id='education-test', waba_id='test')
        chat = Conversation.objects.create(channel=channel, wa_id='919876543210', last_inbound_at=timezone.now())
        Message.objects.create(conversation=chat, direction='inbound', text='Interested', mode='mock')
        Message.objects.create(conversation=chat, direction='outbound', text='Failed', mode='mock', queue_status='failed')
        self.client.force_authenticate(self.manager)
        response = self.client.get('/api/v1/education/attention/')
        self.assertEqual(response.data['counts']['awaiting_reply'], 1)
        self.assertEqual(response.data['counts']['failed_messages'], 1)
        self.client.force_authenticate(self.management)
        response = self.client.get(f'/api/v1/education/attention/?branch={self.b.pk}')
        self.assertEqual(response.data['counts']['awaiting_reply'], 0)
        self.assertEqual(response.data['counts']['failed_messages'], 0)

    def test_worker_failures_are_durable_redacted_and_retried(self):
        with patch('education.jobs.process_automations', side_effect=RuntimeError('private payload')), patch('education.jobs.process_demos', return_value=0) as demos:
            result = run_cycle()
        self.assertEqual(result['status'], 'retry_pending')
        demos.assert_called_once()
        health = JobHealth.objects.get()
        self.assertEqual(health.error_code, 'automation:RuntimeError')
        self.assertEqual(health.consecutive_failures, 1)
        self.assertIsNone(health.last_success_at)
        result = run_cycle()
        health.refresh_from_db()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(health.consecutive_failures, 0)
        self.assertIsNotNone(health.last_success_at)
