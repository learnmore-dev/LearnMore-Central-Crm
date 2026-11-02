from celery import shared_task
from . import services


@shared_task(name='messaging.process_webhooks')
def process_webhooks():
    return services.process_webhooks()


@shared_task(name='messaging.dispatch_outbox')
def dispatch_outbox():
    return services.dispatch_outbox()
