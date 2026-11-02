"""Explicit isolated PostgreSQL tests; never falls back to a development database."""
import os
from .test_settings import *  # noqa: F403

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.environ['POSTGRES_TEST_DB'],
    'USER': os.environ['POSTGRES_TEST_USER'],
    'PASSWORD': os.environ['POSTGRES_TEST_PASSWORD'],
    'HOST': os.environ['POSTGRES_TEST_HOST'],
    'PORT': os.environ['POSTGRES_TEST_PORT'],
    'CONN_MAX_AGE': 0,
}}
