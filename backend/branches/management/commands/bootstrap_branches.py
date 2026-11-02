from django.core.management.base import BaseCommand
from django.db import transaction
from branches.models import Branch

class Command(BaseCommand):
    help = 'Idempotently create the three configured LearnMore branches; no demo users or customer data.'

    @transaction.atomic
    def handle(self, *args, **options):
        for code, name in [('marathahalli', 'Marathahalli'), ('btm-layout', 'BTM Layout'), ('kalyan-nagar', 'Kalyan Nagar')]:
            Branch.objects.get_or_create(code=code, defaults={'name': name})
        self.stdout.write(self.style.SUCCESS('Branch configuration is ready.'))
