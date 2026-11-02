from django.core.management.base import BaseCommand, CommandError
from messaging.models import Channel
from messaging.services import sync_templates
from messaging.provider import ProviderError
from django.conf import settings
from django.utils import timezone
from messaging.models import Template


class Command(BaseCommand):
    help = 'Read Meta template approvals for one configured channel; never sends messages.'

    def add_arguments(self, parser):
        parser.add_argument('channel_id')
        parser.add_argument('--mock', action='store_true', help='Install a simulation-only template without network access.')

    def handle(self, *args, **options):
        try:
            channel = Channel.objects.get(pk=options['channel_id'])
            if options['mock']:
                if settings.WHATSAPP_MODE != 'mock':
                    raise CommandError('--mock requires WHATSAPP_MODE=mock.')
                Template.objects.update_or_create(channel=channel, name='mock_welcome', language='en_US', defaults={
                    'provider_id': 'mock-template', 'status': 'APPROVED', 'body': 'Hello {{1}}, how can we help?',
                    'parameter_count': 1, 'supported': True, 'source_mode': 'mock', 'synced_at': timezone.now()})
                self.stdout.write('Installed mock_welcome for simulation only; no Meta request was made.')
                return
            count = sync_templates(channel)
        except (Channel.DoesNotExist, ProviderError, ValueError) as error:
            raise CommandError('Template sync failed. Check channel/configuration and retry.') from None
        self.stdout.write(f'Synced {count} templates.')
