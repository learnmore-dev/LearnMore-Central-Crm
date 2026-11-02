from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from activities.models import Activity
from branches.models import Branch
from common.access import require_branch, require_manager
from common.permissions import has_global_scope
from leads.models import Lead
from .models import AssignmentHistory, CounsellorProfile, RoutingPolicy

ACTIVE = [Lead.Status.NEW, Lead.Status.CONTACTED, Lead.Status.QUALIFIED]


class RoutingConflict(APIException):
    status_code = 409
    default_detail = 'Lead branch changed concurrently. Refresh and retry.'


def lock_branches(branch_ids):
    # All assignment, capacity, availability and status writes take this lock first.
    return {branch.pk: branch for branch in Branch.objects.select_for_update().filter(
        pk__in=set(branch_ids)).order_by('pk')}


def lock_lead(lead_id, extra_branches=()):
    branch_id = Lead.objects.values_list('branch_id', flat=True).get(pk=lead_id)
    branches = lock_branches([branch_id, *extra_branches])
    lead = Lead.objects.select_for_update().get(pk=lead_id)
    if lead.branch_id not in branches:
        raise RoutingConflict()
    return lead, branches


def policy_for(branch):
    return RoutingPolicy.objects.get_or_create(branch=branch)[0]


def eligible_profiles(lead, exclude_owner=None):
    profiles = CounsellorProfile.objects.select_for_update().select_related('user').filter(
        user__branch_id=lead.branch_id, user__is_active=True,
        user__role__in=['counsellor', 'branch_manager'], is_available=True, can_receive_leads=True).order_by('id')
    eligible = []
    for profile in profiles:
        if profile.user_id == exclude_owner:
            continue
        workload = Lead.objects.filter(owner_id=profile.user_id, status__in=ACTIVE).exclude(pk=lead.pk).count()
        if workload < profile.max_active_leads:
            eligible.append(profile)
    return eligible


def record_event(lead, *, previous_owner_id, previous_branch_id, status, reason, actor):
    AssignmentHistory.objects.create(lead=lead, previous_owner_id=previous_owner_id, new_owner_id=lead.owner_id,
        previous_branch_id=previous_branch_id, branch_id=lead.branch_id, status=status,
        reason=reason, actor=actor, version=lead.assignment_version)
    Activity.objects.create(contact=lead.contact, lead=lead, branch_id=lead.branch_id, actor=actor,
        kind=Activity.Kind.ASSIGNMENT, body='%s: %s' % (status, reason))


def apply_assignment(lead, *, owner, policy, actor, reason, status=None, previous_branch_id=None):
    from followups.services import sync_assignment_tasks
    previous_owner_id = lead.owner_id
    previous_branch_id = previous_branch_id or lead.branch_id
    lead.owner = owner
    lead.unassigned_reason = '' if owner else reason[:500]
    lead.assignment_version += 1
    lead.acknowledged_at = None
    lead.acknowledgement_due_at = timezone.now() + timedelta(minutes=policy.acknowledgement_minutes) if owner else None
    lead.save(update_fields=['owner', 'branch', 'unassigned_reason', 'assignment_version',
                             'acknowledged_at', 'acknowledgement_due_at', 'routing_attempts', 'updated_at'])
    status = status or (AssignmentHistory.Status.ASSIGNED if owner else AssignmentHistory.Status.QUEUED)
    record_event(lead, previous_owner_id=previous_owner_id, previous_branch_id=previous_branch_id,
                 status=status, reason=reason, actor=actor)
    sync_assignment_tasks(lead, actor=actor)
    return lead


def route_locked(lead, *, actor=None, requested_owner=None, exclude_owner=None, initial=False, renew=False, reason='Automatic branch routing'):
    if lead.status not in ACTIVE:
        raise ValidationError({'lead': 'Closed leads cannot be routed.'})
    if not lead.branch.is_active:
        raise ValidationError({'branch': 'Cannot route into an inactive branch.'})
    policy = policy_for(lead.branch)
    profiles = eligible_profiles(lead, exclude_owner=exclude_owner)
    by_user = {profile.user_id: profile for profile in profiles}
    if initial and requested_owner is not None:
        previous = Lead.objects.filter(contact_id=lead.contact_id, branch_id=lead.branch_id,
            status__in=ACTIVE, owner_id__in=by_user).exclude(pk=lead.pk).order_by('-created_at', '-id').first()
        if previous and previous.owner_id != requested_owner.pk:
            raise ValidationError({'owner': 'Preserve the existing eligible enquiry owner; use a reasoned manager override afterward.'})
    if requested_owner is not None:
        if requested_owner.pk not in by_user:
            raise ValidationError({'owner': 'Owner must be available, authorized and below capacity in this branch.'})
        chosen = requested_owner
        reason = 'Explicit initial owner requested by %s.' % actor.pk if actor else 'Explicit initial owner.'
    elif lead.owner_id in by_user and exclude_owner is None:
        if lead.assignment_version and not renew:
            return lead  # preserve ownership, deadlines, acknowledgement and rotation position
        return apply_assignment(lead, owner=by_user[lead.owner_id].user, policy=policy, actor=actor,
                                reason='Existing owner preserved; routing baseline established.')
    else:
        chosen = None
        if initial and exclude_owner is None:
            # Reuse the owner of a relevant active enquiry in this same branch.
            owners = Lead.objects.filter(contact_id=lead.contact_id, branch_id=lead.branch_id,
                status__in=ACTIVE, owner_id__in=by_user).exclude(pk=lead.pk).order_by('-created_at', '-id')
            owner_id = owners.values_list('owner_id', flat=True).first()
            if owner_id:
                chosen = by_user[owner_id].user
        if chosen is None and profiles:
            ordered = [p for p in profiles if p.pk > policy.last_position] + [p for p in profiles if p.pk <= policy.last_position]
            profile = ordered[0]
            chosen = profile.user
            policy.last_position = profile.pk
            policy.save(update_fields=['last_position'])
    if chosen is None:
        reason = 'No eligible counsellor available in this branch.'
        if lead.owner_id is None and lead.assignment_version:
            return lead  # repeated queue retries do not create duplicate alerts/history
    status = AssignmentHistory.Status.REASSIGNED if lead.owner_id and chosen else None
    return apply_assignment(lead, owner=chosen, policy=policy, actor=actor, reason=reason, status=status)


@transaction.atomic
def route_lead(*, lead, actor=None):
    lead, _ = lock_lead(lead.pk)
    if actor:
        require_branch(actor, lead.branch)
    return route_locked(lead, actor=actor)


@transaction.atomic
def manual_assign(*, lead, actor, owner, reason):
    lead, _ = lock_lead(lead.pk)
    require_manager(actor, lead.branch)
    if not reason.strip():
        raise ValidationError({'reason': 'A manual assignment requires a reason.'})
    if lead.status not in ACTIVE:
        raise ValidationError({'lead': 'Closed leads cannot be assigned.'})
    if owner and owner.pk not in {p.user_id for p in eligible_profiles(lead)}:
        raise ValidationError({'owner': 'Owner must be available, authorized and within capacity.'})
    lead.routing_attempts = 0
    return apply_assignment(lead, owner=owner, policy=policy_for(lead.branch), actor=actor,
        reason=reason.strip(), status=AssignmentHistory.Status.REASSIGNED if owner else AssignmentHistory.Status.QUEUED)


@transaction.atomic
def transfer_lead(*, lead, actor, branch, reason):
    if not has_global_scope(actor):
        raise PermissionDenied('Only management can authorize a branch transfer.')
    lead, branches = lock_lead(lead.pk, [branch.pk])
    require_manager(actor, lead.branch)
    branch = branches[branch.pk]
    require_branch(actor, branch)
    if not reason.strip() or branch.pk == lead.branch_id:
        raise ValidationError({'reason': 'Supply a transfer reason and a different destination branch.'})
    if lead.status not in ACTIVE:
        raise ValidationError({'lead': 'Closed leads cannot be transferred.'})
    previous_branch, previous_owner = lead.branch_id, lead.owner_id
    lead.branch = branch
    lead.owner = None
    lead.routing_attempts = 0
    # Choose within the destination; never carry an unauthorized source owner across.
    policy = policy_for(branch)
    profiles = eligible_profiles(lead)
    owner = None
    if profiles:
        ordered = [p for p in profiles if p.pk > policy.last_position] + [p for p in profiles if p.pk <= policy.last_position]
        owner = ordered[0].user
        policy.last_position = ordered[0].pk
        policy.save(update_fields=['last_position'])
    lead.owner_id = previous_owner  # preserve the true previous owner in history
    return apply_assignment(lead, owner=owner, policy=policy, actor=actor, reason=reason.strip(),
        status=AssignmentHistory.Status.TRANSFERRED, previous_branch_id=previous_branch)


@transaction.atomic
def acknowledge(*, lead, actor):
    from followups.models import FollowUpTask
    lead, _ = lock_lead(lead.pk)
    require_branch(actor, lead.branch)
    if lead.owner_id != actor.pk:
        raise PermissionDenied('Only the assigned owner can acknowledge this enquiry.')
    if lead.status not in ACTIVE:
        raise ValidationError({'lead': 'Closed leads cannot be acknowledged.'})
    if lead.acknowledged_at is None:
        lead.acknowledged_at = timezone.now()
        lead.save(update_fields=['acknowledged_at', 'updated_at'])
        lead.tasks.filter(kind=FollowUpTask.Kind.ACKNOWLEDGEMENT, assignment_version=lead.assignment_version,
                          status=FollowUpTask.Status.PENDING).update(status=FollowUpTask.Status.COMPLETED, completed_at=lead.acknowledged_at)
        record_event(lead, previous_owner_id=lead.owner_id, previous_branch_id=lead.branch_id,
            status=AssignmentHistory.Status.ACKNOWLEDGED, reason='Owner acknowledged assignment.', actor=actor)
    return lead


@transaction.atomic
def configure_profile(*, actor, user, **data):
    branches = lock_branches([user.branch_id])
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    if user.branch_id not in branches:
        raise RoutingConflict()
    branch = branches.get(user.branch_id)
    if branch is None or user.role not in ('counsellor', 'branch_manager'):
        raise ValidationError({'user': 'Choose a sales employee with a branch.'})
    require_branch(actor, branch)
    profile = CounsellorProfile.objects.filter(user=user).first()
    manager = has_global_scope(actor) or actor.role == 'branch_manager'
    if not manager and (actor.pk != user.pk or set(data) - {'is_available'} or profile is None):
        raise PermissionDenied('Only a manager can enable routing or change workload limits.')
    if profile is None:
        profile = CounsellorProfile(user=user)
    for key, value in data.items():
        if key not in ('is_available', 'can_receive_leads', 'max_active_leads'):
            raise ValidationError({key: 'Unsupported profile field.'})
        setattr(profile, key, value)
    profile.full_clean()
    profile.save()
    return profile


@transaction.atomic
def configure_policy(*, actor, branch, **data):
    branch = lock_branches([branch.pk])[branch.pk]
    require_manager(actor, branch)
    policy = policy_for(branch)
    for key, value in data.items():
        if key not in ('acknowledgement_minutes', 'followup_minutes', 'max_reassignments'):
            raise ValidationError({key: 'Unsupported policy field.'})
        setattr(policy, key, value)
    policy.full_clean()
    policy.save()
    return policy


def retry_unassigned(limit=100):
    queue = Lead.objects.filter(owner__isnull=True, status__in=ACTIVE, branch__is_active=True)
    branch_ids = list(queue.order_by('branch_id').values_list('branch_id', flat=True).distinct())
    assigned = 0
    for branch_id in branch_ids:
        ids = list(queue.filter(branch_id=branch_id).order_by('created_at', 'id').values_list('pk', flat=True)[:limit])
        for pk in ids:
            try:
                assigned += route_lead(lead=Lead(pk=pk)).owner_id is not None
            except RoutingConflict:
                continue
    return assigned
