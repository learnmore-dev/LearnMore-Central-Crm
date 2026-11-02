import hashlib
import json
from datetime import timedelta
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from activities.models import Activity
from common.access import require_branch
from common.permissions import has_global_scope
from routing.services import lock_lead, ACTIVE
from .models import Qualification, Demo, DemoTask


def authorize(actor, lead):
    require_branch(actor, lead.branch)
    if not has_global_scope(actor) and actor.role == 'counsellor' and lead.owner_id != actor.pk:
        raise PermissionDenied('Only the enquiry owner or a manager can update student details and demos.')


def event(lead, body, actor=None):
    Activity.objects.create(lead=lead, contact=lead.contact, branch=lead.branch, actor=actor, kind='note', body=body)


@transaction.atomic
def save_qualification(actor, lead, data):
    lead, _ = lock_lead(lead.pk)
    authorize(actor, lead)
    item, _ = Qualification.objects.update_or_create(lead=lead, defaults={**data, 'updated_by': actor})
    event(lead, 'Student qualification updated: ' + ', '.join(sorted(data)) + '.', actor)
    return item


def eligible(lead):
    if lead.status not in ACTIVE or lead.no_followup_reason or not lead.branch.is_active:
        raise ValidationError('Book demos only for active enquiries requiring follow-up.')


def validate_slot(lead, starts_at, duration_minutes, exclude=None):
    if starts_at <= timezone.now():
        raise ValidationError({'starts_at': 'Choose a future demo time.'})
    end = starts_at + timedelta(minutes=duration_minutes)
    rows = Demo.objects.filter(branch=lead.branch, status='scheduled', lead__owner_id=lead.owner_id).exclude(pk=exclude)
    if lead.owner_id:
        # Bounded by the maximum supported three-hour duration, then exact overlap.
        for other in rows.filter(starts_at__lt=end, starts_at__gt=starts_at-timedelta(hours=3)):
            if other.starts_at + timedelta(minutes=other.duration_minutes) > starts_at:
                raise ValidationError('The assigned counsellor already has a demo during this time.')


def sync_tasks(demo, lead, now):
    open_tasks = demo.tasks.filter(status='pending')
    if demo.branch_id != lead.branch_id or lead.status not in ACTIVE or lead.no_followup_reason or not lead.branch.is_active:
        open_tasks.update(status='cancelled', resolution='Enquiry closed, transferred or follow-up disabled.')
        if demo.status == 'scheduled':
            demo.status, demo.outcome = 'cancelled', 'Enquiry closed, transferred or follow-up disabled.'
            demo.save(update_fields=['status', 'outcome'])
            event(lead, f'Demo {demo.pk} cancelled automatically: enquiry no longer eligible.')
        return
    owner = lead.owner_id if lead.owner_id and lead.owner.is_active and lead.owner.branch_id == lead.branch_id else None
    changed = open_tasks.exclude(assignee_id=owner).update(assignee_id=owner)
    if changed:
        event(lead, f'Demo {demo.pk}: {changed} task(s) reassigned to current counsellor or manager queue.')
    open_tasks.exclude(version=demo.version).update(status='cancelled', resolution='Demo rescheduled.')
    if demo.status == 'scheduled':
        pairs = [('reminder', demo.starts_at-timedelta(hours=1)), ('attendance', demo.starts_at+timedelta(minutes=demo.duration_minutes))]
    elif demo.status in ('attended', 'no_show'):
        pairs = [('attended_followup' if demo.status == 'attended' else 'no_show_followup', now+timedelta(hours=24 if demo.status == 'attended' else 1))]
    else:
        pairs = []
        open_tasks.update(status='cancelled', resolution='Demo cancelled.')
    for kind, due in pairs:
        DemoTask.objects.get_or_create(demo=demo, version=demo.version, kind=kind,
            defaults={'assignee_id': owner, 'due_at': due})


@transaction.atomic
def book_demo(actor, lead, **data):
    lead, _ = lock_lead(lead.pk)
    authorize(actor, lead)
    payload = json.dumps({k: str(v) for k, v in sorted(data.items()) if k != 'client_key'}, sort_keys=True)
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    previous = Demo.objects.filter(lead=lead, client_key=data['client_key']).first()
    if previous:
        if previous.request_hash != fingerprint or previous.branch_id != lead.branch_id:
            raise ValidationError('This request key was already used for different demo details.')
        return previous
    eligible(lead)
    if lead.demos.filter(status='scheduled').exists():
        raise ValidationError('Reschedule or cancel the existing demo first.')
    validate_slot(lead, data['starts_at'], data['duration_minutes'])
    DemoTask.objects.filter(demo__lead=lead, kind='no_show_followup', status='pending').update(status='cancelled', resolution='Student rebooked for a new demo.')
    demo = Demo.objects.create(lead=lead, branch=lead.branch, created_by=actor, request_hash=fingerprint, **data)
    sync_tasks(demo, lead, timezone.now())
    event(lead, f'Demo booked: {demo.course}, {demo.starts_at.isoformat()}, {demo.mode}. Staff reminder created; no invitation sent.', actor)
    return demo


@transaction.atomic
def change_demo(actor, demo, *, action, version, reason, starts_at=None, duration_minutes=None, location=None):
    lead, _ = lock_lead(demo.lead_id)
    authorize(actor, lead)
    demo = Demo.objects.select_for_update().get(pk=demo.pk)
    if demo.branch_id != lead.branch_id:
        raise ValidationError('This demo belongs to an earlier branch assignment.')
    if demo.version != version or demo.status != 'scheduled':
        raise ValidationError('The demo has changed. Refresh before recording this action.')
    eligible(lead)
    now = timezone.now()
    if action == 'reschedule':
        if not starts_at:
            raise ValidationError('Choose a new date and time.')
        validate_slot(lead, starts_at, duration_minutes or demo.duration_minutes, demo.pk)
        demo.starts_at = starts_at
        demo.duration_minutes = duration_minutes or demo.duration_minutes
        if location is not None:
            demo.location = location
        demo.version += 1
    elif action in ('attended', 'no_show', 'cancelled'):
        minimum = demo.starts_at + (timedelta(minutes=demo.duration_minutes) if action == 'no_show' else timedelta())
        if action != 'cancelled' and now < minimum:
            raise ValidationError('Attendance cannot be recorded before the demo time has passed.')
        demo.status = action
        demo.tasks.filter(status='pending').update(status='cancelled', resolution='Demo outcome recorded.')
    else:
        raise ValidationError('Choose a supported demo action.')
    demo.outcome = reason
    demo.save()
    sync_tasks(demo, lead, now)
    event(lead, f'Demo {action}: {reason}. Demo ID: {demo.pk}.', actor)
    return demo


@transaction.atomic
def complete_demo_task(actor, task, resolution):
    lead, _ = lock_lead(task.demo.lead_id)
    authorize(actor, lead)
    demo = Demo.objects.select_for_update().get(pk=task.demo_id)
    sync_tasks(demo, lead, timezone.now())
    task = DemoTask.objects.select_for_update().get(pk=task.pk)
    if demo.branch_id != lead.branch_id or task.version != demo.version or task.status == 'cancelled':
        raise ValidationError('This demo task is no longer current.')
    if task.kind == 'attendance':
        raise ValidationError('Record attendance on the demo instead of completing this task.')
    if task.status != 'completed':
        task.status, task.resolution, task.completed_at = 'completed', resolution, timezone.now()
        task.save(update_fields=['status', 'resolution', 'completed_at'])
        event(lead, f'Demo task completed ({task.kind}): {resolution}.', actor)
    return task


def process_demos(limit=200):
    now = timezone.now()
    ids = Demo.objects.filter(Q(status='scheduled') | Q(tasks__status='pending')).distinct().order_by(F('last_checked_at').asc(nulls_first=True), 'starts_at').values_list('pk', flat=True)[:limit]
    checked = 0
    for pk in list(ids):
        with transaction.atomic():
            snapshot = Demo.objects.get(pk=pk)
            lead, _ = lock_lead(snapshot.lead_id)
            demo = Demo.objects.select_for_update().get(pk=pk)
            sync_tasks(demo, lead, now)
            demo.last_checked_at = now
            demo.save(update_fields=['last_checked_at'])
            checked += 1
    return checked
