from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from branches.models import Branch
from common.access import branch_scope
from common.permissions import has_global_scope
from automation.presets import PRESETS, install_starter_rules


class Command(BaseCommand):
    help = 'Install LearnMore starter rules. Message steps never send messages.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True, help='Existing active manager username for creation attribution.')
        parser.add_argument('--branch', help='Optional branch code; otherwise all active branches accessible to the actor.')
        parser.add_argument('--enable', action='store_true', help='Enable installed rules for new arrivals; creates real staff tasks when processed.')
        parser.add_argument('--source', choices=[preset['source'] for preset in PRESETS], help='Install just one source, such as the all-source course guide.')

    @transaction.atomic
    def handle(self, **options):
        actor = get_user_model().objects.filter(username=options['actor'], is_active=True).first()
        if not actor or not (has_global_scope(actor) or actor.role == 'branch_manager'):
            raise CommandError('Choose an existing active manager or superuser.')
        branches = branch_scope(Branch.objects.filter(is_active=True), actor, 'pk')
        if options['branch']:
            branches = branches.filter(code=options['branch'])
        if not branches.exists():
            raise CommandError('No active accessible branches matched.')
        for branch in branches:
            result = install_starter_rules(actor=actor, branch=branch, enable=options['enable'], source=options['source'])
            self.stdout.write(self.style.SUCCESS(
                f"{branch.name}: created {result['created']}; preserved {result['preserved']}; enabled {result['enabled']}."))
            if result['conflicts']:
                self.stdout.write('Existing active rules preserved for: ' + ', '.join(result['conflicts']))
        self.stdout.write('Only new arrivals enroll automatically. No messages sent or historic enquiries enrolled.')
