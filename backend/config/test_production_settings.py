"""Import the production profile in isolation without touching any database."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import TestCase


class ProductionSettingsTests(TestCase):
    def inspect(self, changes=None):
        env = os.environ.copy()
        env.update({
            'DJANGO_SECRET_KEY': 'isolated-settings-test-key-' + 'x' * 50,
            'DJANGO_DEBUG': 'false', 'CRM_DOMAIN': 'crm.example.com',
            'POSTGRES_DB': 'centralcrm_prod', 'POSTGRES_USER': 'centralcrm_app',
            'POSTGRES_PASSWORD': 'isolated-db-password', 'POSTGRES_HOST': '127.0.0.1',
            'REDIS_URL': 'redis://:isolated-test-password@127.0.0.1:6381/0',
            'REDIS_CACHE_URL': 'redis://:isolated-test-password@127.0.0.1:6381/1',
            'DJANGO_SECURE_SSL_REDIRECT': 'false',
        })
        env.update(changes or {})
        code = '''import json
from config import production_settings as s
print(json.dumps({'engine': s.DATABASES['default']['ENGINE'], 'debug': s.DEBUG,
 'hosts': s.ALLOWED_HOSTS, 'redirect': s.SECURE_SSL_REDIRECT,
 'secure_cookie': s.SESSION_COOKIE_SECURE, 'cookie_name': s.SESSION_COOKIE_NAME,
 'cache': s.CACHES['default']['BACKEND'], 'queue': s.CELERY_TASK_DEFAULT_QUEUE}))'''
        return subprocess.run([sys.executable, '-c', code], env=env,
                              cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)

    def test_enforces_postgresql_https_and_shared_cache(self):
        result = self.inspect()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['engine'], 'django.db.backends.postgresql')
        self.assertEqual(data['hosts'], ['crm.example.com'])
        self.assertFalse(data['debug'])
        self.assertTrue(data['redirect'])
        self.assertTrue(data['secure_cookie'])
        self.assertEqual(data['cookie_name'], 'centralcrm_sessionid')
        self.assertIn('redis.RedisCache', data['cache'])
        self.assertEqual(data['queue'], 'centralcrm-production')

    def test_rejects_debug_and_unsafe_or_missing_configuration(self):
        for changes in [
            {'DJANGO_DEBUG': 'true'}, {'CRM_DOMAIN': '*'},
            {'CRM_DOMAIN': 'http://crm.example.com'}, {'POSTGRES_DB': ''},
            {'POSTGRES_DB': 'postgres'}, {'POSTGRES_USER': 'postgres'},
            {'POSTGRES_PASSWORD': ''}, {'REDIS_CACHE_URL': ''},
            {'DJANGO_SECRET_KEY': 'replace-with-a-random-secret-of-at-least-50-characters'},
            {'REDIS_URL': 'redis://127.0.0.1:6381/0'},
        ]:
            with self.subTest(changes=changes):
                self.assertNotEqual(self.inspect(changes).returncode, 0)
