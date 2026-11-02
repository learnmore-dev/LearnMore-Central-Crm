from rest_framework import mixins, serializers, viewsets
from branches.models import Branch
from common.access import branch_scope, visible_contacts
from common.permissions import CRMRecordPermissions
from common.serializers import StrictInputMixin
from contacts.models import Contact
from leads.models import Lead
from .models import Activity
from .services import add_note


class ActivitySerializer(StrictInputMixin, serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    contact_name = serializers.CharField(source='contact.full_name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    def get_actor_name(self, obj) -> str:
        return (obj.actor.get_full_name() or obj.actor.username) if obj.actor else 'System'

    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.none())
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.none(), required=False)
    lead = serializers.PrimaryKeyRelatedField(queryset=Lead.objects.none(), required=False, allow_null=True)

    class Meta:
        model = Activity
        fields = ['id', 'contact', 'lead', 'branch', 'actor', 'kind', 'body', 'created_at', 'actor_name', 'contact_name', 'branch_name']
        read_only_fields = ['id', 'actor', 'kind', 'created_at']

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request:
            fields['branch'].queryset = branch_scope(Branch.objects.filter(is_active=True), request.user, 'pk')
            fields['contact'].queryset = visible_contacts(request.user)
            fields['lead'].queryset = branch_scope(Lead.objects.all(), request.user)
        return fields

    def validate(self, attrs):
        attrs['branch'] = attrs.get('branch') or self.context['request'].user.branch
        if attrs['branch'] is None:
            raise serializers.ValidationError({'branch': 'Choose an active branch.'})
        return attrs

    def create(self, validated_data):
        return add_note(actor=self.context['request'].user, **validated_data)


class ActivityViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = ActivitySerializer
    permission_classes = [CRMRecordPermissions]

    def get_queryset(self):
        queryset = branch_scope(Activity.objects.select_related('contact', 'lead', 'actor', 'branch'), self.request.user)
        for field in ('contact', 'lead'):
            if field in self.request.query_params:
                value = serializers.UUIDField().run_validation(self.request.query_params[field])
                queryset = queryset.filter(**{field + '_id': value})
        return queryset
