"""Single-process scheduler for the local workspace, without Redis."""
import time
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from education.jobs import run_cycle
from followups.services import process_slas
from routing.services import retry_unassigned
from messaging.services import process_webhooks, dispatch_outbox


class Command(BaseCommand):
    help = 'Run local follow-up and mock messaging jobs without Celery/Redis.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--interval', type=int, default=30)

    def handle(self, *args, **options):
        if not settings.DEBUG or settings.WHATSAPP_MODE != 'mock':
            raise CommandError('Local jobs require DEBUG=true and WHATSAPP_MODE=mock. Use Celery for deployment.')
        if options['interval'] < 1:
            raise CommandError('--interval must be at least one second.')
        jobs = [run_cycle, process_slas, retry_unassigned, process_webhooks, dispatch_outbox]
        try:
            while True:
                for job in jobs:
                    try:
                        self.stdout.write(f'{job.__name__}: {job()}')
                    except Exception as error:
                        self.stderr.write(f'{job.__name__}: {type(error).__name__}; retry next cycle')
                if options['once']:
                    return
                time.sleep(options['interval'])
        except KeyboardInterrupt:
            self.stdout.write('Local jobs stopped.')
