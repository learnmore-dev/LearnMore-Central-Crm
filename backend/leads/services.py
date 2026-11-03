from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from activities.models import Activity
from common.access import require_branch, visible_contacts
from common.permissions import has_global_scope
from .models import Lead


def validate_lead(data):
    if data.get('owner') is None and not data.get('unassigned_reason', '').strip():
        raise ValidationError({'unassigned_reason': 'An unowned enquiry needs an explicit queue reason.'})
    if data.get('owner') is not None and data.get('unassigned_reason', ''):
        raise ValidationError({'unassigned_reason': 'An assigned lead cannot have an unassigned reason.'})
    action, deadline = data.get('next_action', '').strip(), data.get('next_action_at')
    reason = data.get('no_followup_reason', '').strip()
    if bool(action) != bool(deadline):
        raise ValidationError({'next_action': 'Supply both an action and its deadline.'})
    if reason and (action or deadline):
        raise ValidationError({'no_followup_reason': 'Choose a next action or an explicit no-follow-up reason.'})
    if data.get('status', Lead.Status.NEW) not in (Lead.Status.WON, Lead.Status.LOST) and not (reason or (action and deadline)):
        raise ValidationError({'next_action': 'An active lead requires a next action and deadline, or a no-follow-up reason.'})


@transaction.atomic
def create_lead(*, actor, **data):
    from routing.services import lock_branches, policy_for, route_locked
    from datetime import timedelta
    from django.utils import timezone
    data['branch'] = lock_branches([data['branch'].pk])[data['branch'].pk]
    require_branch(actor, data['branch'])
    if not visible_contacts(actor).filter(pk=data['contact'].pk).exists():
        raise PermissionDenied('Contact is outside your branch scope.')
    owner = data.get('owner')
    if owner:
        if not owner.is_active or owner.branch_id != data['branch'].pk or owner.role not in ('counsellor', 'branch_manager'):
            raise ValidationError({'owner': 'Choose an active counsellor or branch manager in the lead branch.'})
        if actor.role == 'counsellor' and not has_global_scope(actor) and owner.pk != actor.pk:
            raise PermissionDenied('Counsellors may only create assignments to themselves.')
    # New enquiries now enter routing automatically; callers may still explicitly
    # request a valid initial owner. Later overrides use audited manager services.
    if 'next_action' not in data and 'no_followup_reason' not in data:
        data['next_action'] = 'Contact new enquiry'
        data['next_action_at'] = timezone.now() + timedelta(minutes=policy_for(data['branch']).followup_minutes)
    if owner is None:
        data.setdefault('unassigned_reason', 'Awaiting initial routing.')
    validate_lead(data)
    data['owner'], data['unassigned_reason'] = None, 'Awaiting initial routing.'
    lead = Lead.objects.create(created_by=actor, **data)
    Activity.objects.create(contact=lead.contact, lead=lead, branch=lead.branch, actor=actor,
        kind=Activity.Kind.LEAD_CREATED, body='Enquiry created: %s.' % lead.title)
    return route_locked(lead, actor=actor, requested_owner=owner, initial=True)


@transaction.atomic
def update_lead(*, actor, lead, **data):
    from routing.services import lock_lead, route_locked, ACTIVE
    from followups.services import sync_assignment_tasks
    lead, _ = lock_lead(lead.pk)
    require_branch(actor, lead.branch)
    if not has_global_scope(actor) and actor.role == 'counsellor' and lead.owner_id != actor.pk:
        raise PermissionDenied('Only the owner or a manager can update this lead.')
    forbidden = set(data) - {'title', 'status', 'next_action', 'next_action_at', 'no_followup_reason'}
    if forbidden:
        raise ValidationError({name: 'Assignments, contact links and branch transfers are immutable here.' for name in forbidden})
    combined = {field: getattr(lead, field) for field in ('owner', 'unassigned_reason', 'status', 'next_action', 'next_action_at', 'no_followup_reason')}
    combined.update(data)
    validate_lead(combined)
    changed = [key for key, value in data.items() if getattr(lead, key) != value]
    if changed:
        was_active = lead.status in ACTIVE
        for key in changed:
            setattr(lead, key, data[key])
        if 'title' in changed:
            from education.models import Qualification
            qualification = Qualification.objects.filter(lead=lead).first()
            if qualification:
                interests = list(qualification.course_interests or [])
                if lead.title not in interests:
                    interests = [lead.title if value == qualification.course_interest else value for value in interests]
                    if lead.title not in interests:
                        if len(interests) >= 20:
                            raise ValidationError({'title': 'Remove a course interest before adding another primary course.'})
                        interests.insert(0, lead.title)
                Qualification.objects.filter(lead=lead).update(course_interest=lead.title, course_interests=interests, updated_by=actor)
        lead.save(update_fields=changed + ['updated_at'])
        Activity.objects.create(contact=lead.contact, lead=lead, branch=lead.branch, actor=actor,
            kind=Activity.Kind.LEAD_UPDATED, body='Updated fields: %s. Status: %s.' % (', '.join(sorted(changed)), lead.status))
        if lead.status in ACTIVE:
            route_locked(lead, actor=actor, renew=not was_active)
        sync_assignment_tasks(lead, actor=actor)
    return lead
