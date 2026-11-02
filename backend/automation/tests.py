from datetime import timedelta
from unittest.mock import patch
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from contacts.models import ContactIdentifier
from leads.models import Lead
from leads.services import create_lead
from calls.models import CallLog
from messaging.models import Channel, Conversation, Message
from .models import AutomationRule, AutomationRun, AutomationStep, AutomationTask, AutomationEvent
from .services import save_rule, enroll, process_run, process_automations, control_run, complete_task, business_time


class AutomationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        ContactIdentifier.objects.create(contact=self.contact, kind='phone', value='+919876543210')
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.rule = save_rule(self.manager, {'branch': self.a, 'name': 'Test rule', 'is_active': True,
            'business_hours': False, 'acknowledgement_minutes': 0, 'steps': []})

    def lead(self, **extra):
        return create_lead(actor=self.manager, branch=self.a, contact=self.contact, title='Python',
            owner=self.owner, next_action='Call', next_action_at=timezone.now(), **extra)

    def chat(self):
        channel = Channel.objects.create(branch=self.a, name='Test', phone_number_id='test', waba_id='test')
        chat = Conversation.objects.create(channel=channel, contact=self.contact, wa_id='919876543210')
        Message.objects.create(conversation=chat, direction='inbound', text='Interested', mode='mock')
        return chat

    def test_processing_is_idempotent_and_never_queues_a_message(self):
        lead = self.lead()
        run = enroll(rule=self.rule, lead=lead)
        self.assertEqual(enroll(rule=self.rule, lead=lead).pk, run.pk)
        with patch('messaging.services.dispatch_outbox') as dispatch:
            process_run(run.pk)
            process_run(run.pk)
        dispatch.assert_not_called()
        self.assertEqual(run.events.filter(code='message_simulated').count(), 1)
        self.assertIn('NOT SENT', run.events.get(code='message_simulated').detail)
        self.assertEqual(run.work_items.count(), 1)
        self.assertEqual(Message.objects.count(), 0)
        lead.refresh_from_db()
        self.assertEqual(lead.status, 'new')
        self.assertIsNone(lead.acknowledged_at)
        run.refresh_from_db()
        self.assertEqual(run.state, 'active')  # Open callback still needs monitoring.

    def test_new_arrivals_only_and_specific_source_priority(self):
        historic = self.lead()
        Lead.objects.filter(pk=historic.pk).update(created_at=timezone.now()-timedelta(days=2))
        exact = save_rule(self.manager, {'branch': self.a, 'name': 'Website', 'source': 'website', 'is_active': True, 'business_hours': False})
        website = self.lead(source='website')
        manual = self.lead()
        process_automations()
        self.assertFalse(AutomationRun.objects.filter(lead=historic).exists())
        self.assertEqual(AutomationRun.objects.get(lead=website).rule_id, exact.pk)
        self.assertEqual(AutomationRun.objects.get(lead=manual).rule_id, self.rule.pk)

    def test_disabled_rules_do_not_enroll(self):
        save_rule(self.manager, {'is_active': False}, self.rule)
        self.lead()
        process_automations()
        self.assertEqual(AutomationRun.objects.count(), 0)

    def test_blank_acknowledgement_can_be_saved_and_skips_simulation(self):
        response = self.client.patch(f'/api/v1/automation/rules/{self.rule.pk}/', {'acknowledgement_text': ''}, format='json')
        self.assertEqual(response.status_code, 200)
        self.rule.refresh_from_db()
        run = enroll(rule=self.rule, lead=self.lead())
        process_run(run.pk)
        self.assertFalse(run.events.filter(code='message_simulated').exists())

    def test_missed_call_gets_callback_only_and_stops_when_converted(self):
        call = CallLog.objects.create(branch=self.a, client_key='test', caller_phone='+919876543210',
            status='missed', started_at=timezone.now(), created_by=self.manager)
        run = enroll(rule=self.rule, call=call)
        process_run(run.pk)
        self.assertEqual(run.scheduled_steps.count(), 1)
        self.assertEqual(run.work_items.get().title, 'Callback missed caller')
        call.lead = self.lead()
        call.save()
        process_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.state, 'stopped')
        self.assertEqual(run.work_items.get().status, 'cancelled')

    def test_reply_pauses_and_creates_one_handoff(self):
        chat = self.chat()
        run = enroll(rule=self.rule, conversation=chat)
        process_run(run.pk)
        Message.objects.create(conversation=chat, direction='inbound', text='Can you call?', mode='mock')
        process_run(run.pk)
        process_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.state, 'paused')
        self.assertEqual(run.work_items.filter(status='pending').count(), 1)
        self.assertEqual(run.events.filter(code='paused').count(), 1)

    def test_staff_takeover_pauses(self):
        chat = self.chat()
        run = enroll(rule=self.rule, conversation=chat)
        Message.objects.create(conversation=chat, direction='outbound', text='Hello', mode='mock', created_by=self.owner)
        process_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.state, 'paused')

    def test_missed_call_assignment_stays_stable_and_resume_restores_callback(self):
        call = CallLog.objects.create(branch=self.a, client_key='stable', caller_phone='+919876543210',
            status='missed', started_at=timezone.now(), created_by=self.manager)
        run = enroll(rule=self.rule, call=call)
        process_run(run.pk)
        task = run.work_items.get()
        first_owner = task.assignee_id
        process_run(run.pk)
        task.refresh_from_db()
        self.assertEqual(task.assignee_id, first_owner)
        control_run(actor=self.manager, run=run, action='pause', reason='Review')
        task.refresh_from_db()
        self.assertEqual(task.status, 'cancelled')
        control_run(actor=self.manager, run=run, action='resume', reason='Continue')
        task.refresh_from_db()
        self.assertEqual(task.status, 'pending')

    def test_optout_stops_even_a_paused_disabled_rule(self):
        chat = self.chat()
        run = enroll(rule=self.rule, conversation=chat)
        control_run(actor=self.manager, run=run, action='pause', reason='Review')
        save_rule(self.manager, {'is_active': False}, self.rule)
        chat.consent = 'revoked'
        chat.save()
        process_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.state, 'stopped')
        self.assertFalse(run.scheduled_steps.filter(status='pending').exists())

    def test_closed_or_transferred_leads_stop_tasks(self):
        for changes in ({'status': 'lost'}, {'branch': self.b}):
            lead = self.lead()
            run = enroll(rule=self.rule, lead=lead)
            process_run(run.pk)
            Lead.objects.filter(pk=lead.pk).update(**changes)
            process_run(run.pk)
            run.refresh_from_db()
            self.assertEqual(run.state, 'stopped')
            self.assertEqual(run.work_items.get().status, 'cancelled')

    def test_rule_snapshot_and_resume_shift_pending_steps(self):
        rule = save_rule(self.manager, {'steps': [{'kind': 'message', 'title': 'Later', 'body': 'Original', 'delay_minutes': 1440}]}, self.rule)
        run = enroll(rule=rule, lead=self.lead())
        save_rule(self.manager, {'steps': []}, rule)
        control_run(actor=self.manager, run=run, action='pause', reason='Review')
        AutomationRun.objects.filter(pk=run.pk).update(paused_at=timezone.now()-timedelta(hours=1))
        before = run.scheduled_steps.get(title='Later').due_at
        control_run(actor=self.manager, run=run, action='resume', reason='Approved follow-up')
        self.assertGreater(run.scheduled_steps.get(title='Later').due_at, before+timedelta(minutes=59))
        self.assertEqual(run.snapshot['steps'][0]['body'], 'Original')
        with self.assertRaises(PermissionDenied):
            control_run(actor=self.owner, run=run, action='resume', reason='No')

    def test_overdue_escalates_once_and_outcome_completes(self):
        run = enroll(rule=self.rule, lead=self.lead())
        process_run(run.pk)
        task = run.work_items.get()
        AutomationTask.objects.filter(pk=task.pk).update(due_at=timezone.now()-timedelta(minutes=1))
        process_automations()
        process_automations()
        self.assertEqual(run.events.filter(code='task_overdue').count(), 1)
        complete_task(actor=self.owner, task=task, resolution='Spoke to student')
        complete_task(actor=self.owner, task=task, resolution='Spoke to student')
        process_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.state, 'completed')
        self.assertEqual(run.events.filter(code='task_completed').count(), 1)

    def test_worker_updates_owner_and_completion_checks_current_owner(self):
        lead = self.lead()
        run = enroll(rule=self.rule, lead=lead)
        process_run(run.pk)
        task = run.work_items.get()
        Lead.objects.filter(pk=lead.pk).update(owner=self.manager)
        with self.assertRaises(PermissionDenied):
            complete_task(actor=self.owner, task=task, resolution='Stale owner')
        process_run(run.pk)
        task.refresh_from_db()
        self.assertEqual(task.assignee_id, self.manager.pk)

    def test_daily_cap_defers_third_simulation(self):
        run = enroll(rule=self.rule, lead=self.lead())
        for i in range(2):
            AutomationStep.objects.create(run=run, position=i+10, kind='message', title='Extra', body='Hello', due_at=timezone.now())
        process_run(run.pk)
        self.assertEqual(run.events.filter(code='message_simulated').count(), 2)
        self.assertEqual(run.events.filter(code='frequency_limit').count(), 1)
        self.assertEqual(run.scheduled_steps.filter(status='pending').count(), 1)

    def test_business_hours_skip_sunday(self):
        sunday = timezone.make_aware(timezone.datetime(2026, 10, 25, 20))
        due = business_time(sunday, {'business_hours': True, 'start_hour': 9, 'end_hour': 18})
        self.assertEqual(timezone.localtime(due).weekday(), 0)
        self.assertEqual(timezone.localtime(due).hour, 9)

    def test_api_permissions_scope_and_validation(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post('/api/v1/automation/rules/', {'branch': str(self.a.pk), 'name': 'Forbidden'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.client.force_authenticate(self.manager)
        for data in ({'start_hour': 18, 'end_hour': 9}, {'steps': [{'kind': 'message', 'title': 'Bad', 'body': '', 'delay_minutes': 1}]}, {'steps': [{'kind': 'task', 'title': 'Bad', 'delay_minutes': -1}]}, {'acknowledgement_text': '{password}'}, {'branch': str(self.b.pk)}, {'created_by': str(self.owner.pk)}):
            with self.subTest(data=data):
                response = self.client.patch(f'/api/v1/automation/rules/{self.rule.pk}/', data, format='json')
                self.assertEqual(response.status_code, 400)
        run = enroll(rule=self.rule, lead=self.lead())
        process_run(run.pk)
        self.client.force_authenticate(self.other)
        for path in ('rules', 'runs', 'work', 'audit'):
            response = self.client.get(f'/api/v1/automation/{path}/?team=true')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], 0)
        self.assertEqual(self.client.post(f'/api/v1/automation/runs/{run.pk}/control/', {'action': 'stop', 'reason': 'Cross branch'}, format='json').status_code, 404)

    def test_active_scope_uniqueness_and_branch_immutability(self):
        with self.assertRaises(ValidationError):
            save_rule(self.manager, {'branch': self.a, 'name': 'Duplicate', 'is_active': True})
        with self.assertRaises(ValidationError):
            save_rule(self.management, {'branch': self.b}, self.rule)

    def test_unassigned_callback_visible_in_manager_team_queue(self):
        from routing.models import CounsellorProfile
        CounsellorProfile.objects.filter(user__branch=self.a).update(is_available=False)
        call = CallLog.objects.create(branch=self.a, client_key='unassigned', caller_phone='+919876543210',
            status='missed', started_at=timezone.now(), created_by=self.manager)
        run = enroll(rule=self.rule, call=call)
        process_run(run.pk)
        self.assertIsNone(run.work_items.get().assignee_id)
        response = self.client.get('/api/v1/automation/work/?team=true')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['assignee_name'], 'Manager queue')
