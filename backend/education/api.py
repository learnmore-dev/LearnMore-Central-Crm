from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, mixins, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema
from common.access import branch_scope
from common.serializers import StrictInputMixin
from automation.api import SalesPermission, manager
from leads.models import Lead
from .models import Qualification, Demo, DemoTask
from branches.models import Branch
from . import services


def visible_leads(user):
    rows = branch_scope(Lead.objects.all(), user)
    if not user.is_authenticated:
        return rows.none()
    return rows if manager(user) else rows.filter(owner=user)


class QualificationSerializer(StrictInputMixin, serializers.ModelSerializer):
    missing_fields = serializers.SerializerMethodField()
    course_interests = serializers.ListField(child=serializers.CharField(max_length=200), max_length=20, allow_empty=False, required=False)
    preferred_branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), allow_null=True, required=False)
    preferred_branch_name = serializers.CharField(source='preferred_branch.name', read_only=True, allow_null=True)

    def validate_course_interests(self, values):
        if len({value.casefold() for value in values}) != len(values):
            raise serializers.ValidationError('Select each course only once.')
        return values

    def to_representation(self, instance):
        result = super().to_representation(instance)
        if not result['course_interests']:
            primary = instance.course_interest or instance.lead.title
            result['course_interests'] = [primary] if primary else []
        return result

    class Meta:
        model = Qualification
        fields = ['lead', 'course_interest', 'course_interests', 'city', 'preferred_branch', 'preferred_branch_name', 'background', 'training_mode', 'preferred_location', 'preferred_schedule', 'joining_timeline', 'readiness', 'notes', 'updated_at', 'missing_fields']
        read_only_fields = ['lead', 'updated_at']

    def get_missing_fields(self, obj) -> list[str]:
        return [field for field in ('course_interest', 'background', 'training_mode', 'joining_timeline') if getattr(obj, field) in ('', 'unknown', 'undecided')]


class QualificationView(APIView):
    permission_classes = [SalesPermission]

    @extend_schema(responses=QualificationSerializer)
    def get(self, request, lead_id):
        lead = get_object_or_404(visible_leads(request.user), pk=lead_id)
        item = Qualification.objects.filter(lead=lead).first() or Qualification(lead=lead)
        return Response(QualificationSerializer(item).data)

    @extend_schema(request=QualificationSerializer, responses=QualificationSerializer)
    def patch(self, request, lead_id):
        lead = get_object_or_404(visible_leads(request.user), pk=lead_id)
        serializer = QualificationSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        item = services.save_qualification(request.user, lead, serializer.validated_data)
        return Response(QualificationSerializer(item).data)


class DemoSerializer(StrictInputMixin, serializers.ModelSerializer):
    name = serializers.CharField(source='lead.contact.full_name', read_only=True)
    lead_label = serializers.CharField(source='lead.lead_id', read_only=True)
    owner_name = serializers.CharField(source='lead.owner.username', default='Manager queue', read_only=True)
    duration_minutes = serializers.IntegerField(min_value=15, max_value=180, default=60)
    client_key = serializers.UUIDField(write_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = Demo
        fields = ['id', 'lead', 'lead_label', 'name', 'owner_name', 'branch_name', 'course', 'mode', 'location', 'starts_at', 'duration_minutes', 'status', 'outcome', 'version', 'client_key']
        read_only_fields = ['id', 'status', 'outcome', 'version']
        validators = []

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['lead'].queryset = visible_leads(request.user) if request else Lead.objects.none()
        return fields

    def create(self, data):
        return services.book_demo(self.context['request'].user, **data)


class DemoChangeInput(StrictInputMixin, serializers.Serializer):
    action = serializers.ChoiceField(choices=['reschedule', 'attended', 'no_show', 'cancelled'])
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=2000)
    starts_at = serializers.DateTimeField(required=False)
    duration_minutes = serializers.IntegerField(min_value=15, max_value=180, required=False)
    location = serializers.CharField(max_length=250, required=False)

    def validate(self, data):
        if data['action'] != 'reschedule' and set(data) & {'starts_at', 'duration_minutes', 'location'}:
            raise serializers.ValidationError('Schedule fields apply only to rescheduling.')
        return data


class DemoViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    permission_classes = [SalesPermission]
    serializer_class = DemoSerializer

    def get_queryset(self):
        rows = branch_scope(Demo.objects.filter(lead__in=visible_leads(self.request.user)).select_related('lead__contact', 'lead__owner', 'branch'), self.request.user)
        if value := self.request.query_params.get('lead'):
            rows = rows.filter(lead_id=serializers.UUIDField().run_validation(value))
        if value := self.request.query_params.get('status'):
            rows = rows.filter(status=serializers.ChoiceField(choices=Demo._meta.get_field('status').choices).run_validation(value))
        return rows

    @extend_schema(request=DemoChangeInput, responses=DemoSerializer)
    @action(detail=True, methods=['post'])
    def change(self, request, pk=None):
        data = DemoChangeInput(data=request.data)
        data.is_valid(raise_exception=True)
        result = services.change_demo(request.user, self.get_object(), **data.validated_data)
        return Response(self.get_serializer(result).data)


class DemoTaskSerializer(serializers.ModelSerializer):
    lead = serializers.UUIDField(source='demo.lead_id')
    name = serializers.CharField(source='demo.lead.contact.full_name')
    course = serializers.CharField(source='demo.course')
    starts_at = serializers.DateTimeField(source='demo.starts_at')
    assignee_name = serializers.CharField(source='assignee.username', default='Manager queue')

    class Meta:
        model = DemoTask
        fields = ['id', 'demo', 'lead', 'name', 'course', 'kind', 'starts_at', 'assignee_name', 'due_at', 'status', 'resolution']


class DemoTaskCompleteInput(StrictInputMixin, serializers.Serializer):
    resolution = serializers.CharField(max_length=2000)


class DemoTaskViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [SalesPermission]
    serializer_class = DemoTaskSerializer

    def get_queryset(self):
        rows = DemoTask.objects.filter(demo__lead__in=visible_leads(self.request.user))
        rows = branch_scope(rows, self.request.user, 'demo__branch_id').select_related('demo__lead__contact', 'assignee')
        if value := self.request.query_params.get('lead'):
            rows = rows.filter(demo__lead_id=serializers.UUIDField().run_validation(value))
        if self.action == 'list' and self.request.query_params.get('all') != 'true':
            rows = rows.filter(status='pending')
        return rows

    @extend_schema(request=DemoTaskCompleteInput, responses=DemoTaskSerializer)
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        data = DemoTaskCompleteInput(data=request.data)
        data.is_valid(raise_exception=True)
        item = services.complete_demo_task(request.user, self.get_object(), **data.validated_data)
        return Response(self.get_serializer(item).data)


class PreferredBranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ['id', 'name']


class PreferredBranchesView(APIView):
    permission_classes = [SalesPermission]

    @extend_schema(responses=PreferredBranchSerializer(many=True))
    def get(self, request):
        # Preference metadata only: choosing it grants no access or branch transfer.
        return Response(PreferredBranchSerializer(Branch.objects.filter(is_active=True), many=True).data)
