import uuid
import hashlib
from datetime import UTC
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from activities.models import Activity
from common.access import require_branch
from common.permissions import has_global_scope
from routing.models import AssignmentHistory
from routing.services import ACTIVE, lock_lead, policy_for, record_event, route_locked, RoutingConflict
from .models import FollowUpTask


def sync_assignment_tasks(lead, actor=None):
    lead.tasks.filter(status=FollowUpTask.Status.PENDING).exclude(assignment_version=lead.assignment_version).update(
        status=FollowUpTask.Status.CANCELLED, resolution='Assignment superseded.')
    if lead.status not in ACTIVE:
        lead.tasks.filter(status=FollowUpTask.Status.PENDING).update(status=FollowUpTask.Status.CANCELLED, resolution='Lead closed.')
        return
    version = lead.assignment_version
    if lead.owner_id:
        if lead.acknowledged_at is None and lead.acknowledgement_due_at:
            FollowUpTask.objects.get_or_create(dedupe_key='ack:%s:%s' % (lead.pk, version), defaults={
                'lead': lead, 'branch': lead.branch, 'assignee_id': lead.owner_id,
                'kind': FollowUpTask.Kind.ACKNOWLEDGEMENT, 'title': 'Acknowledge enquiry assignment',
                'due_at': lead.acknowledgement_due_at, 'assignment_version': version, 'created_by': actor})
    else:
        FollowUpTask.objects.get_or_create(dedupe_key='queue:%s:%s' % (lead.pk, version), defaults={
            'lead': lead, 'branch': lead.branch, 'kind': FollowUpTask.Kind.UNASSIGNED,
            'title': 'Manager action required: no eligible counsellor', 'due_at': timezone.now(),
            'assignment_version': version, 'created_by': actor})
    key_prefix = 'followup:%s:%s:' % (lead.pk, version)
    if lead.next_action and lead.next_action_at and lead.owner_id:
        fingerprint = hashlib.sha256(('%s|%s' % (lead.next_action, lead.next_action_at.astimezone(UTC).isoformat())).encode()).hexdigest()[:24]
        key = key_prefix + fingerprint
        lead.tasks.filter(dedupe_key__startswith=key_prefix, status=FollowUpTask.Status.PENDING).exclude(dedupe_key=key).update(
            status=FollowUpTask.Status.CANCELLED, resolution='Next action superseded.')
        task, created = FollowUpTask.objects.get_or_create(dedupe_key=key, defaults={
            'lead': lead, 'branch': lead.branch, 'assignee_id': lead.owner_id,
            'kind': FollowUpTask.Kind.FOLLOW_UP, 'title': lead.next_action, 'due_at': lead.next_action_at,
            'assignment_version': version, 'created_by': actor})
        if not created and task.status == FollowUpTask.Status.CANCELLED:
            task.title, task.due_at, task.status = lead.next_action, lead.next_action_at, FollowUpTask.Status.PENDING
            task.completed_at, task.resolution = None, ''
            task.save(update_fields=['title', 'due_at', 'status', 'completed_at', 'resolution'])
    else:
        lead.tasks.filter(dedupe_key__startswith=key_prefix, status=FollowUpTask.Status.PENDING).update(
            status=FollowUpTask.Status.CANCELLED, resolution='No follow-up required or lead unassigned.')


def manager_alert(lead, *, key, title, now):
    return FollowUpTask.objects.get_or_create(dedupe_key=key, defaults={'lead': lead, 'branch': lead.branch,
        'kind': FollowUpTask.Kind.ESCALATION, 'title': title, 'due_at': now,
        'assignment_version': lead.assignment_version})[0]


@transaction.atomic
def process_task(task_id, now):
    snapshot = FollowUpTask.objects.get(pk=task_id)
    lead, _ = lock_lead(snapshot.lead_id)
    task = FollowUpTask.objects.select_for_update().get(pk=task_id)
    if task.status != FollowUpTask.Status.PENDING or task.due_at > now:
        return False
    if task.assignment_version != lead.assignment_version or lead.status not in ACTIVE:
        task.status, task.resolution = FollowUpTask.Status.CANCELLED, 'Obsolete assignment or closed lead.'
        task.save(update_fields=['status', 'resolution'])
        return True
    task.status, task.resolution = FollowUpTask.Status.ESCALATED, 'SLA deadline exceeded.'
    task.save(update_fields=['status', 'resolution'])
    if task.kind in (FollowUpTask.Kind.UNASSIGNED, FollowUpTask.Kind.ESCALATION):
        return True  # durable manager alert; never recursively escalate an alert
    Activity.objects.create(contact=lead.contact, lead=lead, branch=lead.branch,
        kind=Activity.Kind.SLA_ESCALATED, body='Overdue %s task: %s.' % (task.kind, task.pk))
    if task.kind == FollowUpTask.Kind.ACKNOWLEDGEMENT:
        if lead.acknowledged_at:
            task.status, task.completed_at = FollowUpTask.Status.COMPLETED, lead.acknowledged_at
            task.save(update_fields=['status', 'completed_at'])
            return True
        record_event(lead, previous_owner_id=lead.owner_id, previous_branch_id=lead.branch_id,
            status=AssignmentHistory.Status.ESCALATED, reason='Assignment acknowledgement deadline exceeded.', actor=None)
        policy = policy_for(lead.branch)
        if lead.routing_attempts < policy.max_reassignments and lead.branch.is_active:
            previous_owner = lead.owner_id
            lead.routing_attempts += 1
            route_locked(lead, exclude_owner=previous_owner, reason='SLA reassignment: acknowledgement overdue.')
    manager_alert(lead, key='sla-alert:%s' % task.pk, title='Manager review: overdue %s' % task.kind, now=now)
    return True


def process_slas(now=None, limit=200):
    now = now or timezone.now()
    ids = list(FollowUpTask.objects.filter(status=FollowUpTask.Status.PENDING, due_at__lte=now)
               .order_by('due_at', 'id').values_list('pk', flat=True)[:limit])
    processed = 0
    for task_id in ids:
        try:
            processed += process_task(task_id, now)
        except RoutingConflict:
            continue  # retry next scheduler tick after a concurrent branch transfer
    return processed


@transaction.atomic
def create_task(*, actor, lead, kind, title, due_at):
    lead, _ = lock_lead(lead.pk)
    require_branch(actor, lead.branch)
    if not has_global_scope(actor) and actor.role == 'counsellor' and lead.owner_id != actor.pk:
        raise PermissionDenied('Only an owner or manager can schedule this task.')
    if kind not in (FollowUpTask.Kind.FOLLOW_UP, FollowUpTask.Kind.CALLBACK, FollowUpTask.Kind.APPOINTMENT):
        raise ValidationError({'kind': 'Only follow-up, callback and appointment tasks may be created manually.'})
    if lead.status not in ACTIVE or not lead.owner_id:
        raise ValidationError({'lead': 'A task requires an active assigned lead.'})
    return FollowUpTask.objects.create(lead=lead, branch=lead.branch, assignee_id=lead.owner_id,
        kind=kind, title=title, due_at=due_at, assignment_version=lead.assignment_version,
        created_by=actor, dedupe_key='manual:%s' % uuid.uuid4())


@transaction.atomic
def complete_task(*, actor, task, resolution, **next_plan):
    lead, _ = lock_lead(task.lead_id)
    task = FollowUpTask.objects.select_for_update().get(pk=task.pk)
    require_branch(actor, lead.branch)
    if task.branch_id != lead.branch_id or task.assignment_version != lead.assignment_version:
        raise ValidationError({'task': 'Task belongs to a superseded assignment.'})
    if not has_global_scope(actor) and actor.role != 'branch_manager' and task.assignee_id != actor.pk:
        raise PermissionDenied('Only the assignee or a manager may complete this task.')
    if task.kind == FollowUpTask.Kind.ACKNOWLEDGEMENT:
        raise ValidationError({'task': 'Use the assignment acknowledgement endpoint.'})
    if not resolution.strip():
        raise ValidationError({'resolution': 'Supply an outcome.'})
    if task.status == FollowUpTask.Status.COMPLETED:
        return task
    if task.status == FollowUpTask.Status.CANCELLED:
        raise ValidationError({'task': 'Cancelled tasks cannot be completed.'})
    if task.dedupe_key.startswith('followup:') or next_plan:
        from leads.services import validate_lead
        if not next_plan:
            raise ValidationError({'next_action': 'Supply the next action/deadline or a no-follow-up reason.'})
        plan = {'next_action': '', 'next_action_at': None, 'no_followup_reason': ''}
        plan.update(next_plan)
        validate_lead(dict(plan, owner=lead.owner, status=lead.status, unassigned_reason=lead.unassigned_reason))
        if plan == {key: getattr(lead, key) for key in plan}:
            raise ValidationError({'next_action': 'Choose a new action/deadline or a no-follow-up reason.'})
    else:
        plan = None
    task.status, task.completed_at, task.resolution = FollowUpTask.Status.COMPLETED, timezone.now(), resolution.strip()
    task.save(update_fields=['status', 'completed_at', 'resolution'])
    Activity.objects.create(contact=lead.contact, lead=lead, branch=lead.branch, actor=actor,
        kind=Activity.Kind.TASK_COMPLETED, body='Task %s completed: %s' % (task.pk, resolution.strip()))
    if plan:
        from leads.services import update_lead
        update_lead(actor=actor, lead=lead, **plan)
    return task
