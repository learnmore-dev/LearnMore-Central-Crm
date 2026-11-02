"""Due-date accountability reports. Counts describe recorded work, never inferred effort."""
import csv
from datetime import datetime, time, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, F, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter

from automation.api import SalesPermission, manager
from automation.models import AutomationTask
from branches.models import Branch
from calls.models import CallLog
from common.access import branch_scope
from common.deadlines import capture_deadlines, task_details
from education.models import DemoTask
from leads.models import Lead
from messaging.models import Message
from .models import DeadlineMiss, FollowUpTask

TASK_MODELS = (FollowUpTask, AutomationTask, DemoTask)
METRICS = ('assigned', 'due', 'pending', 'overdue', 'completed_on_time', 'completed_late', 'missed_deadline', 'no_contact', 'unanswered')


def snapshot_deadlines():
    active = ['new', 'contacted', 'qualified']
    capture_deadlines(FollowUpTask.objects.filter(
        Q(status='completed') | Q(lead__status__in=active, lead__no_followup_reason='',
            branch_id=F('lead__branch_id'), assignment_version=F('lead__assignment_version'))))
    capture_deadlines(AutomationTask.objects.filter(Q(status='completed') |
        (Q(run__state__in=['active', 'paused']) & (Q(run__lead__isnull=True) |
            Q(run__lead__status__in=active, run__lead__no_followup_reason='', branch_id=F('run__lead__branch_id'))))))
    capture_deadlines(DemoTask.objects.filter(Q(status='completed') |
        Q(demo__lead__status__in=active, demo__lead__no_followup_reason='',
            demo__branch_id=F('demo__lead__branch_id'), version=F('demo__version'))))
    return 'recorded'


class ReportInput(serializers.Serializer):
    team = serializers.BooleanField(default=False)
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    branch = serializers.UUIDField(required=False)
    owner = serializers.UUIDField(required=False)
    category = serializers.ChoiceField(choices=['all', 'overdue', 'pending', 'completed_on_time', 'completed_late', 'missed_deadline', 'no_contact', 'unanswered'], default='overdue')
    page = serializers.IntegerField(min_value=1, max_value=100000, default=1)
    export = serializers.ChoiceField(choices=['csv'], required=False)

    def validate(self, data):
        data.setdefault('end', timezone.localdate())
        data.setdefault('start', data['end'] - timedelta(days=29))
        if data['start'] > data['end'] or (data['end'] - data['start']).days > 92:
            raise serializers.ValidationError('Choose an ordered date range of at most 93 days.')
        if data['end'].year == 9999:
            raise serializers.ValidationError('Choose an end date before year 9999.')
        return data


class FollowUpReportSerializer(serializers.Serializer):
    server_time = serializers.DateTimeField()
    start = serializers.DateField()
    end = serializers.DateField()
    counsellors = serializers.ListField(child=serializers.DictField())
    totals = serializers.DictField(child=serializers.IntegerField())
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    has_next = serializers.BooleanField()
    results = serializers.ListField(child=serializers.DictField())


class FollowUpReportView(APIView):
    permission_classes = [SalesPermission]

    @extend_schema(responses=FollowUpReportSerializer, parameters=[OpenApiParameter(n, type=str) for n in ['team', 'start', 'end', 'branch', 'owner', 'category', 'page', 'export']])
    def get(self, request):
        query = ReportInput(data=request.query_params)
        query.is_valid(raise_exception=True)
        data, user, now = query.validated_data, request.user, timezone.now()
        if data['team'] and not manager(user):
            raise PermissionDenied('Only managers can view counsellor-wise team reports.')
        branches = branch_scope(Branch.objects.all(), user, 'pk')
        if 'branch' in data:
            if not branches.filter(pk=data['branch']).exists():
                raise serializers.ValidationError('Choose an authorized branch.')
            branches = branches.filter(pk=data['branch'])
        branch_ids = set(branches.values_list('pk', flat=True))
        owners = get_user_model().objects.filter(branch_id__in=branch_ids, role__in=['counsellor', 'branch_manager'])
        # Include historical assignees who moved branches and global managers with tasks.
        historical = set()
        for model, field in [(FollowUpTask, 'branch_id'), (AutomationTask, 'branch_id'), (DemoTask, 'demo__branch_id'), (DeadlineMiss, 'branch_id')]:
            historical.update(model.objects.filter(**{field+'__in': branch_ids}).exclude(assignee=None).values_list('assignee_id', flat=True))
        owners = get_user_model().objects.filter(pk__in=set(owners.values_list('pk', flat=True)) | historical | {user.pk}).order_by('username')
        if not data['team']:
            if 'owner' in data and data['owner'] != user.pk:
                raise PermissionDenied('You may only view your own report.')
            owners = owners.filter(pk=user.pk)
        elif 'owner' in data:
            if not owners.filter(pk=data['owner']).exists():
                raise serializers.ValidationError('Choose an authorized counsellor.')
            owners = owners.filter(pk=data['owner'])
        owner_map = {o.pk: o for o in owners}
        start = timezone.make_aware(datetime.combine(data['start'], time()))
        end = timezone.make_aware(datetime.combine(data['end'] + timedelta(days=1), time()))
        summary = {str(pk): dict(owner=str(pk), name=o.get_full_name() or o.username, **dict.fromkeys(METRICS, 0)) for pk, o in owner_map.items()}
        if data['team'] and 'owner' not in data:
            summary['unassigned'] = dict(owner='', name='Unassigned / manager queue', **dict.fromkeys(METRICS, 0))
        details, tasks_by_key, missed = [], {}, set()

        def owner_key(pk):
            return str(pk) if pk else 'unassigned'

        def add_detail(values, pk, category, **extra):
            key = owner_key(pk)
            if key not in summary:
                return
            due = values['due_at']
            details.append(dict(origin=values['origin'], task=str(values.get('task_id', '')), lead=str(values['lead_id']) if values.get('lead_id') else None,
                name=values['name'], course=values['course'], title=values['title'], owner=summary[key]['name'], owner_id=str(pk) if pk else '',
                category=category, due_at=due, delay_minutes=max(0, int(((extra.get('completed_at') or now)-due).total_seconds()//60)),
                target=values['target'] if not values.get('lead_id') or values.get('lead_branch_id', values['branch'].pk) in branch_ids else '', **extra))

        for model in TASK_MODELS:
            field = 'demo__branch_id' if model == DemoTask else 'branch_id'
            rows = model.objects.filter(**{field+'__in': branch_ids})
            if not data['team'] or 'owner' in data:
                rows = rows.filter(assignee_id__in=owner_map)
            related = ['lead__contact', 'lead__branch', 'branch'] if model == FollowUpTask else ['run__lead', 'run__branch', 'branch'] if model == AutomationTask else ['demo__lead__contact', 'demo__branch']
            for task in rows.filter(due_at__gte=start, due_at__lt=end).select_related(*related).iterator():
                values = task_details(task)
                lead = task.lead if model == FollowUpTask else task.run.lead if model == AutomationTask else task.demo.lead
                values['lead_branch_id'] = lead.branch_id if lead else None
                key, task_key = owner_key(task.assignee_id), (values['origin'], task.pk)
                if key not in summary:
                    continue
                tasks_by_key[task_key] = (task, values)
                if task.status == 'completed' and task.completed_at:
                    category = 'completed_late' if task.completed_at > task.due_at else 'completed_on_time'
                elif task.status in ('pending', 'escalated'):
                    # Obsolete work is not presented as a current personal reminder.
                    current = (not lead or (lead.branch_id == values['branch'].pk and lead.status in ('new', 'contacted', 'qualified') and not lead.no_followup_reason))
                    if model == FollowUpTask:
                        current = current and task.assignment_version == lead.assignment_version
                    elif model == DemoTask:
                        current = current and task.version == task.demo.version
                    else:
                        current = current and task.run.state in ('active', 'paused')
                    if not current:
                        continue
                    category = 'overdue' if task.due_at < now else 'pending'
                else:
                    continue
                summary[key]['due'] += 1
                summary[key][category] += 1
                add_detail(values, task.assignee_id, category, status=task.status, completed_at=task.completed_at, resolution=task.resolution)
                if category in ('overdue', 'completed_late'):
                    missed.add(task_key)

        # Saved snapshots retain the original assignee/deadline after cancellation or reassignment.
        snapshots = list(DeadlineMiss.objects.filter(branch_id__in=branch_ids, due_at__gte=start, due_at__lt=end).select_related('branch', 'lead'))
        task_states = {}
        for model in TASK_MODELS:
            for pk, task in model.objects.in_bulk([s.task_id for s in snapshots if s.origin == model._meta.app_label]).items():
                task_states[(model._meta.app_label, pk)] = task
        snapshot_keys = set()
        for item in snapshots:
            key, task_key = owner_key(item.assignee_id), (item.origin, item.task_id)
            snapshot_keys.add(task_key)
            if key not in summary:
                continue
            summary[key]['missed_deadline'] += 1
            values = {name: getattr(item, name) for name in ('origin', 'task_id', 'branch', 'lead_id', 'name', 'course', 'title', 'target', 'due_at')}
            values['lead_branch_id'] = item.lead.branch_id if item.lead else None
            current_task = task_states.get(task_key)
            add_detail(values, item.assignee_id, 'missed_deadline',
                status=current_task.status if current_task else 'recorded',
                completed_at=current_task.completed_at if current_task else None,
                resolution='Deadline miss retained for original assignee.')
        for task_key in missed - snapshot_keys:
            task, values = tasks_by_key[task_key]
            summary[owner_key(task.assignee_id)]['missed_deadline'] += 1
            add_detail(values, task.assignee_id, 'missed_deadline', status=task.status, completed_at=task.completed_at, resolution=task.resolution)

        leads = Lead.objects.filter(branch_id__in=branch_ids, status__in=['new', 'contacted', 'qualified'], no_followup_reason='')
        if not data['team'] or 'owner' in data:
            leads = leads.filter(owner_id__in=owner_map)
        for pk in summary:
            summary[pk]['assigned'] = leads.filter(owner_id=None if pk == 'unassigned' else pk).count()
        calls = CallLog.objects.filter(branch_id=OuterRef('branch_id'), contact_id=OuterRef('contact_id'), started_at__gte=OuterRef('received_at'))
        messages = Message.objects.filter(conversation__channel__branch_id=OuterRef('branch_id'), conversation__contact_id=OuterRef('contact_id'), direction='outbound', mode='live', queue_status='sent', created_by__isnull=False, occurred_at__gte=OuterRef('received_at'))
        fresh = leads.filter(status='new', received_at__gte=start, received_at__lt=end).annotate(
            attempted=Exists(calls.filter(direction='outgoing')), answered=Exists(calls.filter(status='answered')),
            unanswered=Exists(calls.filter(direction='outgoing', status='missed')), messaged=Exists(messages))
        for lead in fresh.select_related('contact', 'branch').iterator():
            key = owner_key(lead.owner_id)
            if key not in summary or lead.answered or lead.messaged:
                continue
            category = 'unanswered' if lead.unanswered else 'no_contact' if not lead.attempted else None
            if category:
                summary[key][category] += 1
                add_detail(dict(origin='enquiry', lead_id=lead.pk, name=lead.contact.full_name, course=lead.title,
                    title='Unanswered outgoing call recorded' if category == 'unanswered' else 'No contact attempt recorded',
                    target=f'/leads/{lead.pk}', branch=lead.branch, due_at=lead.received_at), lead.owner_id, category,
                    status=lead.status, completed_at=None, resolution='')
        selected = [row for row in details if data['category'] == 'all' or row['category'] == data['category']]
        selected.sort(key=lambda row: (row['due_at'], row['origin'], row['task']))
        if data.get('export') == 'csv':
            if len(selected) > 10000:
                raise serializers.ValidationError('Export is limited to 10,000 rows; narrow the filters.')
            buffer = StringIO()
            fields = ['owner', 'name', 'course', 'title', 'origin', 'category', 'due_at', 'delay_minutes', 'status', 'completed_at', 'resolution']
            writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in selected:
                # Prevent spreadsheet formula execution in user-entered values.
                writer.writerow({k: ("'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else timezone.localtime(v).isoformat() if isinstance(v, datetime) else v) for k, v in row.items() if k in fields})
            response = HttpResponse('\ufeff'+buffer.getvalue(), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="learnmore-follow-up-report.csv"'
            return response
        page, size = data['page'], 25
        return Response(dict(server_time=now, start=data['start'], end=data['end'], counsellors=list(summary.values()),
            totals={metric: sum(row[metric] for row in summary.values()) for metric in METRICS}, count=len(selected),
            page=page, has_next=page*size < len(selected), results=selected[(page-1)*size:page*size]))
