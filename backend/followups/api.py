from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from common.access import branch_scope
from common.permissions import CRMRecordPermissions, has_global_scope
from common.serializers import StrictInputMixin
from leads.models import Lead
from .models import FollowUpTask
from . import services


class TaskSerializer(StrictInputMixin, serializers.ModelSerializer):
    overdue = serializers.SerializerMethodField()

    class Meta:
        model = FollowUpTask
        fields = ['id', 'lead', 'branch', 'assignee', 'kind', 'title', 'status', 'due_at', 'assignment_version',
                  'resolution', 'completed_at', 'created_by', 'created_at', 'overdue']
        read_only_fields = ['id', 'branch', 'assignee', 'status', 'assignment_version',
                            'resolution', 'completed_at', 'created_by', 'created_at', 'overdue']

    def get_overdue(self, obj) -> bool:
        return obj.status in ('pending', 'escalated') and obj.due_at < timezone.now()

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['lead'].queryset = branch_scope(Lead.objects.all(), request.user) if request else Lead.objects.none()
        return fields

    def create(self, validated_data):
        return services.create_task(actor=self.context['request'].user, **validated_data)


class CompleteInput(StrictInputMixin, serializers.Serializer):
    resolution = serializers.CharField(max_length=2000)
    next_action = serializers.CharField(max_length=500, required=False, allow_blank=True)
    next_action_at = serializers.DateTimeField(required=False, allow_null=True)
    no_followup_reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class TaskViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = TaskSerializer
    permission_classes = [CRMRecordPermissions]

    def get_queryset(self):
        user = self.request.user
        queryset = branch_scope(FollowUpTask.objects.select_related('lead', 'branch', 'assignee'), user)
        if not has_global_scope(user) and getattr(user, 'role', None) != 'branch_manager':
            queryset = queryset.filter(assignee_id=user.pk)
        if 'lead' in self.request.query_params:
            queryset = queryset.filter(lead_id=serializers.UUIDField().run_validation(self.request.query_params['lead']))
        if 'status' in self.request.query_params:
            value = serializers.ChoiceField(choices=FollowUpTask.Status.choices).run_validation(self.request.query_params['status'])
            queryset = queryset.filter(status=value)
        if self.request.query_params.get('overdue') == 'true':
            queryset = queryset.filter(status__in=['pending', 'escalated'], due_at__lt=timezone.now())
        return queryset

    @extend_schema(request=CompleteInput, responses=TaskSerializer)
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        task = self.get_object()
        serializer = CompleteInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = services.complete_task(actor=request.user, task=task, **serializer.validated_data)
        return Response(self.get_serializer(task).data)
