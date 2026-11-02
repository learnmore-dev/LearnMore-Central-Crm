from celery import shared_task
from django.db import OperationalError
from .services import process_slas
from routing.services import retry_unassigned


@shared_task(name='followups.process_slas', autoretry_for=(OperationalError,), retry_backoff=True, max_retries=5)
def process_sla_tasks():
    return process_slas()


@shared_task(name='followups.retry_unassigned', autoretry_for=(OperationalError,), retry_backoff=True, max_retries=5)
def retry_unassigned_tasks():
    return retry_unassigned()
