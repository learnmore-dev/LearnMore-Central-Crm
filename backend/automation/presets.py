"""Reusable LearnMore course-enquiry rules. Message actions remain simulations."""
from types import SimpleNamespace
from django.db import transaction
from branches.models import Branch
from .models import AutomationRule


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


COURSE_OPTIONS = [
    'Python Full Stack Development', 'Java Full Stack Development',
    '.NET Full Stack Development', 'Data Science', 'Data Analytics',
    'Artificial Intelligence', 'Machine Learning', 'AWS', 'Azure', 'DevOps',
    'Software Testing', 'Selenium', 'Power BI', 'SQL', 'Advanced Excel',
]
COURSE_GUIDE = 'Courses include: ' + '; '.join(COURSE_OPTIONS) + '.'

PRESETS.insert(0, {
    'name': 'LearnMore | IT course enquiry - counselling and course guide',
    'source': 'all', 'callback_minutes': 10,
    'acknowledgement_text': 'Hi {name}, welcome to LearnMore Technologies, {branch}! Thank you for your interest in {course}. '
        + COURSE_GUIDE + ' Which course interests you, and when would you like a counselling call?',
    'steps': [
        task('Confirm course interest, experience, training mode and preferred batch', 30),
        message('Day 1: Share LearnMore course options', 1440,
            'Hi {name}, here are some learning options at LearnMore Technologies: ' + COURSE_GUIDE
            + ' Our {branch} counsellor can help you choose a path for your learning goals. Reply with your preferred course and call time, or let us know if you prefer no further follow-ups.'),
        task('Day 2: Discuss syllabus, batch options and approved fee details', 2880),
        task('Day 3: Confirm interest and trainer availability before booking a demo', 4320),
        task('Day 7: Record the decision or agree the next follow-up date', 10080),
    ],
})

DESCRIPTIONS = {
    'all': 'A course guide, a counselling call within 10 minutes, qualification, syllabus discussion, demo coordination and a seven-day decision review. Used when no source-specific rule is enabled.',
    'website': 'Acknowledge website enquiries, call within five minutes, discuss course fit, offer a demo and review the decision on day seven.',
    'call': 'Create a five-minute callback task for an incoming missed call. Calls linked to an enquiry follow its normal enquiry sequence.',
    'whatsapp': 'Preview a welcome reply, create a counselling task and check course interest. A candidate reply pauses the sequence for a counsellor.',
    'manual': 'Help walk-in and manually entered candidates confirm their course, batch preferences and demo interest, then record their decision.',
}


def library():
    return {'templates': [dict(preset, key=preset['source'], description=DESCRIPTIONS[preset['source']]) for preset in PRESETS],
            'courses': COURSE_OPTIONS}


@transaction.atomic
def install_starter_rules(*, actor, branch, enable=False, source=None):
    # Serialize installation with rule editing to preserve per-source uniqueness.
    from .api import RuleSerializer
    from .services import save_rule
    from common.access import require_manager
    require_manager(actor, branch)
    Branch.objects.select_for_update().get(pk=branch.pk)
    summary = {'created': 0, 'enabled': 0, 'preserved': 0, 'conflicts': [], 'rules': []}
    for preset in PRESETS:
        if source is not None and preset['source'] != source:
            continue
        rule = AutomationRule.objects.filter(branch=branch, name=preset['name']).first()
        if rule:
            summary['preserved'] += 1
        else:
            serializer = RuleSerializer(data={
                **preset, 'branch': str(branch.pk), 'is_active': False,
                'acknowledgement_minutes': 1, 'business_hours': True, 'start_hour': 9, 'end_hour': 18,
            }, context={'request': SimpleNamespace(user=actor)})
            serializer.is_valid(raise_exception=True)
            rule = serializer.save()
            summary['created'] += 1
        if enable and not rule.is_active:
            if AutomationRule.objects.filter(branch=branch, source=rule.source, is_active=True).exclude(pk=rule.pk).exists():
                summary['conflicts'].append(rule.source)
            else:
                rule = save_rule(actor, {'is_active': True}, rule)
                summary['enabled'] += 1
        summary['rules'].append(rule)
    return summary
