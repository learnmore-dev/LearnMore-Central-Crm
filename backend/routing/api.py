from django.contrib.auth import get_user_model
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from branches.models import Branch
from common.access import branch_scope
from common.permissions import CRMRecordPermissions
from common.serializers import StrictInputMixin
from leads.api import LeadSerializer
from leads.models import Lead
from .models import AssignmentHistory, CounsellorProfile, RoutingPolicy
from . import services


class CounsellorProfileSerializer(StrictInputMixin, serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    branch = serializers.UUIDField(source='user.branch_id', read_only=True)
    user_active = serializers.BooleanField(source='user.is_active', read_only=True)

    def get_user_name(self, obj) -> str:
        return obj.user.get_full_name() or obj.user.username

    workload = serializers.SerializerMethodField()

    class Meta:
        model = CounsellorProfile
        fields = ['id', 'user', 'is_available', 'can_receive_leads', 'max_active_leads', 'workload', 'updated_at',
                  'user_name', 'branch', 'user_active']
        read_only_fields = ['id', 'workload', 'updated_at']
        validators = []

    def get_workload(self, obj) -> int:
        return obj.user.leads.filter(status__in=services.ACTIVE).count()

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['user'].queryset = branch_scope(get_user_model().objects.filter(
            role__in=['counsellor', 'branch_manager']), request.user) if request else get_user_model().objects.none()
        if self.instance:
            fields['user'].read_only = True
        return fields

    def create(self, validated_data):
        return services.configure_profile(actor=self.context['request'].user, **validated_data)

    def update(self, instance, validated_data):
        return services.configure_profile(actor=self.context['request'].user, user=instance.user, **validated_data)


class ProfileViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                     mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = CounsellorProfileSerializer
    permission_classes = [CRMRecordPermissions]

    def get_queryset(self):
        return branch_scope(CounsellorProfile.objects.select_related('user'), self.request.user, 'user__branch_id')


class PolicySerializer(StrictInputMixin, serializers.ModelSerializer):
    acknowledgement_minutes = serializers.IntegerField(min_value=1, max_value=10080, required=False)
    followup_minutes = serializers.IntegerField(min_value=1, max_value=43200, required=False)
    max_reassignments = serializers.IntegerField(min_value=0, max_value=20, required=False)
    class Meta:
        model = RoutingPolicy
        fields = ['branch', 'last_position', 'acknowledgement_minutes', 'followup_minutes', 'max_reassignments']
        read_only_fields = ['last_position']
        validators = []

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['branch'].queryset = branch_scope(Branch.objects.filter(is_active=True), request.user, 'pk') if request else Branch.objects.none()
        if self.instance:
            fields['branch'].read_only = True
        return fields

    def create(self, validated_data):
        return services.configure_policy(actor=self.context['request'].user, **validated_data)

    def update(self, instance, validated_data):
        return services.configure_policy(actor=self.context['request'].user, branch=instance.branch, **validated_data)


class PolicyViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                    mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = PolicySerializer
    permission_classes = [CRMRecordPermissions]
    lookup_field = 'branch'

    def get_queryset(self):
        return branch_scope(RoutingPolicy.objects.select_related('branch'), self.request.user)


class HistorySerializer(serializers.ModelSerializer):
    lead_label = serializers.CharField(source='lead.lead_id', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    previous_owner_name = serializers.SerializerMethodField()
    new_owner_name = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()

    def get_previous_owner_name(self, obj) -> str | None:
        return (obj.previous_owner.get_full_name() or obj.previous_owner.username) if obj.previous_owner else None

    def get_new_owner_name(self, obj) -> str | None:
        return (obj.new_owner.get_full_name() or obj.new_owner.username) if obj.new_owner else None

    def get_actor_name(self, obj) -> str:
        return (obj.actor.get_full_name() or obj.actor.username) if obj.actor else 'System'

    class Meta:
        model = AssignmentHistory
        fields = ['id', 'lead', 'previous_owner', 'new_owner', 'previous_branch', 'branch',
                  'reason', 'actor', 'status', 'version', 'created_at', 'lead_label', 'branch_name',
                  'previous_owner_name', 'new_owner_name', 'actor_name']
        read_only_fields = fields


class HistoryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = HistorySerializer
    permission_classes = [CRMRecordPermissions]

    def get_queryset(self):
        queryset = branch_scope(AssignmentHistory.objects.select_related('lead', 'branch', 'previous_owner', 'new_owner', 'actor'), self.request.user)
        if 'lead' in self.request.query_params:
            queryset = queryset.filter(lead_id=serializers.UUIDField().run_validation(self.request.query_params['lead']))
        return queryset


class ScopedLeadInput(StrictInputMixin, serializers.Serializer):
    lead = serializers.PrimaryKeyRelatedField(queryset=Lead.objects.none())

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['lead'].queryset = branch_scope(Lead.objects.all(), request.user) if request else Lead.objects.none()
        return fields


class OverrideInput(ScopedLeadInput):
    owner = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.none(), allow_null=True)
    reason = serializers.CharField(max_length=2000)

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['owner'].queryset = branch_scope(get_user_model().objects.all(), request.user) if request else get_user_model().objects.none()
        return fields


class TransferInput(ScopedLeadInput):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    reason = serializers.CharField(max_length=2000)


class RoutingViewSet(viewsets.GenericViewSet):
    permission_classes = [CRMRecordPermissions]
    serializer_class = ScopedLeadInput

    def run_operation(self, request, serializer_class, operation):
        serializer = serializer_class(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        lead = operation(actor=request.user, **serializer.validated_data)
        return Response(LeadSerializer(lead, context=self.get_serializer_context()).data)

    @extend_schema(request=ScopedLeadInput, responses=LeadSerializer)
    @action(detail=False, methods=['post'])
    def route(self, request):
        return self.run_operation(request, ScopedLeadInput, services.route_lead)

    @extend_schema(request=OverrideInput, responses=LeadSerializer)
    @action(detail=False, methods=['post'])
    def override(self, request):
        return self.run_operation(request, OverrideInput, services.manual_assign)

    @extend_schema(request=TransferInput, responses=LeadSerializer)
    @action(detail=False, methods=['post'])
    def transfer(self, request):
        return self.run_operation(request, TransferInput, services.transfer_lead)

    @extend_schema(request=ScopedLeadInput, responses=LeadSerializer)
    @action(detail=False, methods=['post'])
    def acknowledge(self, request):
        return self.run_operation(request, ScopedLeadInput, services.acknowledge)


class UnassignedViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = LeadSerializer
    permission_classes = [CRMRecordPermissions]

    def get_queryset(self):
        return branch_scope(Lead.objects.filter(owner__isnull=True, status__in=services.ACTIVE).select_related('contact', 'branch'), self.request.user)
