"""Explicit SQLite smoke tests only; never a supported production database."""
import os
os.environ.setdefault('DJANGO_SECRET_KEY', 'isolated-test-key-not-valid-for-deployment-123456789')
os.environ['DJANGO_DEBUG'] = 'true'
from .settings import *  # noqa: F403
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
