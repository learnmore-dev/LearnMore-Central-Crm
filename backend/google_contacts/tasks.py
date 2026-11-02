from celery import shared_task
from .services import process_queue


@shared_task(name='google_contacts.process')
def process_google_contacts():
    return process_queue()
