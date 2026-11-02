from celery import shared_task
from education.jobs import run_cycle


@shared_task(name='automation.process')
def process():
    return run_cycle()
