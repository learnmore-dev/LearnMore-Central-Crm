from io import StringIO
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient
from .models import Branch

User = get_user_model()

class BranchAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a = Branch.objects.create(name='Marathahalli', code='marathahalli')
        self.b = Branch.objects.create(name='BTM Layout', code='btm-layout')
        self.client = APIClient()

    def test_anonymous_cannot_read_or_write(self):
        self.assertEqual(self.client.get('/api/v1/branches/').status_code, 403)
        self.assertEqual(self.client.post('/api/v1/branches/', {'name': 'No', 'code': 'no'}).status_code, 403)

    def test_all_scoped_roles_are_branch_restricted_and_cannot_write(self):
        for role in (User.Role.BRANCH_MANAGER, User.Role.COUNSELLOR, User.Role.ACCOUNTS, User.Role.SUPPORT):
            with self.subTest(role=role):
                user = User.objects.create_user(username=role, branch=self.a, role=role)
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get('/api/v1/branches/').json()['count'], 1)
                self.assertEqual(self.client.get('/api/v1/branches/?branch=' + str(self.b.pk)).json()['results'][0]['id'], str(self.a.pk))
                self.assertEqual(self.client.get('/api/v1/branches/%s/' % self.b.pk).status_code, 404)
                self.assertEqual(self.client.patch('/api/v1/branches/%s/' % self.a.pk, {'name': 'Changed'}).status_code, 403)

    def test_global_roles_can_manage_branches_but_not_delete(self):
        for role in (User.Role.SUPER_ADMIN, User.Role.MANAGEMENT):
            user = User.objects.create_user(username=role, role=role)
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get('/api/v1/branches/').json()['count'], 2)
            self.assertEqual(self.client.patch('/api/v1/branches/%s/' % self.a.pk, {'address': 'Bengaluru'}).status_code, 200)
            self.assertEqual(self.client.delete('/api/v1/branches/%s/' % self.a.pk).status_code, 405)

    def test_branch_creation_uniqueness_and_deactivation(self):
        self.client.force_authenticate(User.objects.create_superuser(username='admin', password='test-only-password'))
        self.assertEqual(self.client.post('/api/v1/branches/', {'name': 'Kalyan Nagar', 'code': 'kalyan-nagar'}).status_code, 201)
        self.assertEqual(self.client.post('/api/v1/branches/', {'name': 'Kalyan Nagar', 'code': 'another'}).status_code, 400)
        self.assertEqual(self.client.patch('/api/v1/branches/%s/' % self.a.pk, {'is_active': False}, format='json').status_code, 200)
        self.a.refresh_from_db()
        self.assertFalse(self.a.is_active)

    def test_bootstrap_is_idempotent_and_preserves_customization(self):
        self.a.address = 'Existing address'
        self.a.save()
        for _ in range(2):
            call_command('bootstrap_branches', stdout=StringIO())
        self.assertEqual(Branch.objects.count(), 3)
        self.a.refresh_from_db()
        self.assertEqual(self.a.address, 'Existing address')
