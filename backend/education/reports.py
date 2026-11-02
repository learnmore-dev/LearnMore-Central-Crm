"""Current outcomes for a dated enquiry cohort; never invents historical stages."""
import csv
from datetime import datetime, time, timedelta
from io import StringIO
from django.contrib.auth import get_user_model
from django.db.models import Q, F, Value, CharField, Count, Exists, OuterRef, Subquery
from django.db.models.functions import Coalesce, NullIf
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from activities.models import Activity
from branches.models import Branch
from common.access import branch_scope
from contacts.models import Source
from leads.models import Lead
from automation.api import SalesPermission, manager
from .models import Demo


class ReportFilters(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    branch = serializers.UUIDField(required=False)
    owner = serializers.UUIDField(required=False)
    source = serializers.ChoiceField(choices=Source.choices, required=False)
    course = serializers.CharField(max_length=200, required=False)
    group = serializers.ChoiceField(choices=['branch', 'owner', 'source', 'course'], default='source')
    page = serializers.IntegerField(min_value=1, max_value=100000, default=1)
    export = serializers.ChoiceField(choices=['csv'], required=False)

    def validate(self, data):
        data.setdefault('end', timezone.localdate())
        data.setdefault('start', data['end']-timedelta(days=29))
        if data['start'] > data['end'] or (data['end']-data['start']).days > 365:
            raise serializers.ValidationError('Choose a date range of at most 366 days, with start before end.')
        return data


def scoped_cohort(user, filters):
    branches = branch_scope(Branch.objects.all(), user, 'pk')
    if 'branch' in filters:
        if not branches.filter(pk=filters['branch']).exists():
            raise serializers.ValidationError({'branch': 'Choose a branch in your scope.'})
        branches = branches.filter(pk=filters['branch'])
    owners = get_user_model().objects.filter(branch_id__in=branches.values('pk'), role__in=['counsellor', 'branch_manager'])
    rows = Lead.objects.filter(branch_id__in=branches.values('pk'))
    if not manager(user):
        rows = rows.filter(owner=user)
        owners = owners.filter(pk=user.pk)
    if 'owner' in filters:
        if not owners.filter(pk=filters['owner']).exists():
            raise serializers.ValidationError({'owner': 'Choose a counsellor in your scope.'})
        rows = rows.filter(owner_id=filters['owner'])
    start = timezone.make_aware(datetime.combine(filters['start'], time()))
    end = timezone.make_aware(datetime.combine(filters['end']+timedelta(days=1), time()))
    rows = rows.filter(created_at__gte=start, created_at__lt=end).annotate(
        course_label=Coalesce(NullIf(F('qualification__course_interest'), Value('')), F('title')))
    if 'source' in filters:
        rows = rows.filter(source=filters['source'])
    if 'course' in filters:
        rows = rows.filter(course_label__icontains=filters['course'])
    demos = Demo.objects.filter(lead_id=OuterRef('pk'), branch_id__in=branches.values('pk'))
    human = Activity.objects.filter(lead_id=OuterRef('pk'), actor__isnull=False).order_by('-created_at', '-pk')
    return rows.annotate(has_demo=Exists(demos), has_attended=Exists(demos.filter(status='attended')),
        last_staff_at=Coalesce(Subquery(human.values('created_at')[:1]), F('created_at')))


def metrics():
    return dict(enquiries=Count('pk'), **{s: Count('pk', filter=Q(status=s)) for s in Lead.Status.values},
        demo_booked=Count('pk', filter=Q(has_demo=True)), demo_attended=Count('pk', filter=Q(has_attended=True)),
        unassigned=Count('pk', filter=Q(owner__isnull=True, status__in=['new', 'contacted', 'qualified'])))


def csv_cell(value):
    text = str(value)
    return "'"+text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text


class FunnelReportSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    totals = serializers.DictField(child=serializers.IntegerField())
    demo_outcomes = serializers.DictField(child=serializers.IntegerField())
    ageing = serializers.DictField(child=serializers.IntegerField())
    aged_enquiries = serializers.ListField(child=serializers.DictField())
    group = serializers.CharField()
    groups = serializers.ListField(child=serializers.DictField())
    group_count = serializers.IntegerField()
    page = serializers.IntegerField()
    has_next = serializers.BooleanField()


class FunnelReportView(APIView):
    permission_classes = [SalesPermission]

    @extend_schema(responses=FunnelReportSerializer, parameters=[OpenApiParameter(n, type=str) for n in ['start', 'end', 'branch', 'owner', 'source', 'course', 'group', 'page', 'export']])
    def get(self, request):
        filters = ReportFilters(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        rows = scoped_cohort(request.user, data)
        group_fields = {'branch': ('branch_id', 'branch__name'), 'owner': ('owner_id', 'owner__username'), 'source': ('source', 'source'), 'course': ('course_label', 'course_label')}
        key, title = group_fields[data['group']]
        grouped = rows.order_by().annotate(group_label=Coalesce(F(title), Value('Unassigned'), output_field=CharField())).values(key, 'group_label').annotate(**metrics()).order_by('-enquiries', 'group_label', key)
        count, size = grouped.count(), 50
        if data.get('export') == 'csv':
            if count > 5000:
                raise serializers.ValidationError('Narrow the filters before exporting more than 5,000 report groups.')
            stream = StringIO(newline='')
            writer = csv.writer(stream)
            writer.writerow(['Enquiry cohort from', str(data['start']), 'through', str(data['end']), 'IST'])
            writer.writerow(['Group', 'Enquiries', 'New', 'Contacted (current)', 'Qualified (current)', 'Won (CRM stage)', 'Lost', 'Any demo booking', 'Attended demo', 'Unassigned active'])
            for row in grouped:
                writer.writerow([csv_cell(row['group_label'])]+[row[k] for k in ['enquiries', 'new', 'contacted', 'qualified', 'won', 'lost', 'demo_booked', 'demo_attended', 'unassigned']])
            response = HttpResponse('\ufeff'+stream.getvalue(), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="learnmore-enquiry-outcomes.csv"'
            return response
        now = timezone.now()
        active = rows.filter(status__in=['new', 'contacted', 'qualified'], no_followup_reason='')
        ageing = {'0_2_days': active.filter(last_staff_at__gt=now-timedelta(days=3)).count(),
            '3_7_days': active.filter(last_staff_at__lte=now-timedelta(days=3), last_staff_at__gt=now-timedelta(days=8)).count(),
            '8_14_days': active.filter(last_staff_at__lte=now-timedelta(days=8), last_staff_at__gt=now-timedelta(days=15)).count(),
            '15_plus_days': active.filter(last_staff_at__lte=now-timedelta(days=15)).count()}
        aged = [{'id': str(r.pk), 'name': r.contact.full_name, 'course': r.course_label, 'owner': r.owner.username if r.owner_id else 'Unassigned',
            'last_staff_at': r.last_staff_at, 'days': max(0, int((now-r.last_staff_at).total_seconds()//86400))}
            for r in active.select_related('contact', 'owner').order_by('last_staff_at', 'pk')[:10]]
        demo_rows = Demo.objects.filter(lead_id__in=rows.values('pk'), branch_id__in=branch_scope(Branch.objects.all(), request.user, 'pk').values('pk'))
        if 'branch' in data:
            demo_rows = demo_rows.filter(branch_id=data['branch'])
        return Response({'start': data['start'], 'end': data['end'], 'totals': rows.aggregate(**metrics()),
            'demo_outcomes': {s: demo_rows.filter(status=s).count() for s in ['scheduled', 'attended', 'no_show', 'cancelled']},
            'ageing': ageing, 'aged_enquiries': aged, 'group': data['group'], 'groups': list(grouped[(data['page']-1)*size:data['page']*size]),
            'group_count': count, 'page': data['page'], 'has_next': data['page']*size < count})
