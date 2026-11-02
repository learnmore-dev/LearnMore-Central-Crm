from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from common.access import branch_scope
from common.permissions import has_global_scope
from messaging.models import Channel, Conversation
from messaging.intake import receive


class Command(BaseCommand):
    help = 'Configure an existing manager for automatic WhatsApp contact/enquiry intake. No messages sent.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True)
        parser.add_argument('--channel', help='Optional inbox UUID; otherwise active authorized inboxes.')
        parser.add_argument('--retry-existing', action='store_true', help='Also process conversations with existing inbound messages.')

    @transaction.atomic
    def handle(self, **options):
        actor = get_user_model().objects.filter(username=options['actor'], is_active=True).first()
        if not actor or not (has_global_scope(actor) or actor.role == 'branch_manager'):
            raise CommandError('Choose an existing active manager or superuser.')
        channels = branch_scope(Channel.objects.filter(is_active=True, branch__is_active=True), actor)
        if options['channel']:
            channels = channels.filter(pk=options['channel'])
        count = 0
        for channel in channels:
            channel.intake_actor, channel.auto_intake = actor, True
            channel.save(update_fields=['intake_actor', 'auto_intake'])
            self.stdout.write(f'Configured: {channel.name} / {channel.branch.name}')
            count += 1
            if options['retry_existing']:
                for row in Conversation.objects.select_for_update().filter(channel=channel, last_inbound_at__isnull=False).select_related('channel__branch', 'channel__intake_actor', 'contact', 'review', 'lead'):
                    receive(row)
        self.stdout.write(self.style.SUCCESS(f'Configured {count} inbox(es). No messages sent.'))
