from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from automation.api import RuleSerializer
from automation.models import AutomationRule
from branches.models import Branch
from common.access import branch_scope
from common.permissions import has_global_scope


def task(title, delay):
    return {'kind': 'task', 'title': title, 'delay_minutes': delay, 'grace_minutes': 30}


def message(title, delay, body):
    return {'kind': 'message', 'title': title, 'delay_minutes': delay, 'body': body}


PRESETS = [
    {
        'name': 'LearnMore | Website enquiry - 7 day follow-up',
        'source': 'website', 'callback_minutes': 5,
        'acknowledgement_text': 'Hi {name}, thank you for enquiring about {course} at LearnMore Technologies, {branch}. A counsellor will help you with the syllabus, batch timings and course details. What is a convenient time to call?',
        'steps': [
            task('Day 1: Call to understand learning goals, experience and preferred batch', 1440),
            message('Day 2: Offer course guidance', 2880, 'Hi {name}, would you like help choosing the right learning path for {course}? Our LearnMore Technologies team at {branch} can explain the syllabus and available batch timings. Reply with a convenient time to talk. If you do not want further follow-ups, please let us know.'),
            task('Day 3: Offer a demo after confirming interest and trainer availability', 4320),
            task('Day 7: Record final outcome or agree a future follow-up; respect opt-outs', 10080),
        ],
    },
    {
        'name': 'LearnMore | Missed call - callback within 5 minutes',
        'source': 'call', 'callback_minutes': 5,
        'acknowledgement_text': '', 'steps': [],
    },
    {
        'name': 'LearnMore | WhatsApp enquiry - counselling follow-up',
        'source': 'whatsapp', 'callback_minutes': 10,
        'acknowledgement_text': 'Hi {name}, welcome to LearnMore Technologies, {branch}. Thank you for reaching out about {course}. Please share your learning goal and preferred time for a counselling call.',
        'steps': [
            task('Day 1: Review chat, confirm course interest and offer counselling', 1440),
            message('Day 2: Check whether guidance is still needed', 2880, 'Hi {name}, are you still looking for guidance on {course}? LearnMore Technologies, {branch}, can help with course content and batch options. Let us know a suitable time, or tell us if you prefer no further follow-ups.'),
            task('Day 4: Review response and record the next step or no-follow-up reason', 5760),
        ],
    },
    {
        'name': 'LearnMore | Walk-in enquiry - counselling and demo',
        'source': 'manual', 'callback_minutes': 30,
        'acknowledgement_text': 'Hi {name}, thank you for your interest in {course} at LearnMore Technologies, {branch}. Our counsellor can help with the course outline, batch options and next steps.',
        'steps': [
            task('Day 1: Confirm course fit, preferred schedule and any questions', 1440),
            task('Day 3: Offer a demo after confirming interest and trainer availability', 4320),
            message('Day 5: Offer help with remaining questions', 7200, 'Hi {name}, do you have any remaining questions about {course} at LearnMore Technologies, {branch}? We can help you decide your next step. Please let us know if you prefer no further follow-ups.'),
            task('Day 7: Record decision or a student-agreed follow-up date', 10080),
        ],
    },
]


class Command(BaseCommand):
    help = 'Create disabled LearnMore automation drafts; never enrolls contacts or sends messages.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True, help='Existing active manager username for creation attribution.')
        parser.add_argument('--branch', help='Optional branch code; otherwise all active branches accessible to the actor.')

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
        created = skipped = 0
        for branch in branches:
            for preset in PRESETS:
                if AutomationRule.objects.filter(branch=branch, name=preset['name']).exists():
                    skipped += 1
                    continue
                serializer = RuleSerializer(data={
                    **preset, 'branch': str(branch.pk), 'is_active': False,
                    'acknowledgement_minutes': 1, 'business_hours': True,
                    'start_hour': 9, 'end_hour': 18,
                }, context={'request': SimpleNamespace(user=actor)})
                serializer.is_valid(raise_exception=True)
                serializer.save()
                created += 1
                self.stdout.write(f"Created disabled draft: {branch.name} / {preset['name']}")
        self.stdout.write(self.style.SUCCESS(f'Created {created}; preserved {skipped} existing rules. No enquiries enrolled.'))
