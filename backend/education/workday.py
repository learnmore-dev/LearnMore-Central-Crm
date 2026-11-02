from datetime import timedelta
from django.db.models import Q, F, Value, CharField
from django.db.models.functions import Cast, Concat, Coalesce
from django.utils import timezone
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from drf_spectacular.utils import extend_schema, OpenApiParameter
from branches.models import Branch
from common.access import branch_scope
from common.enquiries import source_rows
from automation.api import SalesPermission, manager
from automation.models import AutomationTask
from followups.models import FollowUpTask
from leads.models import Lead
from messaging.models import Conversation
from .models import Demo, DemoTask

FIELDS = ['id', 'origin', 'kind', 'name', 'title', 'lead', 'due_at', 'status', 'target']


def text(value):
    return Value(value, output_field=CharField())


def string(field):
    return Cast(F(field), CharField())


def project(rows, **fields):
    return rows.order_by().annotate(**{'work_'+k: fields.get(k, text(None)) for k in FIELDS}).values(*['work_'+k for k in FIELDS])


class WorkdayInput(serializers.Serializer):
    team = serializers.BooleanField(default=False)
    period = serializers.ChoiceField(choices=['due', 'today', 'overdue', 'upcoming', 'all'], default='due')
    kind = serializers.ChoiceField(choices=['followup', 'automation', 'demo', 'appointment', 'reply'], required=False)
    search = serializers.CharField(max_length=200, required=False)
    page = serializers.IntegerField(min_value=1, max_value=100000, default=1)


class WorkdaySerializer(serializers.Serializer):
    server_time = serializers.DateTimeField()
    counts = serializers.DictField(child=serializers.IntegerField())
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    has_next = serializers.BooleanField()
    results = serializers.ListField(child=serializers.DictField())


class WorkdayView(APIView):
    permission_classes = [SalesPermission]

    @extend_schema(responses=WorkdaySerializer, parameters=[OpenApiParameter(n, type=str) for n in ['team', 'period', 'kind', 'search', 'page']])
    def get(self, request):
        query = WorkdayInput(data=request.query_params)
        query.is_valid(raise_exception=True)
        data, user = query.validated_data, request.user
        if data['team'] and not manager(user):
            raise PermissionDenied('Only managers can view the branch team queue.')
        team, now = data['team'], timezone.now()
        ids = branch_scope(Branch.objects.all(), user, 'pk').values('pk')
        leads = Lead.objects.filter(branch_id__in=ids, status__in=['new', 'contacted', 'qualified'], no_followup_reason='')
        if not team:
            leads = leads.filter(owner=user)
        followups = FollowUpTask.objects.filter(branch_id__in=ids, lead__in=leads, assignment_version=F('lead__assignment_version'), status__in=['pending', 'escalated'])
        if not team:
            followups = followups.filter(assignee=user)
        followups = project(followups, id=string('pk'), origin=text('followup'), kind=string('kind'), name=string('lead__contact__full_name'),
            title=string('title'), lead=string('lead_id'), due_at=F('due_at'), status=string('status'), target=Concat(text('/leads/'), string('lead_id')))
        automation = AutomationTask.objects.filter(branch_id__in=ids, status__in=['pending', 'escalated'], run__state__in=['active', 'paused']).filter(Q(run__lead__isnull=True) | Q(run__lead__in=leads))
        if not team:
            automation = automation.filter(assignee=user)
        automation = project(automation, id=string('pk'), origin=text('automation'), kind=text('callback'), name=string('run__name'), title=string('title'),
            lead=string('run__lead_id'), due_at=F('due_at'), status=string('status'), target=text('/automation'))
        demos = Demo.objects.filter(branch_id__in=ids, lead__in=leads)
        tasks = DemoTask.objects.filter(demo__in=demos, status='pending', version=F('demo__version'))
        tasks = project(tasks, id=string('pk'), origin=text('demo'), kind=string('kind'), name=string('demo__lead__contact__full_name'), title=string('demo__course'),
            lead=string('demo__lead_id'), due_at=F('due_at'), status=string('status'), target=Concat(text('/demos?lead='), string('demo__lead_id')))
        appointments = project(demos.filter(status='scheduled'), id=string('pk'), origin=text('appointment'), kind=text('scheduled_demo'), name=string('lead__contact__full_name'), title=string('course'),
            lead=string('lead_id'), due_at=F('starts_at'), status=string('status'), target=Concat(text('/demos?lead='), string('lead_id')))
        chats = Conversation.objects.filter(channel__branch_id__in=ids)
        if not team:
            owned_contacts = leads.values('contact_id')
            chats = chats.filter(Q(contact_id__in=owned_contacts) | Q(automation_run__work_items__assignee=user))
        chat_ids = chats.order_by().annotate(string_id=string('pk')).values('string_id')
        incoming, _ = source_rows(user, list(ids.values_list('pk', flat=True)))
        # source_rows appends WhatsApp last for all authorized sales roles.
        replies = incoming[-1].filter(feed_source='whatsapp', feed_status='awaiting_reply', feed_target_id__in=chat_ids)
        replies = project(replies, id=F('feed_target_id'), origin=text('reply'), kind=text('awaiting_reply'), name=F('feed_name'), title=text('Reply to WhatsApp enquiry'),
            due_at=F('feed_activity_at'), status=F('feed_status'), target=Concat(text('/inbox?conversation='), F('feed_target_id')))
        rows = [followups, automation, tasks, appointments, replies]
        start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start+timedelta(days=1)
        counts = dict(today=0, overdue=0, upcoming=0, all=0)
        filtered = []
        for row in rows:
            if 'kind' in data:
                row = row.filter(work_origin=data['kind'])
            if 'search' in data:
                row = row.filter(Q(work_name__icontains=data['search']) | Q(work_title__icontains=data['search']))
            counts['today'] += row.filter(work_due_at__gte=start, work_due_at__lt=end).count()
            counts['overdue'] += row.filter(work_due_at__lt=now).count()
            counts['upcoming'] += row.filter(work_due_at__gte=end).count()
            counts['all'] += row.count()
            period = data['period']
            row = row.filter(work_due_at__lt=end) if period == 'due' else row.filter(work_due_at__gte=start, work_due_at__lt=end) if period == 'today' else row.filter(work_due_at__lt=now) if period == 'overdue' else row.filter(work_due_at__gte=end) if period == 'upcoming' else row
            filtered.append(row)
        merged = filtered[0].union(*filtered[1:], all=True).order_by('work_due_at', 'work_origin', 'work_id')
        total = sum(row.count() for row in filtered)
        page, size = data['page'], 25
        results = [{k[5:]: v for k, v in row.items()} for row in merged[(page-1)*size:page*size]]
        return Response({'server_time': now, 'counts': counts, 'count': total, 'page': page, 'has_next': page*size < total, 'results': results})
