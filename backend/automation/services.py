"""Rule-based simulations and staff tasks. No provider transport is imported."""
from datetime import datetime, time, timedelta
from django.db import transaction
from django.db.models import Q, F
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from branches.models import Branch
from calls.models import CallLog
from contacts.models import ContactIdentifier
from leads.models import Lead
from messaging.models import Conversation, Message
from routing.services import eligible_profiles
from common.access import require_manager, require_branch
from common.permissions import has_global_scope
from .models import AutomationRule, AutomationRun, AutomationStep, AutomationTask, AutomationEvent


def audit(run, code, detail, actor=None):
    return AutomationEvent.objects.create(run=run, branch_id=run.branch_id, code=code, detail=detail[:2500], actor=actor)


def business_time(moment, snapshot):
    if not snapshot['business_hours']:
        return moment
    local = timezone.localtime(moment)
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if day.weekday() == 6:  # Sunday is quiet time.
            continue
        start = timezone.make_aware(datetime.combine(day, time(snapshot['start_hour'])))
        end = timezone.make_aware(datetime.combine(day, time())) + timedelta(hours=snapshot['end_hour'])
        candidate = max(local, start)
        if candidate < end:
            return candidate
    raise ValidationError('No business-hours slot is available.')


def render(text, run):
    return text.replace('{name}', run.name).replace('{course}', run.lead.title if run.lead_id else 'our courses').replace('{branch}', run.branch.name)


@transaction.atomic
def save_rule(actor, data, instance=None):
    branch = instance.branch if instance else data['branch']
    Branch.objects.select_for_update().get(pk=branch.pk)
    require_manager(actor, branch)
    if instance:
        instance = AutomationRule.objects.select_for_update().get(pk=instance.pk)
        if 'branch' in data and data['branch'].pk != instance.branch_id:
            raise ValidationError('A rule cannot move between branches.')
    active = data.get('is_active', instance.is_active if instance else False)
    source = data.get('source', instance.source if instance else 'all')
    duplicates = AutomationRule.objects.filter(branch=branch, source=source, is_active=True)
    if instance:
        duplicates = duplicates.exclude(pk=instance.pk)
    if active and duplicates.exists():
        raise ValidationError('Only one active rule per branch/source is allowed.')
    if not instance:
        return AutomationRule.objects.create(**data, created_by=actor, enabled_at=timezone.now() if active else None)
    if active and (not instance.is_active or source != instance.source):
        instance.enabled_at = timezone.now()
    for key, value in data.items():
        setattr(instance, key, value)
    instance.version += 1
    instance.save()
    return instance


def task_owner(run):
    if run.lead_id:
        lead = Lead.objects.get(pk=run.lead_id)
        return lead.owner_id if lead.owner_id and lead.owner.is_active and lead.owner.branch_id == run.branch_id else None
    profiles = eligible_profiles(Lead(branch_id=run.branch_id))
    if not profiles:
        return None
    existing = run.work_items.filter(status__in=['pending', 'escalated'], assignee_id__in=[p.user_id for p in profiles]).values_list('assignee_id', flat=True).first()
    if existing:
        return existing
    return min(profiles, key=lambda p: (AutomationTask.objects.filter(assignee_id=p.user_id,
        status__in=['pending', 'escalated']).count(), p.pk)).user_id


def linked_chats(run):
    if run.conversation_id:
        return Conversation.objects.filter(pk=run.conversation_id)
    contact_id = run.lead.contact_id if run.lead_id else run.call.contact_id
    query = Q(contact_id=contact_id) if contact_id else Q(pk__in=[])
    if run.phone:
        query |= Q(wa_id=run.phone.lstrip('+'))
    return Conversation.objects.filter(query, channel__branch_id=run.branch_id)


def stop(run, reason, *, paused=False, actor=None, now=None, handoff=False):
    now = now or timezone.now()
    state = 'paused' if paused else 'stopped'
    if run.state == state and run.reason == reason:
        return
    run.state, run.reason, run.paused_at = state, reason, now if paused else None
    run.save(update_fields=['state', 'reason', 'paused_at'])
    run.work_items.filter(status__in=['pending', 'escalated']).update(status='cancelled', resolution=reason)
    if not paused:
        run.scheduled_steps.filter(status='pending').update(status='cancelled')
    audit(run, state, reason, actor)
    if handoff:
        AutomationTask.objects.create(run=run, branch_id=run.branch_id, assignee_id=task_owner(run),
            title='Human follow-up: ' + reason[:150], due_at=now+timedelta(minutes=5))


@transaction.atomic
def enroll(*, rule, actor=None, lead=None, call=None, conversation=None, now=None):
    now = now or timezone.now()
    Branch.objects.select_for_update().get(pk=rule.branch_id)
    rule = AutomationRule.objects.select_for_update().get(pk=rule.pk)
    if actor:
        require_manager(actor, rule.branch)
    targets = {key: value for key, value in dict(lead=lead, call=call, conversation=conversation).items() if value is not None}
    if len(targets) != 1:
        raise ValidationError('Choose exactly one enquiry, missed call or conversation.')
    key, target = next(iter(targets.items()))
    target = type(target).objects.get(pk=target.pk)
    lead, call, conversation = (target if key == kind else None for kind in ('lead', 'call', 'conversation'))
    targets = {key: target}
    branch_id = target.channel.branch_id if conversation else target.branch_id
    source = lead.source if lead else 'call' if call else 'whatsapp'
    if branch_id != rule.branch_id or rule.source not in ('all', source):
        raise PermissionDenied('The target is outside this rule’s branch/source.')
    previous = AutomationRun.objects.filter(**{key: target}).first()
    if previous:
        return previous
    if not rule.is_active or not rule.branch.is_active:
        raise ValidationError('Enable an active rule before enrolling an enquiry.')
    if lead and lead.status not in ['new', 'contacted', 'qualified']:
        raise ValidationError('Closed enquiries cannot be enrolled.')
    if lead and lead.no_followup_reason:
        raise ValidationError('This enquiry is marked as requiring no further follow-up.')
    if call and (call.status != 'missed' or call.direction != 'incoming' or call.lead_id):
        raise ValidationError('Choose an unconverted incoming missed call.')
    if conversation and not conversation.messages.filter(direction='inbound').exists():
        raise ValidationError('The conversation must have an inbound message.')
    phone = (ContactIdentifier.objects.filter(contact_id=lead.contact_id, kind='phone').order_by('created_at').values_list('normalized_value', flat=True).first() or '') if lead else call.caller_phone if call else '+' + conversation.wa_id
    name = lead.contact.full_name if lead else call.caller_name or call.caller_phone if call else conversation.contact.full_name if conversation.contact_id else '+' + conversation.wa_id
    snapshot = {field: getattr(rule, field) for field in ['version', 'acknowledgement_minutes', 'acknowledgement_text', 'callback_minutes', 'business_hours', 'start_hour', 'end_hour', 'steps']}
    run = AutomationRun.objects.create(rule=rule, branch_id=rule.branch_id, **targets, snapshot=snapshot, source=source,
        name=name, phone=phone, target_key=phone or 'contact:' + str(lead.contact_id), started_at=now, watch_since=now)
    position = 0
    if not call and snapshot['acknowledgement_text']:
        AutomationStep.objects.create(run=run, position=position, kind='message', title='Initial acknowledgement', body=snapshot['acknowledgement_text'],
            due_at=business_time(now+timedelta(minutes=snapshot['acknowledgement_minutes']), snapshot))
        position += 1
    AutomationStep.objects.create(run=run, position=position, kind='task', title='Callback missed caller' if call else 'Contact new enquiry',
        due_at=now, grace_minutes=snapshot['callback_minutes'])
    if not call:
        for item in snapshot['steps']:
            position += 1
            AutomationStep.objects.create(run=run, position=position, kind=item['kind'], title=item['title'], body=item.get('body', ''),
                due_at=business_time(now+timedelta(minutes=item['delay_minutes']), snapshot), grace_minutes=item.get('grace_minutes', 15))
    audit(run, 'enrolled', f'Mock sequence enrolled using rule version {snapshot["version"]}. No message will be sent.', actor)
    return run


def safety(run, now):
    if run.lead_id and run.lead.no_followup_reason:
        stop(run, 'Enquiry marked as requiring no further follow-up', now=now)
        return False
    if run.lead_id and (run.lead.branch_id != run.branch_id or run.lead.status in ['won', 'lost']):
        stop(run, 'Enquiry closed or transferred to another branch', now=now)
        return False
    if run.call_id and (run.call.branch_id != run.branch_id or run.call.lead_id):
        stop(run, 'Call converted to an enquiry or transferred', now=now)
        return False
    if run.conversation_id and (run.conversation.channel.branch_id != run.branch_id or not run.conversation.channel.is_active):
        stop(run, 'Conversation account disabled or branch changed', now=now)
        return False
    chats = linked_chats(run)
    if chats.filter(consent='revoked').exists():
        stop(run, 'Customer opted out', now=now)
        return False
    if not run.branch.is_active or not run.rule.is_active:
        stop(run, 'Branch or rule disabled', paused=True, now=now)
        return False
    if run.state == 'paused':
        return False
    if Message.objects.filter(conversation__in=chats, direction='inbound', created_at__gt=run.watch_since).exists():
        stop(run, 'Customer replied', paused=True, now=now, handoff=True)
        return False
    if Message.objects.filter(conversation__in=chats, direction='outbound', created_by__isnull=False,
        created_at__gt=run.watch_since).exclude(client_key__startswith='campaign_').exists():
        stop(run, 'Counsellor took over the conversation', paused=True, now=now, handoff=True)
        return False
    return True


@transaction.atomic
def process_run(run_id, now=None):
    now = now or timezone.now()
    branch_id = AutomationRun.objects.values_list('branch_id', flat=True).get(pk=run_id)
    Branch.objects.select_for_update().get(pk=branch_id)
    run = AutomationRun.objects.select_for_update(of=('self',)).select_related('rule', 'branch', 'lead__owner', 'call', 'conversation__channel').get(pk=run_id)
    run.last_checked_at = now
    run.save(update_fields=['last_checked_at'])
    if run.state not in ['active', 'paused']:
        return
    safe = safety(run, now)
    owner = task_owner(run)
    changed = run.work_items.filter(status__in=['pending', 'escalated']).exclude(assignee_id=owner).update(assignee_id=owner)
    if changed:
        audit(run, 'work_reassigned', f'{changed} work item(s) reassigned to {owner or "manager queue"}.')
    if not safe:
        return
    for step in run.scheduled_steps.filter(status='pending', due_at__lte=now).order_by('due_at', 'position'):
        if step.kind == 'message':
            due = business_time(now, run.snapshot)
            if due > now:
                step.due_at = due
                step.save(update_fields=['due_at'])
                audit(run, 'quiet_hours', f'{step.title} deferred until {due.isoformat()}.')
                continue
            day_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
            sent = AutomationEvent.objects.filter(branch_id=run.branch_id, run__target_key=run.target_key, code='message_simulated', created_at__gte=day_start).count()
            if sent >= 2:
                step.due_at = business_time(day_start+timedelta(days=1), run.snapshot)
                step.save(update_fields=['due_at'])
                audit(run, 'frequency_limit', f'{step.title} deferred: maximum two simulations per recipient per day.')
                continue
            step.status = 'simulated'
            audit(run, 'message_simulated', f'{step.title}: {render(step.body, run)} (SIMULATION ONLY — NOT SENT)')
        else:
            AutomationTask.objects.get_or_create(step=step, defaults={'run': run, 'branch_id': run.branch_id, 'assignee_id': owner,
                'title': step.title, 'due_at': business_time(now+timedelta(minutes=step.grace_minutes), run.snapshot)})
            step.status = 'task_created'
            audit(run, 'task_created', f'{step.title}; assigned to {owner or "manager queue"}.')
        step.save(update_fields=['status'])
    if not run.scheduled_steps.filter(status='pending').exists() and not run.work_items.filter(status__in=['pending', 'escalated']).exists():
        run.state, run.reason = 'completed', 'All scheduled steps processed'
        run.save(update_fields=['state', 'reason'])
        audit(run, 'completed', run.reason)


def discover(limit=100):
    """Specific source rules win; enabling a rule never sweeps historic records."""
    rules = list(AutomationRule.objects.filter(is_active=True, branch__is_active=True).select_related('branch'))
    scopes = {(r.branch_id, r.source): r for r in rules}
    count = 0
    for rule in rules:
        targets = [('lead', Lead.objects.filter(branch=rule.branch, status__in=['new', 'contacted', 'qualified'], no_followup_reason='', created_at__gte=rule.enabled_at,
            automation_run__isnull=True)), ('call', CallLog.objects.filter(branch=rule.branch, status='missed', direction='incoming', lead__isnull=True,
            created_at__gte=rule.enabled_at, automation_run__isnull=True)), ('conversation', Conversation.objects.filter(channel__branch=rule.branch,
            messages__direction='inbound', messages__created_at__gte=rule.enabled_at, automation_run__isnull=True, lead__isnull=True).distinct())]
        for kind, rows in targets:
            if kind == 'lead':
                rows = rows.filter(source=rule.source) if rule.source != 'all' else rows.exclude(source__in=[s for (b, s) in scopes if b == rule.branch_id and s != 'all'])
            elif rule.source not in ('all', 'call' if kind == 'call' else 'whatsapp') or (rule.source == 'all' and (rule.branch_id, 'call' if kind == 'call' else 'whatsapp') in scopes):
                continue
            for target in rows.order_by('pk')[:limit]:
                source = target.source if kind == 'lead' else 'call' if kind == 'call' else 'whatsapp'
                chosen = scopes.get((rule.branch_id, source), scopes.get((rule.branch_id, 'all')))
                if chosen and chosen.pk == rule.pk:
                    try:
                        enroll(rule=rule, **{kind: target})
                        count += 1
                    except (ValidationError, PermissionDenied):
                        continue
    return count


def process_automations(now=None, limit=200):
    now = now or timezone.now()
    discovered = discover()
    ids = list(AutomationRun.objects.filter(state__in=['active', 'paused']).order_by(F('last_checked_at').asc(nulls_first=True), 'started_at').values_list('pk', flat=True)[:limit])
    for pk in ids:
        process_run(pk, now)
    # Completed sequences can still have open tasks; escalate once without sending anything.
    for task_id in AutomationTask.objects.filter(status='pending', due_at__lt=now).values_list('pk', flat=True)[:limit]:
        with transaction.atomic():
            task = AutomationTask.objects.select_for_update().select_related('run').get(pk=task_id)
            if task.status != 'pending':
                continue
            task.status, task.escalated_at = 'escalated', now
            task.save(update_fields=['status', 'escalated_at'])
            audit(task.run, 'task_overdue', f'Manager attention required: {task.title}.')
    return {'enrolled': discovered, 'checked': len(ids)}


@transaction.atomic
def control_run(*, actor, run, action, reason):
    if action not in ('pause', 'resume', 'stop'):
        raise ValidationError('Choose pause, resume or stop.')
    Branch.objects.select_for_update().get(pk=run.branch_id)
    run = AutomationRun.objects.select_for_update(of=('self',)).select_related('rule', 'branch', 'lead', 'call', 'conversation__channel').get(pk=run.pk)
    require_branch(actor, run.branch)
    if not has_global_scope(actor) and actor.role != 'branch_manager' and (not run.lead_id or run.lead.owner_id != actor.pk):
        raise PermissionDenied('Only the owner or a manager may control this sequence.')
    if not reason.strip():
        raise ValidationError('An explicit reason is required.')
    now = timezone.now()
    if action == 'resume':
        require_manager(actor, run.branch)
        if run.state != 'paused' or not run.rule.is_active:
            raise ValidationError('Only paused sequences with enabled rules can resume.')
        if run.lead_id and (run.lead.status in ['won', 'lost'] or run.lead.branch_id != run.branch_id) or linked_chats(run).filter(consent='revoked').exists():
            raise ValidationError('Resolve closure, branch transfer or opt-out before resuming.')
        if not run.branch.is_active or (run.call_id and (run.call.lead_id or run.call.branch_id != run.branch_id)) or (run.conversation_id and (not run.conversation.channel.is_active or run.conversation.channel.branch_id != run.branch_id)):
            raise ValidationError('This target is no longer eligible for automation.')
        delay = now - (run.paused_at or now)
        for step in run.scheduled_steps.filter(status='pending'):
            step.due_at = business_time(max(now, step.due_at+delay), run.snapshot)
            step.save(update_fields=['due_at'])
        run.work_items.filter(step__isnull=True, status__in=['pending', 'escalated']).update(status='cancelled', resolution='Sequence resumed by manager')
        for task in run.work_items.filter(step__isnull=False, status='cancelled'):
            task.status, task.resolution, task.escalated_at = 'pending', '', None
            task.due_at = business_time(max(now, task.due_at+delay), run.snapshot)
            task.assignee_id = task_owner(run)
            task.save(update_fields=['status', 'resolution', 'escalated_at', 'due_at', 'assignee'])
        run.state, run.reason, run.paused_at, run.watch_since = 'active', reason.strip(), None, now
        run.save(update_fields=['state', 'reason', 'paused_at', 'watch_since'])
        audit(run, 'resumed', reason, actor)
    elif run.state in ['active', 'paused']:
        stop(run, reason.strip(), paused=action == 'pause', actor=actor, now=now)
    else:
        raise ValidationError('This sequence is already terminal.')
    return run


@transaction.atomic
def complete_task(*, actor, task, resolution):
    Branch.objects.select_for_update().get(pk=task.branch_id)
    process_run(task.run_id)
    task = AutomationTask.objects.select_for_update().select_related('run', 'branch').get(pk=task.pk)
    require_branch(actor, task.branch)
    if not has_global_scope(actor) and actor.role != 'branch_manager' and task.assignee_id != actor.pk:
        raise PermissionDenied('Only the assignee or a manager can complete this work item.')
    if task.status == 'completed':
        return task
    if task.status == 'cancelled' or not resolution.strip():
        raise ValidationError('Record an outcome for an open work item.')
    task.status, task.completed_at, task.resolution = 'completed', timezone.now(), resolution.strip()
    task.save(update_fields=['status', 'completed_at', 'resolution'])
    audit(task.run, 'task_completed', f'{task.title}: {resolution}', actor)
    return task
