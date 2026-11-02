from django.db.models import F, Value, CharField, Case, When
from django.db.models.functions import Cast, Concat, Coalesce, Replace, NullIf
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from common.permissions import has_global_scope
from activities.models import Activity
from calls.models import CallLog
from common.access import branch_scope
from leads.models import Lead
from messaging.models import Message

FIELDS = ['id', 'source', 'title', 'body', 'actor', 'branch', 'occurred_at', 'status', 'mode', 'target']


def text(value):
    return Value(value, output_field=CharField())


def string(field):
    return Cast(F(field), output_field=CharField())


def project(rows, **fields):
    return rows.order_by().annotate(**{'history_'+k: fields.get(k, text('')) for k in FIELDS}).values(*['history_'+k for k in FIELDS])


class HistoryQuery(serializers.Serializer):
    source = serializers.ChoiceField(choices=['all', 'whatsapp', 'call', 'activity'], default='all')
    page = serializers.IntegerField(min_value=1, max_value=100000, default=1)


class ContactCommunicationHistorySerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    has_next = serializers.BooleanField()
    enquiries = serializers.ListField(child=serializers.DictField())
    results = serializers.ListField(child=serializers.DictField())


def contact_history(request, contact):
    form = HistoryQuery(data=request.query_params)
    form.is_valid(raise_exception=True)
    source, page = form.validated_data['source'], form.validated_data['page']
    can_read_chat = has_global_scope(request.user) or request.user.role in ('counsellor', 'branch_manager', 'support')
    if source == 'whatsapp' and not can_read_chat:
        raise PermissionDenied('WhatsApp access is required for chat history.')
    messages = branch_scope(Message.objects.filter(conversation__contact=contact), request.user, 'conversation__channel__branch_id')
    if not can_read_chat:
        messages = messages.none()
    calls = branch_scope(CallLog.objects.filter(contact=contact), request.user)
    activities = branch_scope(Activity.objects.filter(contact=contact), request.user)
    rows = {
        'whatsapp': project(messages, id=string('pk'), source=text('whatsapp'), title=Concat(text('WhatsApp · '), string('direction')),
            body=Concat(Coalesce(NullIf(string('text'), text('')), string('template__body'), text('[Non-text message]')),
                Case(When(template__isnull=False, then=Concat(text('\nTemplate parameters: '), string('parameters'))), default=text(''), output_field=CharField())), actor=Coalesce(F('created_by__username'), text('Customer / system')),
            branch=F('conversation__channel__branch__name'), occurred_at=F('occurred_at'), status=F('queue_status'), mode=F('mode'),
            target=Concat(text('/inbox?conversation='), string('conversation_id'))),
        'call': project(calls, id=string('pk'), source=text('call'), title=Concat(string('direction'), text(' call · '), string('status')),
            body=Concat(Coalesce(F('notes'), text('')), text('\nDuration: '), string('duration_seconds'), text('s · Forwarded to: '), Coalesce(F('forwarded_to'), text(''))),
            actor=F('created_by__username'), branch=F('branch__name'), occurred_at=F('started_at'), status=F('status'), mode=F('origin'),
            target=Concat(text('/calls?search='), Replace(F('caller_phone'), text('+'), text('%2B')))),
        'activity': project(activities, id=string('pk'), source=text('activity'), title=F('kind'), body=F('body'),
            actor=Coalesce(F('actor__username'), text('System')), branch=F('branch__name'), occurred_at=F('created_at')),
    }
    selected = list(rows.values()) if source == 'all' else [rows[source]]
    merged = selected[0].union(*selected[1:], all=True).order_by('-history_occurred_at', 'history_source', 'history_id') if len(selected) > 1 else selected[0].order_by('-history_occurred_at', 'history_id')
    size, count = 25, sum(q.count() for q in selected)
    leads = branch_scope(Lead.objects.filter(contact=contact), request.user).select_related('owner', 'branch')
    enquiries = [dict(id=str(lead.pk), lead_id=lead.lead_id, title=lead.title, status=lead.status, branch=lead.branch.name,
        owner=(lead.owner.get_full_name() or lead.owner.username) if lead.owner_id else 'Unassigned / manager queue',
        received_at=lead.received_at.isoformat(), received_via=lead.received_via) for lead in leads[:100]]
    return Response(dict(count=count, page=page, has_next=page*size < count, enquiries=enquiries,
        results=[{k[8:]: v for k, v in row.items()} for row in merged[(page-1)*size:page*size]]))
