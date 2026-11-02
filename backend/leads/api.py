from django.contrib.auth import get_user_model
from rest_framework import mixins, serializers, viewsets
from branches.models import Branch
from common.access import branch_scope, visible_contacts
from common.permissions import CRMRecordPermissions, has_global_scope
from common.serializers import StrictInputMixin
from contacts.models import Contact
from .models import Lead
from . import services
from common.identifiers import canonical_identifier_search
from django.db.models import Q


class LeadSerializer(StrictInputMixin, serializers.ModelSerializer):
    contact_name = serializers.CharField(source='contact.full_name', read_only=True)
    owner_name = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    origin_branch_name = serializers.CharField(source='origin_branch.name', read_only=True, allow_null=True)
    can_edit = serializers.SerializerMethodField()

    def get_owner_name(self, obj) -> str | None:
        return (obj.owner.get_full_name() or obj.owner.username) if obj.owner else None

    def get_can_edit(self, obj) -> bool:
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        user = request.user
        return has_global_scope(user) or (user.branch_id == obj.branch_id and (
            user.role == 'branch_manager' or (user.role == 'counsellor' and obj.owner_id == user.pk)))
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.none(), required=False)
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.none())
    owner = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.none(), required=False, allow_null=True)

    class Meta:
        model = Lead
        fields = ['id', 'lead_id', 'contact', 'branch', 'owner', 'title', 'source', 'status', 'next_action',
                  'next_action_at', 'no_followup_reason', 'unassigned_reason', 'created_by', 'created_at', 'updated_at',
                  'assignment_version', 'acknowledgement_due_at', 'acknowledged_at', 'routing_attempts',
                  'contact_name', 'owner_name', 'branch_name', 'can_edit', 'received_at', 'received_via',
                  'origin_branch', 'origin_branch_name', 'origin_branch_code', 'origin_branch_verified', 'legacy_lead_id']
        read_only_fields = ['id', 'lead_id', 'created_by', 'created_at', 'updated_at',
                            'assignment_version', 'acknowledgement_due_at', 'acknowledged_at', 'routing_attempts', 'received_at', 'received_via',
                            'origin_branch', 'origin_branch_code', 'origin_branch_verified', 'legacy_lead_id']

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request:
            fields['branch'].queryset = branch_scope(Branch.objects.filter(is_active=True), request.user, 'pk')
            fields['contact'].queryset = visible_contacts(request.user)
            fields['owner'].queryset = branch_scope(get_user_model().objects.filter(
                is_active=True, role__in=['counsellor', 'branch_manager']), request.user)
        if self.instance:
            for name in ('contact', 'branch', 'owner', 'source', 'unassigned_reason'):
                fields[name].read_only = True
        return fields

    def validate(self, attrs):
        if self.instance is None:
            attrs['branch'] = attrs.get('branch') or self.context['request'].user.branch
            if attrs['branch'] is None:
                raise serializers.ValidationError({'branch': 'Choose an active branch.'})
        return attrs

    def create(self, validated_data):
        return services.create_lead(actor=self.context['request'].user, **validated_data)

    def update(self, instance, validated_data):
        return services.update_lead(actor=self.context['request'].user, lead=instance, **validated_data)


class LeadViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                  mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = LeadSerializer
    permission_classes = [CRMRecordPermissions]

    def get_queryset(self):
        queryset = branch_scope(Lead.objects.select_related('contact', 'branch', 'owner', 'origin_branch'), self.request.user)
        if search := self.request.query_params.get('search', '').strip():
            search = canonical_identifier_search(search)
            queryset = queryset.filter(Q(lead_id__icontains=search) | Q(legacy_lead_id__icontains=search) | Q(title__icontains=search) | Q(contact__full_name__icontains=search))
        for field in ('contact', 'owner', 'branch'):
            if field in self.request.query_params:
                value = serializers.UUIDField().run_validation(self.request.query_params[field])
                queryset = queryset.filter(**{field + '_id': value})
        if 'status' in self.request.query_params:
            value = serializers.ChoiceField(choices=Lead.Status.choices).run_validation(self.request.query_params['status'])
            queryset = queryset.filter(status=value)
        return queryset
