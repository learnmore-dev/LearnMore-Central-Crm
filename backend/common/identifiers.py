from django.db import transaction
from .models import IdentifierSequence


def enquiry_branch_code(branch):
    codes = {'kalyan-nagar': 'KN', 'marathahalli': 'MT', 'btm-layout': 'BTM'}
    return codes.get(branch.code, ''.join(c for c in branch.code.upper() if c.isalnum())[:8])


def canonical_identifier_search(value):
    """Historic LM IDs remain searchable after the LMT branding migration."""
    if value.upper().startswith('LM-'):
        return 'LMT' + value[2:]
    return value


def lock_sequence(name):
    # get_or_create handles the unique-key race if a test flush removed seed rows.
    IdentifierSequence.objects.get_or_create(name=name)
    return IdentifierSequence.objects.select_for_update().get(name=name)


@transaction.atomic
def next_identifier(name, prefix):
    sequence = lock_sequence(name)
    sequence.value += 1
    sequence.save(update_fields=['value'])
    return '%s-%06d' % (prefix, sequence.value)
