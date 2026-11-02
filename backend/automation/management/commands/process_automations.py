from django.core.management.base import BaseCommand
from django.db import close_old_connections
import time
from education.jobs import run_cycle


class Command(BaseCommand):
    help = 'Process mock automation steps and staff tasks. Never sends messages.'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true', help='Poll every ten seconds for local development without Celery.')

    def handle(self, **options):
        while True:
            close_old_connections()
            self.stdout.write(str(run_cycle()))
            self.stdout.flush()
            if not options['watch']:
                break
            time.sleep(10)
