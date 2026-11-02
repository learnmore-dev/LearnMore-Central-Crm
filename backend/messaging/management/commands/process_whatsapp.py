from django.core.management.base import BaseCommand
from messaging import services


class Command(BaseCommand):
    help = 'Process signed webhook receipts. Outbound dispatch requires --dispatch (mock by default).'

    def add_arguments(self, parser):
        parser.add_argument('--dispatch', action='store_true')

    def handle(self, *args, **options):
        received = services.process_webhooks()
        sent = services.dispatch_outbox() if options['dispatch'] else 0
        self.stdout.write(f'Processed {received} webhook receipts; inspected {sent} queued messages.')
