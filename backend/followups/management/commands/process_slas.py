from django.core.management.base import BaseCommand
from followups.services import process_slas
from routing.services import retry_unassigned


class Command(BaseCommand):
    help = 'Process one idempotent batch of overdue tasks and retry the unassigned queue.'

    def handle(self, *args, **options):
        processed = process_slas()
        assigned = retry_unassigned()
        self.stdout.write('Processed %s SLA tasks; assigned %s queued leads.' % (processed, assigned))
