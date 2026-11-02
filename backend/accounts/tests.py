from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient
from branches.models import Branch

User = get_user_model()

class AuthenticationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.branch = Branch.objects.create(name='Marathahalli', code='marathahalli')
        self.user = User.objects.create_user(username='counsellor', password='a-test-password-123', branch=self.branch)
        self.client = APIClient(enforce_csrf_checks=True)

    def csrf(self):
        return self.client.get('/api/v1/auth/csrf/').json()['csrfToken']

    def test_login_requires_csrf_even_for_anonymous_users(self):
        response = self.client.post('/api/v1/auth/login/', {'username': self.user.username, 'password': 'a-test-password-123'})
        self.assertEqual(response.status_code, 403)

    def test_login_profile_logout_and_session_invalidation(self):
        response = self.client.post('/api/v1/auth/login/', {'username': self.user.username, 'password': 'a-test-password-123'}, HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['role'], 'counsellor')
        self.assertNotIn('password', response.json())
        self.assertEqual(self.client.get('/api/v1/auth/me/').status_code, 200)
        self.assertEqual(self.client.post('/api/v1/auth/logout/').status_code, 403)
        self.assertEqual(self.client.post('/api/v1/auth/logout/', HTTP_X_CSRFTOKEN=self.csrf()).status_code, 204)
        self.assertEqual(self.client.get('/api/v1/auth/me/').status_code, 403)

    def test_inactive_and_invalid_credentials_return_same_error(self):
        token = self.csrf()
        invalid = self.client.post('/api/v1/auth/login/', {'username': 'unknown', 'password': 'invalid'}, HTTP_X_CSRFTOKEN=token)
        self.user.is_active = False
        self.user.save()
        inactive = self.client.post('/api/v1/auth/login/', {'username': self.user.username, 'password': 'a-test-password-123'}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(inactive.json(), invalid.json())

    def test_login_validation_and_throttling(self):
        token = self.csrf()
        self.assertEqual(self.client.post('/api/v1/auth/login/', {}, HTTP_X_CSRFTOKEN=token).status_code, 400)
        cache.clear()
        for _ in range(10):
            self.assertEqual(self.client.post('/api/v1/auth/login/', {'username': 'unknown', 'password': 'wrong'}, HTTP_X_CSRFTOKEN=token).status_code, 401)
        self.assertEqual(self.client.post('/api/v1/auth/login/', {'username': 'unknown', 'password': 'wrong'}, HTTP_X_CSRFTOKEN=token).status_code, 429)

    def test_scoped_user_requires_branch_at_database_level(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username='unscoped', password='irrelevant')

    def test_profile_cannot_change_role(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.patch('/api/v1/auth/me/', {'role': 'super_admin'}, HTTP_X_CSRFTOKEN=self.csrf()).status_code, 405)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.COUNSELLOR)

    def test_staff_cannot_administer_users_even_with_model_permissions(self):
        from django.contrib.auth.models import Permission
        self.user.is_staff = True
        self.user.save()
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label='accounts'))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/admin/accounts/user/').status_code, 403)

    def test_cross_origin_login_is_rejected(self):
        self.assertEqual(self.client.post('/api/v1/auth/login/',
            {'username': self.user.username, 'password': 'a-test-password-123'},
            HTTP_X_CSRFTOKEN=self.csrf(), HTTP_ORIGIN='https://untrusted.example').status_code, 403)
