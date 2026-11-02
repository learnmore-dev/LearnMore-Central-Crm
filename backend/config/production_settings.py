"""HTTPS deployment behind the loopback-only Nginx/Gunicorn setup in deploy/ubuntu."""
import os
import re
from urllib.parse import urlsplit
from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F403


def required(name):
    value = os.getenv(name, '').strip()
    if not value or value.startswith('replace-'):
        raise ImproperlyConfigured(f'Set {name} before using production settings.')
    return value


if DEBUG:  # noqa: F405
    raise ImproperlyConfigured('Production requires DJANGO_DEBUG=false.')
SECRET_KEY = required('DJANGO_SECRET_KEY')
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured('Production requires a random DJANGO_SECRET_KEY of at least 50 characters.')

DOMAIN = required('CRM_DOMAIN').lower()
if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', DOMAIN):
    raise ImproperlyConfigured('CRM_DOMAIN must be one DNS hostname without a scheme, port or wildcard.')

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': required('POSTGRES_DB'),
    'USER': required('POSTGRES_USER'),
    'PASSWORD': required('POSTGRES_PASSWORD'),
    'HOST': required('POSTGRES_HOST'),
    'PORT': os.getenv('POSTGRES_PORT', '5432'),
    'CONN_MAX_AGE': 60,
    'CONN_HEALTH_CHECKS': True,
    'OPTIONS': {'connect_timeout': 10},
}}
if DATABASES['default']['NAME'] in ('postgres', 'template0', 'template1') or DATABASES['default']['USER'] == 'postgres':
    raise ImproperlyConfigured('Use a dedicated CRM database and a non-superuser login.')

ALLOWED_HOSTS = [DOMAIN]
CSRF_TRUSTED_ORIGINS = [f'https://{DOMAIN}']
CORS_ALLOWED_ORIGINS = []  # Nginx provides same-origin frontend/API access.
SECURE_SSL_REDIRECT = True
# Trust only the proxy that overwrites this header; Gunicorn must bind to loopback.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
SESSION_COOKIE_NAME = 'centralcrm_sessionid'
CSRF_COOKIE_NAME = 'centralcrm_csrftoken'
SESSION_COOKIE_DOMAIN = CSRF_COOKIE_DOMAIN = None
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
STATIC_URL = '/static/'

def redis_url(name):
    value = required(name)
    parsed = urlsplit(value)
    if parsed.scheme not in ('redis', 'rediss') or not parsed.hostname or not parsed.password or parsed.password.startswith('replace-'):
        raise ImproperlyConfigured(f'{name} must be an authenticated Redis URL with a real password.')
    return value


CELERY_BROKER_URL = redis_url('REDIS_URL')
CACHES = {'default': {
    'BACKEND': 'django.core.cache.backends.redis.RedisCache',
    'LOCATION': redis_url('REDIS_CACHE_URL'),
    'KEY_PREFIX': 'centralcrm-production',
}}
CELERY_TASK_DEFAULT_QUEUE = 'centralcrm-production'
