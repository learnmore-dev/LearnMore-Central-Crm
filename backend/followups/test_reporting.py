from datetime import timedelta
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from leads.services import create_lead
from calls.models import CallLog
from .models import FollowUpTask, DeadlineMiss
from .reporting import snapshot_deadlines


class FollowUpReportingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.now = timezone.now()
        self.lead = create_lead(actor=self.manager, branch=self.a, contact=self.contact, owner=self.owner,
            title='Python training', next_action='Call student', next_action_at=self.now+timedelta(days=1))
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = '/api/v1/follow-up-report/'

    def task(self, **extra):
        return FollowUpTask.objects.create(lead=self.lead, branch=self.a, assignee=self.owner,
            kind='callback', title='Call student', due_at=self.now-timedelta(hours=2),
            assignment_version=self.lead.assignment_version, dedupe_key='test-'+str(FollowUpTask.objects.count()), **extra)

    def report(self, **params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_personal_is_scoped_and_team_requires_manager(self):
        self.task()
        data = self.report()
        self.assertEqual(data['totals']['overdue'], 1)
        self.assertEqual(len(data['counsellors']), 1)
        self.assertEqual(data['counsellors'][0]['owner'], str(self.owner.pk))
        self.assertEqual(self.client.get(self.url, {'team': 'true'}).status_code, 403)
        self.assertEqual(self.client.get(self.url, {'owner': self.other.pk}).status_code, 403)
        self.assertEqual(self.client.get(self.url, {'branch': self.b.pk}).status_code, 400)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.get(self.url, {'team': 'true', 'owner': self.other.pk}).status_code, 400)

    def test_deadline_survives_completion_and_reassignment_once(self):
        task = self.task()
        task.status, task.completed_at, task.resolution = 'completed', self.now, 'Discussed course'
        task.save()
        snapshot_deadlines()
        self.assertEqual(DeadlineMiss.objects.filter(task_id=task.pk).count(), 1)
        data = self.report(category='completed_late')
        self.assertEqual(data['totals']['completed_late'], 1)
        self.assertEqual(data['totals']['missed_deadline'], 1)
        self.assertEqual(data['results'][0]['resolution'], 'Discussed course')
        FollowUpTask.objects.filter(pk=task.pk).update(assignee=self.manager, status='cancelled')
        self.assertEqual(DeadlineMiss.objects.get(task_id=task.pk).assignee, self.owner)
        data = self.report(category='missed_deadline')
        self.assertEqual(data['totals']['missed_deadline'], 1)
        self.assertEqual(len(data['results']), 1)

    def test_bulk_cancellation_retains_overdue_but_not_future_deadlines(self):
        task = self.task()
        FollowUpTask.objects.filter(lead=self.lead).update(status='cancelled')
        self.assertEqual(list(DeadlineMiss.objects.values_list('task_id', flat=True)), [task.pk])
        self.assertEqual(self.report(category='overdue')['totals']['overdue'], 0)
        self.assertEqual(self.report(category='missed_deadline')['totals']['missed_deadline'], 1)

    def test_no_contact_and_unanswered_calls_are_separate(self):
        self.assertEqual(self.report(category='no_contact')['totals']['no_contact'], 1)
        call = CallLog.objects.create(branch=self.a, contact=self.contact, created_by=self.owner,
            caller_phone='+919876543210', direction='outgoing', status='missed', started_at=timezone.now(),
            client_key='attempt', request_hash='attempt')
        data = self.report(category='unanswered')
        self.assertEqual(data['totals']['no_contact'], 0)
        self.assertEqual(data['totals']['unanswered'], 1)
        call.status = 'answered'
        call.save()
        data = self.report()
        self.assertEqual(data['totals']['no_contact'], 0)
        self.assertEqual(data['totals']['unanswered'], 0)

    def test_reschedule_preserves_original_deadline_and_csv_is_safe(self):
        task = self.task()
        task.title = '=DANGEROUS()'
        task.save()
        task.due_at = self.now+timedelta(days=1)
        task.save()
        data = self.report(category='missed_deadline')
        self.assertEqual(data['totals']['missed_deadline'], 1)
        self.assertEqual(data['totals']['overdue'], 0)
        response = self.client.get(self.url, {'category': 'pending', 'export': 'csv', 'end': timezone.localdate()+timedelta(days=1)})
        self.assertEqual(response.status_code, 200)
        self.assertIn("'=DANGEROUS()", response.content.decode('utf-8-sig'))
        self.assertIn('attachment', response['Content-Disposition'])

    def test_date_validation_and_obsolete_assignments(self):
        self.task()
        self.lead.assignment_version += 1
        self.lead.save()
        self.assertEqual(self.report()['totals']['overdue'], 0)
        self.assertEqual(self.client.get(self.url, {'start': '2020-01-01', 'end': '2026-01-01'}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'start': '2026-02-01', 'end': '2026-01-01'}).status_code, 400)

    def test_other_task_types_preserve_history(self):
        from automation.services import save_rule, enroll
        from automation.models import AutomationTask
        from education.models import Demo, DemoTask
        import uuid
        rule = save_rule(self.manager, dict(branch=self.a, name='Rule', is_active=True))
        run = enroll(rule=rule, lead=self.lead)
        task = AutomationTask.objects.create(run=run, branch=self.a, assignee=self.owner,
            title='Counselling callback', due_at=self.now-timedelta(hours=1))
        AutomationTask.objects.filter(pk=task.pk).update(status='cancelled')
        demo = Demo.objects.create(lead=self.lead, branch=self.a, course='Python', mode='online', location='Online',
            starts_at=self.now, client_key=uuid.uuid4(), request_hash='test', created_by=self.manager)
        demo_task = DemoTask.objects.create(demo=demo, version=1, kind='attendance', assignee=self.owner,
            due_at=self.now-timedelta(minutes=30))
        DemoTask.objects.filter(pk=demo_task.pk).update(assignee=self.manager, status='cancelled')
        data = self.report(category='missed_deadline')
        self.assertEqual(data['totals']['missed_deadline'], 2)
        self.assertEqual({r['origin'] for r in data['results']}, {'education', 'automation'})

    def test_transferred_enquiry_history_has_no_cross_branch_link(self):
        task = self.task()
        FollowUpTask.objects.filter(pk=task.pk).update(status='cancelled')
        self.lead.branch = self.b
        self.lead.owner = self.other
        self.lead.save()
        data = self.report(category='missed_deadline')
        self.assertEqual(data['results'][0]['target'], '')
