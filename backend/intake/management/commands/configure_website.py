from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from branches.models import Branch
from intake.models import WebsiteSource


class Command(BaseCommand):
    help = 'Configure a website source, default branch and non-login integration actor. Secrets remain environment-only.'

    def add_arguments(self, parser):
        parser.add_argument('site', choices=[key for key, _ in WebsiteSource.SITES])
        parser.add_argument('--branch', required=True, help='Default branch code.')
        parser.add_argument('--allowed-branch', action='append', default=[], help='Additional permitted branch code (repeatable).')

    @transaction.atomic
    def handle(self, *args, **options):
        codes = set([options['branch'], *options['allowed_branch']])
        branches = {b.code: b for b in Branch.objects.filter(code__in=codes, is_active=True)}
        if set(branches) != codes:
            raise CommandError('Choose existing active branch codes.')
        user, created = get_user_model().objects.get_or_create(username='intake-' + options['site'], defaults={
            'role': 'management', 'is_active': True, 'is_staff': False})
        if created:
            user.set_unusable_password()
            user.save(update_fields=['password'])
        if user.has_usable_password() or user.role != 'management' or not user.is_active or user.is_staff or user.is_superuser:
            raise CommandError('The integration username is already in use by a different account. No account was changed.')
        source, _ = WebsiteSource.objects.update_or_create(slug=options['site'], defaults={
            'default_branch': branches[options['branch']], 'actor': user, 'is_active': True})
        source.allowed_branches.set(branches.values())
        self.stdout.write(f'{source.domain}: default branch {options["branch"]}; source enabled. Configure its environment secret separately.')
