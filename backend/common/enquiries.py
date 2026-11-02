"""A read-only, permission-scoped live feed across existing intake records."""
from datetime import timedelta
from django.conf import settings
from django.db.models import Q, F, Value, CharField, Case, When, Count, Exists, OuterRef, Subquery
from django.db.models.functions import Cast, Coalesce, Concat, NullIf
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from branches.models import Branch
from calls.models import CallLog
from contacts.models import ContactIdentifier
from intake.models import WebsiteSubmission
from leads.models import Lead
from messaging.models import Conversation, Message
from .access import branch_scope, visible_contacts
from .permissions import has_global_scope

STATES = ['new', 'contacted', 'qualified', 'won', 'lost', 'unassigned', 'review', 'rejected', 'needs_enquiry', 'awaiting_reply', 'replied', 'transferred']
FIELDS = ['key', 'source', 'source_label', 'name', 'phone', 'title', 'preview', 'branch', 'branch_name', 'status',
          'owner_name', 'lead', 'lead_label', 'contact', 'received_at', 'activity_at', 'target', 'target_id']


def text(value):
    return Value(value, output_field=CharField())


def string(field):
    return Cast(F(field), output_field=CharField())


def choose(condition, value, otherwise=None):
    return Case(When(condition, then=value), default=text(otherwise), output_field=CharField())


def project(rows, **columns):
    # Identical field order/types make this a bounded, database-paginated UNION.
    return rows.order_by().annotate(**{'feed_' + key: columns.get(key, text(None)) for key in FIELDS}).values(*['feed_' + key for key in FIELDS])


def source_rows(user, branch_ids):
    contacts = visible_contacts(user).values('pk')
    accessible_branches = branch_scope(Branch.objects.all(), user, 'pk').values('pk')
    visible_lead = Q(lead__branch_id__in=accessible_branches)
    lead_state = Case(
        When(lead__isnull=True, then=text('needs_enquiry')),
        When(~visible_lead, then=text('transferred')),
        When(lead__status__in=['won', 'lost'], then=string('lead__status')),
        When(lead__owner__isnull=True, then=text('unassigned')),
        default=string('lead__status'), output_field=CharField())
    linked = dict(owner_name=choose(visible_lead, string('lead__owner__username')),
                  lead=choose(visible_lead, string('lead_id')), lead_label=choose(visible_lead, string('lead__lead_id')))
    website = project(WebsiteSubmission.objects.filter(branch_id__in=branch_ids),
        key=Concat(text('website:'), string('pk')), source=text('website'),
        source_label=Case(When(source__slug='learnmoretech', then=text('learnmoretech.in')), default=text('learnmoretechnologies.in')),
        name=string('full_name'), phone=Coalesce(NullIf(string('phone'), text('')), string('email')),
        title=Coalesce(NullIf(string('course'), text('')), text('Website enquiry')), preview=string('message'),
        branch=string('branch_id'), branch_name=string('branch__name'),
        status=Case(When(status__in=['review', 'rejected'], then=string('status')), default=lead_state, output_field=CharField()),
        contact=choose(visible_lead & Q(lead__contact_id__in=contacts), string('lead__contact_id')),
        received_at=F('created_at'), activity_at=F('created_at'), target=text('website'), target_id=string('pk'), **linked)
    calls = project(CallLog.objects.filter(branch_id__in=branch_ids, direction='incoming'),
        key=Concat(text('call:'), string('pk')), source=text('call'), source_label=Concat(text('Incoming call · '), string('status')),
        name=Coalesce(choose(Q(contact_id__in=contacts), string('contact__full_name')),
            NullIf(string('caller_name'), text('')), string('caller_phone')), phone=string('caller_phone'),
        title=text('Phone enquiry'), preview=string('notes'), branch=string('branch_id'), branch_name=string('branch__name'),
        status=Case(When(contact__isnull=True, review__status='rejected', then=text('rejected')),
            When(contact__isnull=True, then=text('review')), default=lead_state, output_field=CharField()),
        contact=choose(Q(contact_id__in=contacts), string('contact_id')), received_at=F('started_at'), activity_at=F('created_at'),
        target=text('call'), target_id=string('caller_phone'), **linked)
    phone = ContactIdentifier.objects.filter(contact_id=OuterRef('contact_id'), kind='phone').order_by('created_at').values('normalized_value')[:1]
    leads = project(Lead.objects.filter(Q(origin_call__isnull=True) | Q(origin_call__direction='outgoing'), branch_id__in=branch_ids, website_submission__isnull=True),
        key=Concat(text('lead:'), string('pk')), source=string('source'), source_label=Concat(text('Enquiry · '), string('source')),
        name=string('contact__full_name'), phone=Subquery(phone), title=string('title'), preview=string('next_action'),
        branch=string('branch_id'), branch_name=string('branch__name'),
        status=Case(When(status__in=['won', 'lost'], then=string('status')), When(owner__isnull=True, then=text('unassigned')),
                    default=string('status'), output_field=CharField()), owner_name=string('owner__username'), lead=string('pk'),
        lead_label=string('lead_id'), contact=string('contact_id'), received_at=F('created_at'), activity_at=F('created_at'),
        target=text('lead'), target_id=string('pk'))
    result = [website, calls, leads]
    can_read_whatsapp = has_global_scope(user) or user.role in ['branch_manager', 'counsellor', 'support']
    if can_read_whatsapp:
        inbound = Message.objects.filter(conversation_id=OuterRef('pk'), direction='inbound').order_by('-created_at', '-id')
        replied = Message.objects.filter(conversation_id=OuterRef('pk'), direction='outbound', mode='live', queue_status='sent',
            occurred_at__gte=OuterRef('last_inbound_at')).exclude(delivery_status='failed')
        chats = Conversation.objects.filter(channel__branch_id__in=branch_ids).annotate(
            latest_inbound=Subquery(inbound.values('created_at')[:1]), latest_body=Subquery(inbound.values('text')[:1]), has_reply=Exists(replied))
        chats = chats.filter(latest_inbound__isnull=False)
        result.append(project(chats, key=Concat(text('whatsapp:'), string('pk')), source=text('whatsapp'),
            source_label=string('channel__name'), name=Coalesce(choose(Q(contact_id__in=contacts), string('contact__full_name')), Concat(text('+'), string('wa_id'))),
            phone=Concat(text('+'), string('wa_id')), title=text('WhatsApp conversation'), preview=string('latest_body'),
            branch=string('channel__branch_id'), branch_name=string('channel__branch__name'),
            status=Case(When(has_reply=True, then=text('replied')), default=text('awaiting_reply')),
            contact=choose(Q(contact_id__in=contacts), string('contact_id')), received_at=F('last_inbound_at'), activity_at=F('latest_inbound'),
            target=text('whatsapp'), target_id=string('pk')))
    else:
        result = [rows.exclude(feed_source='whatsapp') for rows in result]
    return result, can_read_whatsapp


class FeedEntrySerializer(serializers.Serializer):
    key = serializers.CharField()
    source = serializers.CharField()
    source_label = serializers.CharField()
    name = serializers.CharField()
    phone = serializers.CharField(allow_null=True, allow_blank=True)
    title = serializers.CharField()
    preview = serializers.CharField(allow_null=True, allow_blank=True)
    branch = serializers.CharField()
    branch_name = serializers.CharField()
    status = serializers.CharField()
    owner_name = serializers.CharField(allow_null=True)
    lead = serializers.CharField(allow_null=True)
    lead_label = serializers.CharField(allow_null=True)
    contact = serializers.CharField(allow_null=True)
    received_at = serializers.DateTimeField(allow_null=True)
    activity_at = serializers.DateTimeField()
    target = serializers.CharField()
    target_id = serializers.CharField()


class FeedSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    has_next = serializers.BooleanField()
    server_time = serializers.DateTimeField()
    sources = serializers.ListField(child=serializers.CharField())
    totals = serializers.DictField(child=serializers.IntegerField())
    source_totals = serializers.DictField(child=serializers.IntegerField())
    whatsapp_mode = serializers.CharField()
    results = FeedEntrySerializer(many=True)


class LiveEnquiryView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'live_enquiries'

    @extend_schema(responses=FeedSerializer, parameters=[OpenApiParameter(name, type=str) for name in ['branch', 'source', 'status', 'period', 'search', 'page']])
    def get(self, request):
        now = timezone.now()
        branches = branch_scope(Branch.objects.all(), request.user, 'pk')
        selected_branch = request.query_params.get('branch')
        if selected_branch:
            selected_branch = serializers.UUIDField().run_validation(selected_branch)
            if not branches.filter(pk=selected_branch).exists():
                raise serializers.ValidationError({'branch': 'Choose a branch in your scope.'})
            branches = branches.filter(pk=selected_branch)
        queries, whatsapp = source_rows(request.user, list(branches.values_list('pk', flat=True)))
        sources = ['website', 'call', 'manual'] + (['whatsapp'] if whatsapp else [])
        source = request.query_params.get('source', '')
        if source and source not in sources:
            raise PermissionDenied('This enquiry source is not in your scope.')
        status = request.query_params.get('status', '')
        if status and status not in STATES:
            raise serializers.ValidationError({'status': 'Choose a valid enquiry state.'})
        period = serializers.ChoiceField(choices=['today', '24h', 'all']).run_validation(request.query_params.get('period', 'today'))
        start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0) if period == 'today' else now-timedelta(hours=24) if period == '24h' else None
        search = serializers.CharField(max_length=200, allow_blank=True).run_validation(request.query_params.get('search', ''))
        page = serializers.IntegerField(min_value=1, max_value=100000).run_validation(request.query_params.get('page', 1))
        counts, by_source, filtered = {}, {key: 0 for key in sources}, []
        for rows in queries:
            if start:
                rows = rows.filter(feed_activity_at__gte=start)
            if search:
                rows = rows.filter(Q(feed_name__icontains=search) | Q(feed_phone__icontains=search) | Q(feed_title__icontains=search))
            for group in rows.values('feed_status', 'feed_source').annotate(total=Count('pk')):
                if not source or group['feed_source'] == source:
                    counts[group['feed_status']] = counts.get(group['feed_status'], 0) + group['total']
                by_source[group['feed_source']] = by_source.get(group['feed_source'], 0) + group['total']
            if source:
                rows = rows.filter(feed_source=source)
            filtered.append(rows.filter(feed_status=status) if status else rows)
        total = counts.get(status, 0) if status else sum(counts.values())
        size = 25
        merged = filtered[0].union(*filtered[1:], all=True).order_by('-feed_activity_at', 'feed_key')
        results = [{key[5:]: value for key, value in row.items()} for row in merged[(page-1)*size:page*size]]
        totals = {'all': sum(counts.values()), 'needs_enquiry': counts.get('needs_enquiry', 0), 'unassigned': counts.get('unassigned', 0),
            'review': counts.get('review', 0), 'awaiting_reply': counts.get('awaiting_reply', 0), 'new': counts.get('new', 0)}
        return Response({'count': total, 'page': page, 'page_size': size, 'has_next': page*size < total, 'server_time': now,
            'sources': sources, 'totals': totals, 'source_totals': by_source, 'whatsapp_mode': settings.WHATSAPP_MODE, 'results': results})
