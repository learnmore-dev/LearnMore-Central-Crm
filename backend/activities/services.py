from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from common.access import require_branch, visible_contacts
from .models import Activity


@transaction.atomic
def add_note(*, actor, contact, branch, body, lead=None):
    require_branch(actor, branch)
    if not visible_contacts(actor).filter(pk=contact.pk).exists():
        raise PermissionDenied('Contact is outside your branch scope.')
    if lead:
        if lead.contact_id != contact.pk or lead.branch_id != branch.pk:
            raise ValidationError({'lead': 'The note must use its lead contact and branch.'})
    elif contact.branch_id != branch.pk and not contact.leads.filter(branch=branch).exists():
        raise ValidationError({'branch': 'The contact has no enquiry in this branch.'})
    return Activity.objects.create(contact=contact, lead=lead, branch=branch, actor=actor,
                                   kind=Activity.Kind.NOTE, body=body)
