from io import StringIO
from datetime import timedelta
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from leads.services import create_lead
from messaging.models import Message
from .models import AutomationRule, AutomationRun
from .presets import PRESETS, COURSE_OPTIONS, install_starter_rules
from .services import discover, process_run, save_rule


class StarterRuleTests(TestCase):
    def setUp(self):
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def install(self, **body):
        return self.client.post('/api/v1/automation/rules/install-starters/', {'branch': str(self.a.pk), **body}, format='json')

    def test_library_exposes_five_valid_presets_and_course_options(self):
        response = self.client.get('/api/v1/automation/rules/templates/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['templates']), 5)
        self.assertIn('Python Full Stack Development', response.data['courses'])
        self.assertIn('Power BI', response.data['courses'])
        self.assertEqual(len(set(item['source'] for item in response.data['templates'])), 5)
        result = self.install()
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data['created'], 5)
        self.assertFalse(AutomationRule.objects.filter(is_active=True).exists())
        self.assertEqual(AutomationRun.objects.count(), 0)

    def test_install_is_idempotent_and_keeps_customized_content(self):
        self.install()
        rule = AutomationRule.objects.get(branch=self.a, source='website')
        rule.acknowledgement_text = 'Custom website welcome'
        rule.save()
        result = self.install()
        self.assertEqual(result.data['created'], 0)
        self.assertEqual(result.data['preserved'], 5)
        self.assertEqual(AutomationRule.objects.count(), 5)
        rule.refresh_from_db()
        self.assertEqual(rule.acknowledgement_text, 'Custom website welcome')

    def test_install_can_enable_new_arrivals_and_does_not_enroll_history(self):
        old = create_lead(actor=self.manager, branch=self.a, contact=self.contact, title='Java', owner=self.owner,
                          next_action='Call', next_action_at=timezone.now(), source='website')
        result = self.install(enable=True)
        self.assertEqual(result.data['enabled'], 5)
        self.assertTrue(all(rule.enabled_at for rule in AutomationRule.objects.all()))
        new = create_lead(actor=self.manager, branch=self.a, contact=self.contact, title='Python', owner=self.owner,
                          next_action='Call', next_action_at=timezone.now(), source='website')
        discover()
        self.assertFalse(AutomationRun.objects.filter(lead=old).exists())
        run = AutomationRun.objects.get(lead=new)
        self.assertEqual(run.rule.source, 'website')
        self.assertEqual(AutomationRun.objects.count(), 1)
        self.assertEqual(self.install(enable=True).data['enabled'], 0)

    def test_active_custom_rules_are_preserved(self):
        custom = save_rule(self.manager, {'branch': self.a, 'name': 'Custom website', 'source': 'website', 'is_active': True})
        result = self.install(enable=True)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data['enabled'], 4)
        self.assertEqual(result.data['conflicts'], ['website'])
        self.assertEqual(AutomationRule.objects.get(branch=self.a, source='website', is_active=True).pk, custom.pk)
        self.assertFalse(AutomationRule.objects.get(branch=self.a, name=PRESETS[1]['name']).is_active)

    def test_install_requires_manager_and_rejects_cross_branch_or_inactive_branch(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.install().status_code, 403)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.install(branch=str(self.b.pk)).status_code, 400)
        self.a.is_active = False
        self.a.save()
        self.assertEqual(self.install().status_code, 400)
        self.assertEqual(AutomationRule.objects.count(), 0)

    def test_global_manager_can_install_another_branch(self):
        self.client.force_authenticate(self.management)
        result = self.install(branch=str(self.b.pk))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(AutomationRule.objects.filter(branch=self.b).count(), 5)
        self.assertEqual(AutomationRule.objects.filter(branch=self.a).count(), 0)

    def test_general_course_rule_creates_work_and_previews_courses_without_sending(self):
        result = install_starter_rules(actor=self.manager, branch=self.a, enable=True, source='all')
        rule = result['rules'][0]
        lead = create_lead(actor=self.manager, branch=self.a, contact=self.contact, title='Python', owner=self.owner,
                           next_action='Call', next_action_at=timezone.now())
        discover()
        run = AutomationRun.objects.get(lead=lead)
        with patch('messaging.services.dispatch_outbox') as dispatch:
            # Choose a working hour so the initial acknowledgement is due.
            now = timezone.localtime(timezone.now()) + timedelta(days=1)
            while now.weekday() == 6:
                now += timedelta(days=1)
            now = now.replace(hour=11, minute=0, second=0, microsecond=0)
            run.scheduled_steps.filter(kind='message').update(due_at=now)
            process_run(run.pk, now=now)
        dispatch.assert_not_called()
        self.assertEqual(Message.objects.count(), 0)
        self.assertTrue(run.work_items.filter(assignee=self.owner).exists())
        preview = run.events.filter(code='message_simulated').first().detail
        self.assertIn('LearnMore Technologies', preview)
        self.assertIn(COURSE_OPTIONS[0], preview)
        self.assertNotIn('{name}', preview)
        self.assertIn('NOT SENT', preview)
        self.assertEqual(rule.source, 'all')

    def test_seed_command_reuses_installation_and_preserves_drafts(self):
        output = StringIO()
        call_command('seed_learnmore_rules', actor=self.manager.username, source='all', stdout=output)
        self.assertEqual(AutomationRule.objects.count(), 1)
        self.assertFalse(AutomationRule.objects.get().is_active)
        call_command('seed_learnmore_rules', actor=self.manager.username, source='all', enable=True, stdout=output)
        self.assertEqual(AutomationRule.objects.count(), 1)
        self.assertTrue(AutomationRule.objects.get().is_active)
