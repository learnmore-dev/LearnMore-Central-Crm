import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / '.env')

def boolean(name, default=False):
    return os.getenv(name, str(default)).lower() in ('true', '1', 'yes')

def csv(name, default=''):
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '')
if len(SECRET_KEY) < 32 or SECRET_KEY == 'replace-with-a-random-secret':
    raise ImproperlyConfigured('Set DJANGO_SECRET_KEY to a random value of at least 32 characters.')
DEBUG = boolean('DJANGO_DEBUG')
ALLOWED_HOSTS = csv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'corsheaders', 'rest_framework', 'drf_spectacular', 'branches', 'accounts',
    'common', 'contacts', 'leads', 'activities', 'routing', 'followups', 'messaging', 'intake', 'calls', 'automation', 'education', 'google_contacts',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'corsheaders.middleware.CorsMiddleware',
    'common.middleware.PrivateAPIMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True,
              'OPTIONS': {'context_processors': ['django.template.context_processors.request',
                          'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'
# DATABASES = {'default': {
#     'ENGINE': 'django.db.backends.postgresql', 'NAME': os.getenv('POSTGRES_DB', 'learnmore'),
#     'USER': os.getenv('POSTGRES_USER', 'learnmore'), 'PASSWORD': os.getenv('POSTGRES_PASSWORD', ''),
#     'HOST': os.getenv('POSTGRES_HOST', '127.0.0.1'), 'PORT': os.getenv('POSTGRES_PORT', '5432'),
#     'CONN_MAX_AGE': 60,
# }}
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
AUTH_USER_MODEL = 'accounts.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'en-in'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CSRF_TRUSTED_ORIGINS = csv('DJANGO_CSRF_TRUSTED_ORIGINS')
CORS_ALLOWED_ORIGINS = csv('DJANGO_CORS_ALLOWED_ORIGINS')
CORS_ALLOW_CREDENTIALS = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 28800
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_SSL_REDIRECT = boolean('DJANGO_SECURE_SSL_REDIRECT', not DEBUG)
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
# Configure proxy headers only after a trusted proxy strips client-supplied headers.
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination', 'PAGE_SIZE': 50,
    'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.AnonRateThrottle', 'rest_framework.throttling.UserRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {'anon': '100/hour', 'user': '1000/hour', 'login': '10/minute', 'website_intake': '120/minute', 'live_enquiries': '30/minute'},
}
SPECTACULAR_SETTINGS = {
    'TITLE': 'LearnMore Connect API', 'VERSION': '1.0.0', 'SERVE_INCLUDE_SCHEMA': False,
    'ENUM_NAME_OVERRIDES': {
        'ContactIdentifierKindEnum': 'contacts.schema.identifier_kinds',
        'ActivityKindEnum': 'activities.schema.activity_kinds',
        'AutomationRuleSourceEnum': 'automation.schema.rule_sources',
        'SourceEnum': 'contacts.schema.sources',
    },
}
# Single-process development cache only. Before multi-worker deployment, use a shared
# Redis cache and enforce authentication rate limits at the trusted ingress too.
CELERY_BROKER_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    'google-contacts': {'task': 'google_contacts.process', 'schedule': 60.0},
    'crm-automations': {'task': 'automation.process', 'schedule': 30.0},
    'process-slas': {'task': 'followups.process_slas', 'schedule': 60.0},
    'retry-unassigned': {'task': 'followups.retry_unassigned', 'schedule': 60.0},
    'whatsapp-webhooks': {'task': 'messaging.process_webhooks', 'schedule': 10.0},
    'whatsapp-outbox': {'task': 'messaging.dispatch_outbox', 'schedule': 10.0},
}

# Credentials are environment-only and are never exposed through browser APIs.
WHATSAPP_MODE = os.getenv('WHATSAPP_MODE', 'mock')
if WHATSAPP_MODE not in ('mock', 'live'):
    raise ImproperlyConfigured('WHATSAPP_MODE must be mock or live.')
WHATSAPP_LIVE_SENDS_ENABLED = boolean('WHATSAPP_LIVE_SENDS_ENABLED', False)
WHATSAPP_ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN', '')
WHATSAPP_APP_SECRET = os.getenv('WHATSAPP_APP_SECRET', '')
WHATSAPP_VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN', '')
WHATSAPP_GRAPH_VERSION = os.getenv('WHATSAPP_GRAPH_VERSION', '')

WEBSITE_INTAKE_SECRETS = {
    'learnmoretech': os.getenv('WEBSITE_LEARNMORETECH_SECRET', ''),
    'learnmoretechnologies': os.getenv('WEBSITE_LEARNMORETECHNOLOGIES_SECRET', ''),
}

GOOGLE_CONTACTS_CLIENT_ID = os.getenv('GOOGLE_CONTACTS_CLIENT_ID', '')
GOOGLE_CONTACTS_CLIENT_SECRET = os.getenv('GOOGLE_CONTACTS_CLIENT_SECRET', '')
GOOGLE_CONTACTS_ENCRYPTION_KEY = os.getenv('GOOGLE_CONTACTS_ENCRYPTION_KEY', '')
GOOGLE_CONTACTS_REDIRECT_URI = os.getenv('GOOGLE_CONTACTS_REDIRECT_URI', '')
GOOGLE_CONTACTS_CRM_ORIGIN = os.getenv('GOOGLE_CONTACTS_CRM_ORIGIN', '')
GOOGLE_CONTACTS_EXPECTED_EMAIL = os.getenv('GOOGLE_CONTACTS_EXPECTED_EMAIL', '')

LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'filters': {'redact_google_callback': {'()': 'google_contacts.logging.RedactGoogleCallback'}},
    'loggers': {'django.server': {'filters': ['redact_google_callback']}, 'django.request': {'filters': ['redact_google_callback']}},
}
