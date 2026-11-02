import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from google_contacts.services import process_queue


class Command(BaseCommand):
    help = 'Process queued, explicitly approved Google syncs and enabled schedules. No contact deletion.'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')

    def handle(self, **options):
        while True:
            close_old_connections()
            self.stdout.write(str(process_queue()))
            self.stdout.flush()
            if not options['watch']:
                break
            time.sleep(10)
