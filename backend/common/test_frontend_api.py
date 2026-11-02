from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from contacts.models import Contact
from followups.models import FollowUpTask
from leads.services import create_lead
from .test_utils import crm_fixtures


class FrontendAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.lead = create_lead(actor=self.manager, branch=self.a, contact=self.contact, title='Visible enquiry')
        hidden = Contact.objects.create(full_name='Hidden student', branch=self.b)
        self.hidden = create_lead(actor=self.management, branch=self.b, contact=hidden, title='Private enquiry')
        FollowUpTask.objects.filter(lead=self.lead, kind='follow_up').update(due_at=timezone.now() - timedelta(hours=1))
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_dashboard_is_scoped_and_selected_branch_cannot_expand_scope(self):
        response = self.client.get('/api/v1/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store, private')
        self.assertEqual(response.data['contacts'], 1)
        self.assertEqual(response.data['active_leads'], 1)
        self.assertEqual(response.data['overdue_tasks'], 1)
        self.assertEqual(len(response.data['branches']), 1)
        self.assertNotIn('Hidden student', str(response.data))
        self.assertNotIn('Private enquiry', str(response.data))
        self.assertEqual(self.client.get('/api/v1/dashboard/?branch=%s' % self.b.pk).status_code, 400)
        self.assertEqual(self.client.get('/api/v1/dashboard/?branch=invalid').status_code, 400)

    def test_management_dashboard_has_all_totals_and_branch_filter(self):
        self.client.force_authenticate(self.management)
        self.assertEqual(self.client.get('/api/v1/dashboard/').data['active_leads'], 2)
        response = self.client.get('/api/v1/dashboard/?branch=%s' % self.b.pk)
        self.assertEqual(response.data['contacts'], 1)
        self.assertEqual(response.data['active_leads'], 1)
        self.assertEqual(response.data['overdue_tasks'], 0)

    def test_support_dashboard_does_not_leak_manager_task_counts(self):
        support = get_user_model().objects.create_user(username='reader', branch=self.a, role='support')
        self.client.force_authenticate(support)
        response = self.client.get('/api/v1/dashboard/')
        self.assertEqual(response.data['active_leads'], 1)
        self.assertEqual(response.data['overdue_tasks'], 0)

    def test_employee_directory_is_scoped_readonly_and_contains_no_credentials(self):
        response = self.client.get('/api/v1/employees/')
        self.assertEqual(response.data['count'], 2)
        ids = {str(row['id']) for row in response.data['results']}
        self.assertNotIn(str(self.other.pk), ids)
        for row in response.data['results']:
            self.assertNotIn('password', row)
            self.assertNotIn('email', row)
        self.assertEqual(self.client.post('/api/v1/employees/', {}, format='json').status_code, 405)

    def test_capabilities_respect_actual_superuser_privileges(self):
        admin = get_user_model().objects.create_superuser(username='admin', password='synthetic-test-password')
        self.client.force_authenticate(admin)
        capabilities = self.client.get('/api/v1/auth/me/').data['capabilities']
        self.assertTrue(capabilities['global_scope'])
        self.assertTrue(capabilities['manage_branches'])
        self.client.force_authenticate(self.owner)
        capabilities = self.client.get('/api/v1/auth/me/').data['capabilities']
        self.assertFalse(capabilities['manage_branches'])
        self.assertFalse(capabilities['manage_routing'])

    def test_readable_labels_and_edit_flags_do_not_grant_write_privileges(self):
        lead = self.client.get('/api/v1/leads/%s/' % self.lead.pk).data
        self.assertEqual(lead['contact_name'], self.contact.full_name)
        self.assertEqual(lead['owner_name'], self.owner.username)
        self.assertTrue(lead['can_edit'])
        self.assertEqual(self.client.patch('/api/v1/leads/%s/' % self.lead.pk, {'can_edit': True}, format='json').status_code, 400)
        self.assertEqual(self.client.patch('/api/v1/branches/%s/' % self.a.pk, {'name': 'Unauthorized'}, format='json').status_code, 403)
        self.client.force_authenticate(self.manager)
        lead = create_lead(actor=self.manager, branch=self.a, contact=Contact.objects.create(full_name='Another', branch=self.a), title='Manager enquiry', owner=self.manager)
        self.client.force_authenticate(self.owner)
        detail = self.client.get('/api/v1/leads/%s/' % lead.pk).data
        self.assertFalse(detail['can_edit'])
        self.assertEqual(self.client.patch('/api/v1/leads/%s/' % lead.pk, {'title': 'Hijacked'}, format='json').status_code, 403)

    def test_anonymous_cannot_read_dashboard_or_directory(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/v1/dashboard/').status_code, 403)
        self.assertEqual(self.client.get('/api/v1/employees/').status_code, 403)
