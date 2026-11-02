import re
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from common.access import branch_scope
from common.permissions import has_global_scope
from common.serializers import StrictInputMixin
from branches.models import Branch
from leads.models import Lead
from calls.models import CallLog
from messaging.models import Conversation
from .models import AutomationRule, AutomationRun, AutomationTask, AutomationEvent
from . import services


def manager(user):
    return has_global_scope(user) or getattr(user, 'role', None) == 'branch_manager'


class SalesPermission(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return u.is_authenticated and u.is_active and (has_global_scope(u) or u.role in ('branch_manager', 'counsellor'))


def runs_for(user):
    if not user.is_authenticated:
        return AutomationRun.objects.none()
    rows = branch_scope(AutomationRun.objects.all(), user)
    return rows if manager(user) else rows.filter(Q(lead__owner=user) | Q(work_items__assignee=user)).distinct()


def validate_text(text):
    if any(item not in ('name', 'course', 'branch') for item in re.findall(r'\{([^{}]*)\}', text)):
        raise serializers.ValidationError('Supported placeholders: {name}, {course}, {branch}.')
    return text


class StepInput(StrictInputMixin, serializers.Serializer):
    kind = serializers.ChoiceField(choices=['message', 'task'])
    title = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=2000, allow_blank=True, required=False, default='')
    delay_minutes = serializers.IntegerField(min_value=0, max_value=43200)
    grace_minutes = serializers.IntegerField(min_value=1, max_value=1440, default=15)

    def validate(self, data):
        validate_text(data['body'])
        if data['kind'] == 'message' and not data['body'].strip():
            raise serializers.ValidationError('Message text is required.')
        return data


class RuleSerializer(StrictInputMixin, serializers.ModelSerializer):
    steps = StepInput(many=True, max_length=12, required=False)
    acknowledgement_minutes = serializers.IntegerField(min_value=0, max_value=60, required=False)
    acknowledgement_text = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    callback_minutes = serializers.IntegerField(min_value=1, max_value=1440, required=False)
    start_hour = serializers.IntegerField(min_value=0, max_value=23, required=False)
    end_hour = serializers.IntegerField(min_value=1, max_value=24, required=False)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = AutomationRule
        fields = ['id', 'branch', 'branch_name', 'name', 'source', 'is_active', 'enabled_at', 'version', 'acknowledgement_minutes', 'acknowledgement_text', 'callback_minutes', 'business_hours', 'start_hour', 'end_hour', 'steps', 'created_at']
        read_only_fields = ['id', 'enabled_at', 'version', 'created_at']
        validators = []

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['branch'].queryset = branch_scope(Branch.objects.filter(is_active=True), request.user, 'pk') if request else Branch.objects.none()
        return fields

    def validate_acknowledgement_text(self, value):
        return validate_text(value)

    def validate(self, data):
        start = data.get('start_hour', self.instance.start_hour if self.instance else 9)
        end = data.get('end_hour', self.instance.end_hour if self.instance else 18)
        if start >= end:
            raise serializers.ValidationError('Business hours must finish after they start.')
        return data

    def create(self, data):
        return services.save_rule(self.context['request'].user, data)

    def update(self, instance, data):
        return services.save_rule(self.context['request'].user, data, instance)


class RuleViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = RuleSerializer
    permission_classes = [SalesPermission]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        return branch_scope(AutomationRule.objects.select_related('branch'), self.request.user)

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and not manager(request.user):
            self.permission_denied(request, message='Only managers can configure automation rules.')


class RunSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name')
    rule_name = serializers.CharField(source='rule.name')
    can_control = serializers.SerializerMethodField()

    class Meta:
        model = AutomationRun
        fields = ['id', 'rule', 'rule_name', 'branch', 'branch_name', 'lead', 'call', 'conversation', 'source', 'name', 'phone', 'state', 'reason', 'snapshot', 'started_at', 'can_control']

    def get_can_control(self, obj) -> bool:
        user = self.context['request'].user
        return manager(user) or (obj.lead_id is not None and obj.lead.owner_id == user.pk)


class EnrollInput(StrictInputMixin, serializers.Serializer):
    rule = serializers.UUIDField()
    lead = serializers.UUIDField(required=False)
    call = serializers.UUIDField(required=False)
    conversation = serializers.UUIDField(required=False)

    def validate(self, data):
        if sum(k in data for k in ('lead', 'call', 'conversation')) != 1:
            raise serializers.ValidationError('Choose exactly one target.')
        return data


class ControlInput(StrictInputMixin, serializers.Serializer):
    action = serializers.ChoiceField(choices=['pause', 'resume', 'stop'])
    reason = serializers.CharField(max_length=250)


class RunViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [SalesPermission]
    serializer_class = RunSerializer

    def get_queryset(self):
        rows = runs_for(self.request.user).select_related('branch', 'rule', 'lead')
        if value := self.request.query_params.get('state'):
            rows = rows.filter(state=serializers.ChoiceField(choices=['active', 'paused', 'stopped', 'completed']).run_validation(value))
        return rows

    @extend_schema(request=EnrollInput, responses=RunSerializer)
    @action(detail=False, methods=['post'])
    def enroll(self, request):
        from django.shortcuts import get_object_or_404
        if not manager(request.user):
            self.permission_denied(request, message='Only managers can enroll historic enquiries.')
        data = EnrollInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        rule = get_object_or_404(branch_scope(AutomationRule.objects.all(), request.user), pk=values.pop('rule'))
        key, pk = next(iter(values.items()))
        models = {'lead': Lead, 'call': CallLog, 'conversation': Conversation}
        scope = 'channel__branch_id' if key == 'conversation' else 'branch_id'
        target = get_object_or_404(branch_scope(models[key].objects.all(), request.user, scope), pk=pk)
        run = services.enroll(rule=rule, actor=request.user, **{key: target})
        return Response(self.get_serializer(run).data)

    @extend_schema(request=ControlInput, responses=RunSerializer)
    @action(detail=True, methods=['post'])
    def control(self, request, pk=None):
        data = ControlInput(data=request.data)
        data.is_valid(raise_exception=True)
        run = services.control_run(actor=request.user, run=self.get_object(), **data.validated_data)
        return Response(self.get_serializer(run).data)


class WorkSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='run.name')
    phone = serializers.CharField(source='run.phone')
    lead = serializers.UUIDField(source='run.lead_id', allow_null=True)
    call = serializers.UUIDField(source='run.call_id', allow_null=True)
    conversation = serializers.UUIDField(source='run.conversation_id', allow_null=True)
    assignee_name = serializers.CharField(source='assignee.username', default='Manager queue')
    overdue = serializers.SerializerMethodField()

    class Meta:
        model = AutomationTask
        fields = ['id', 'run', 'name', 'phone', 'lead', 'call', 'conversation', 'assignee', 'assignee_name', 'title', 'due_at', 'status', 'resolution', 'overdue']

    def get_overdue(self, obj) -> bool:
        return obj.status in ('pending', 'escalated') and obj.due_at < timezone.now()


class AutomationCompleteInput(StrictInputMixin, serializers.Serializer):
    resolution = serializers.CharField(max_length=2000)


class WorkViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [SalesPermission]
    serializer_class = WorkSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return AutomationTask.objects.none()
        rows = branch_scope(AutomationTask.objects.select_related('run', 'assignee'), self.request.user)
        if not manager(self.request.user) or self.request.query_params.get('team') != 'true':
            rows = rows.filter(assignee=self.request.user)
        status = self.request.query_params.get('status', 'open')
        if status == 'open':
            rows = rows.filter(status__in=['pending', 'escalated'])
        elif status:
            rows = rows.filter(status=serializers.ChoiceField(choices=['pending', 'escalated', 'completed', 'cancelled']).run_validation(status))
        if self.request.query_params.get('overdue') == 'true':
            rows = rows.filter(due_at__lt=timezone.now(), status__in=['pending', 'escalated'])
        return rows

    @extend_schema(request=AutomationCompleteInput, responses=WorkSerializer)
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        data = AutomationCompleteInput(data=request.data)
        data.is_valid(raise_exception=True)
        result = services.complete_task(actor=request.user, task=self.get_object(), **data.validated_data)
        return Response(self.get_serializer(result).data)


class EventSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='run.name')

    class Meta:
        model = AutomationEvent
        fields = ['id', 'run', 'name', 'code', 'detail', 'actor', 'created_at']


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [SalesPermission]
    serializer_class = EventSerializer

    def get_queryset(self):
        rows = AutomationEvent.objects.filter(run__in=runs_for(self.request.user)).select_related('run')
        if value := self.request.query_params.get('run'):
            rows = rows.filter(run_id=serializers.UUIDField().run_validation(value))
        return rows
