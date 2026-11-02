from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from leads.services import create_lead
from routing.models import CounsellorProfile
from .models import User, UserAccessEvent


class EmployeeAdministrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.admin = User.objects.create_user(username='crm-admin', role='super_admin', password='River!Orchid!Window!2026')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = '/api/v1/admin/employees/'

    def data(self, **extra):
        return dict(username='new-counsellor', first_name='Asha', last_name='K', email='asha@example.com', role='counsellor',
            branch=str(self.a.pk), password='Meadow!Window!Velvet!2026', **extra)

    def test_admin_creates_hashed_account_and_opt_in_routing(self):
        response = self.client.post(self.url, self.data(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(username='new-counsellor')
        self.assertTrue(user.check_password('Meadow!Window!Velvet!2026'))
        self.assertNotIn('password', response.data)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.counsellor_profile.can_receive_leads)
        event = UserAccessEvent.objects.get(target=user)
        self.assertNotIn('Meadow', str(event.detail))
        self.assertEqual(event.actor, self.admin)
        response = self.client.patch(f'{self.url}{user.pk}/', {'can_receive_leads': True, 'max_active_leads': 12}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['routing_enabled'])
        self.assertEqual(response.data['capacity'], 12)

    def test_non_admins_cannot_list_create_reset_or_view_audit(self):
        intern = User.objects.create_user(username='intern', branch=self.a, role='intern')
        for user in [self.owner, self.manager, self.other, self.management, intern]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url, self.data(), format='json').status_code, 403)
            self.assertEqual(self.client.post(f'{self.url}{self.owner.pk}/reset-password/', {'password': 'Meadow!Window!Velvet!2026'}, format='json').status_code, 403)
            self.assertEqual(self.client.get('/api/v1/admin/access-events/').status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_password_validation_username_collision_and_permission_flags(self):
        for patch in [{'password': 'short'}, {'branch': None}, {'is_superuser': True}, {'is_staff': True}, {'groups': []}, {'user_permissions': []}]:
            response = self.client.post(self.url, {**self.data(), **patch}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        response = self.client.post(self.url, {**self.data(), 'username': self.owner.username.upper()}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(UserAccessEvent.objects.count(), 0)

    def test_intern_is_branch_scoped_read_only_and_cannot_receive_enquiries(self):
        response = self.client.post(self.url, {**self.data(), 'role': 'intern'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(pk=response.data['id'])
        self.assertFalse(CounsellorProfile.objects.filter(user=user).exists())
        self.client.force_authenticate(user)
        self.assertFalse(self.client.get('/api/v1/auth/me/').data['capabilities']['sales_write'])
        self.assertFalse(self.client.get('/api/v1/auth/me/').data['capabilities']['manage_users'])
        self.assertEqual(self.client.get('/api/v1/branches/').data['count'], 1)
        self.assertEqual(self.client.post('/api/v1/leads/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.get('/api/v1/whatsapp/conversations/').status_code, 403)
        self.assertEqual(self.client.get(f'/api/v1/contacts/{self.contact.pk}/history/', {'source': 'whatsapp'}).status_code, 403)

    def test_active_enquiries_block_deactivation_branch_change_or_sales_demotion(self):
        create_lead(actor=self.manager, branch=self.a, contact=self.contact, owner=self.owner, title='Python')
        for change in [{'is_active': False}, {'branch': str(self.b.pk)}, {'role': 'intern'}]:
            response = self.client.patch(f'{self.url}{self.owner.pk}/', change, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn('Reassign', str(response.data))
        self.assertEqual(UserAccessEvent.objects.count(), 0)

    def test_self_lockout_and_protected_system_account_changes_are_blocked(self):
        for change in [{'is_active': False}, {'role': 'intern', 'branch': str(self.a.pk)}]:
            self.assertEqual(self.client.patch(f'{self.url}{self.admin.pk}/', change, format='json').status_code, 400)
        system = User.objects.create_superuser(username='system', password='Strong!Window!Lake!2026')
        self.assertEqual(self.client.patch(f'{self.url}{system.pk}/', {'first_name': 'Changed'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(f'{self.url}{system.pk}/reset-password/', {'password': 'Meadow!Window!Velvet!2026'}, format='json').status_code, 400)

    def test_password_reset_invalidates_old_session_and_does_not_leak_password(self):
        self.owner.set_password('Old!Window!River!2026'); self.owner.save()
        other_device = APIClient(); other_device.force_login(self.owner)
        self.assertEqual(other_device.get('/api/v1/auth/me/').status_code, 200)
        response = self.client.post(f'{self.url}{self.owner.pk}/reset-password/', {'password': 'New!Window!River!2026'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(other_device.get('/api/v1/auth/me/').status_code, 403)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password('New!Window!River!2026'))
        self.assertNotIn('New!Window', str(self.client.get('/api/v1/admin/access-events/').data))
        self.assertEqual(self.client.patch(f'{self.url}{self.owner.pk}/', {'password': 'Different!Window!River!2026'}, format='json').status_code, 400)

    def test_self_password_change_requires_current_password(self):
        url = f'{self.url}{self.admin.pk}/reset-password/'
        self.assertEqual(self.client.post(url, {'password': 'New!Window!River!2026'}, format='json').status_code, 400)
        self.client.force_authenticate(None); self.client.force_login(self.admin)
        response = self.client.post(url, {'password': 'New!Window!River!2026', 'current_password': 'River!Orchid!Window!2026'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.client.get('/api/v1/auth/me/').status_code, 200)

    def test_role_branch_change_revokes_sessions_and_deactivation_is_reversible(self):
        device = APIClient(); device.force_login(self.other)
        response = self.client.patch(f'{self.url}{self.other.pk}/', {'role': 'intern', 'is_active': False}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(device.get('/api/v1/auth/me/').status_code, 403)
        self.assertEqual(self.client.patch(f'{self.url}{self.other.pk}/', {'is_active': True}, format='json').status_code, 200)
        self.assertEqual(device.get('/api/v1/auth/me/').status_code, 403)
        self.assertEqual(self.client.delete(f'{self.url}{self.other.pk}/').status_code, 405)

    def test_admin_role_grants_crm_administration_without_django_superuser(self):
        response = self.client.post(self.url, {**self.data(), 'role': 'super_admin', 'branch': None}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(pk=response.data['id'])
        self.client.force_authenticate(user)
        self.assertTrue(self.client.get('/api/v1/auth/me/').data['capabilities']['manage_users'])
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertFalse(user.is_superuser)

    def test_csrf_required_for_admin_writes(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url, self.data(), format='json').status_code, 403)

    def test_stale_admin_request_is_rechecked_inside_write_lock(self):
        User.objects.filter(pk=self.admin.pk).update(role='counsellor', branch=self.a)
        self.assertEqual(self.client.post(self.url, self.data(), format='json').status_code, 403)
        self.assertFalse(User.objects.filter(username='new-counsellor').exists())

    def test_summary_excludes_counsellors_at_capacity(self):
        CounsellorProfile.objects.all().update(max_active_leads=1, is_available=True)
        before = self.client.get(self.url+'summary/').data['assignment_ready']
        create_lead(actor=self.manager, branch=self.a, contact=self.contact, owner=self.owner, title='Python')
        after = self.client.get(self.url+'summary/').data['assignment_ready']
        self.assertEqual(after, before-1)
