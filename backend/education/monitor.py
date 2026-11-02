from datetime import timedelta
from django.db.models import Q, Count
from django.utils import timezone
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from drf_spectacular.utils import extend_schema, OpenApiParameter
from automation.api import SalesPermission, manager
from automation.models import AutomationTask
from branches.models import Branch
from common.access import branch_scope
from common.enquiries import source_rows
from followups.models import FollowUpTask
from leads.models import Lead
from messaging.models import Message
from .models import Demo, DemoTask, JobHealth


class AttentionSerializer(serializers.Serializer):
    server_time = serializers.DateTimeField()
    counts = serializers.DictField(child=serializers.IntegerField())
    alerts = serializers.DictField(child=serializers.ListField(child=serializers.DictField()))
    job = serializers.DictField(allow_null=True)
    source_results = serializers.ListField(child=serializers.DictField())


class AttentionView(APIView):
    permission_classes = [SalesPermission]

    @extend_schema(responses=AttentionSerializer, parameters=[OpenApiParameter('branch', type=str)])
    def get(self, request):
        if not manager(request.user):
            raise PermissionDenied('This monitoring view is for branch managers and management.')
        now = timezone.now()
        branches = branch_scope(Branch.objects.all(), request.user, 'pk')
        if selected := request.query_params.get('branch'):
            pk = serializers.UUIDField().run_validation(selected)
            if not branches.filter(pk=pk).exists():
                raise serializers.ValidationError('Choose a branch in your scope.')
            branches = branches.filter(pk=pk)
        ids = list(branches.values_list('pk', flat=True))
        leads = Lead.objects.filter(branch_id__in=ids)
        active = leads.filter(status__in=['new', 'contacted', 'qualified'], no_followup_reason='')
        counts, alerts = {}, {}

        def collect(key, rows, build):
            counts[key] = rows.count()
            alerts[key] = [build(row) for row in rows[:10]]

        def lead_item(row):
            return {'name': row.contact.full_name, 'title': row.title, 'target': f'/leads/{row.pk}', 'due_at': row.next_action_at}

        collect('unassigned', active.filter(owner__isnull=True).select_related('contact'), lead_item)
        incomplete = Q(qualification__isnull=True) | Q(qualification__course_interest='') | Q(qualification__background='unknown') | Q(qualification__training_mode='undecided') | Q(qualification__joining_timeline='undecided')
        collect('qualification_needed', active.filter(incomplete).select_related('contact'), lead_item)
        collect('admission_ready', active.filter(qualification__readiness='admission_ready').select_related('contact'), lead_item)
        tasks = FollowUpTask.objects.filter(branch_id__in=ids, lead__branch_id__in=ids, lead__status__in=['new', 'contacted', 'qualified'], status__in=['pending', 'escalated'], due_at__lt=now).select_related('lead__contact')
        collect('overdue_followups', tasks, lambda r: {'name': r.lead.contact.full_name, 'title': r.title, 'target': f'/leads/{r.lead_id}', 'due_at': r.due_at})
        tasks = AutomationTask.objects.filter(branch_id__in=ids, run__state__in=['active', 'paused'], status__in=['pending', 'escalated']).filter(Q(run__lead__isnull=True) | Q(run__lead__branch_id__in=ids)).filter(Q(due_at__lt=now) | Q(assignee__isnull=True)).select_related('run')
        collect('callback_attention', tasks, lambda r: {'name': r.run.name, 'title': r.title, 'target': '/my-work', 'due_at': r.due_at})
        tasks = DemoTask.objects.filter(demo__branch_id__in=ids, demo__lead__branch_id__in=ids, demo__lead__status__in=['new', 'contacted', 'qualified'], status='pending', due_at__lt=now).select_related('demo__lead__contact')
        collect('demo_attention', tasks, lambda r: {'name': r.demo.lead.contact.full_name, 'title': r.get_kind_display(), 'target': f'/demos?lead={r.demo.lead_id}', 'due_at': r.due_at})
        messages = Message.objects.filter(conversation__channel__branch_id__in=ids, direction='outbound', queue_status__in=['failed', 'unknown', 'blocked']).select_related('conversation')
        collect('failed_messages', messages, lambda r: {'name': '+' + r.conversation.wa_id, 'title': f'{r.mode}: {r.queue_status}', 'target': f'/inbox?conversation={r.conversation_id}', 'due_at': r.created_at})
        queries, _ = source_rows(request.user, ids)
        counts['awaiting_reply'], alerts['awaiting_reply'] = 0, []
        for rows in queries:
            subset = rows.filter(feed_source='whatsapp', feed_status='awaiting_reply').order_by('feed_activity_at', 'feed_key')
            counts['awaiting_reply'] += subset.count()
            alerts['awaiting_reply'].extend({'name': r['feed_name'], 'title': 'WhatsApp awaiting accepted reply', 'target': '/inbox?conversation=' + r['feed_target_id'], 'due_at': r['feed_activity_at']} for r in subset[:10])
        health = JobHealth.objects.filter(pk='crm_followups').first()
        job = None if not health else {'last_attempt_at': health.last_attempt_at, 'last_success_at': health.last_success_at, 'error_code': health.error_code, 'consecutive_failures': health.consecutive_failures, 'stale': health.last_attempt_at < now-timedelta(minutes=2)}
        source_results = list(leads.filter(created_at__gte=now-timedelta(days=30)).values('source').annotate(enquiries=Count('pk', distinct=True), won=Count('pk', filter=Q(status='won'), distinct=True), demo_booked=Count('pk', filter=Q(demos__isnull=False), distinct=True), demo_attended=Count('pk', filter=Q(demos__status='attended'), distinct=True)).order_by('source'))
        return Response({'server_time': now, 'counts': counts, 'alerts': alerts, 'job': job, 'source_results': source_results})
