from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from branches.models import Branch
from common.access import branch_scope, visible_contacts
from common.permissions import CRMRecordPermissions
from common.serializers import StrictInputMixin
from contacts.normalization import normalize_phone
from intake.api import ResolveInput
from .models import CallLog
from . import services


class CallSerializer(StrictInputMixin, serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    contact_name = serializers.CharField(source='contact.full_name', read_only=True, allow_null=True)
    contact_label = serializers.CharField(source='contact.contact_id', read_only=True, allow_null=True)
    lead_label = serializers.CharField(source='lead.lead_id', read_only=True, allow_null=True)
    identity_status = serializers.SerializerMethodField()
    candidates = serializers.SerializerMethodField()

    def get_identity_status(self, obj) -> str:
        return 'linked' if obj.contact_id else 'rejected' if obj.review_id and obj.review.status == 'rejected' else 'review'

    def get_candidates(self, obj) -> list[dict]:
        if not obj.review_id or obj.contact_id:
            return []
        return list(visible_contacts(self.context['request'].user).filter(duplicate_reviews=obj.review).values('id', 'full_name', 'contact_id'))

    class Meta:
        model = CallLog
        fields = ['id', 'branch', 'branch_name', 'client_key', 'origin', 'caller_phone', 'caller_name', 'business_phone',
            'direction', 'status', 'started_at', 'duration_seconds', 'forwarded_to', 'notes', 'contact', 'contact_name',
            'contact_label', 'identity_status', 'candidates', 'lead', 'lead_label', 'created_at']
        read_only_fields = ['id', 'origin', 'contact', 'lead', 'created_at']
        validators = []

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['branch'].queryset = branch_scope(Branch.objects.filter(is_active=True), request.user, 'pk') if request else Branch.objects.none()
        return fields

    def validate_client_key(self, value):
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
            raise serializers.ValidationError('Supply a unique call request key.')
        return value

    def validate(self, attrs):
        for key in ['caller_phone', 'business_phone']:
            if attrs.get(key):
                try:
                    attrs[key] = normalize_phone(attrs[key])
                except DjangoValidationError:
                    raise serializers.ValidationError({key: 'Enter a valid phone number.'}) from None
        if attrs.get('duration_seconds', 0) > 604800:
            raise serializers.ValidationError({'duration_seconds': 'Enter a duration of up to seven days.'})
        return attrs

    def create(self, validated_data):
        return services.record_call(actor=self.context['request'].user, **validated_data)


class EnquiryInput(StrictInputMixin, serializers.Serializer):
    title = serializers.CharField(max_length=200)


class CallViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = CallSerializer
    permission_classes = [CRMRecordPermissions]

    def get_queryset(self):
        rows = branch_scope(CallLog.objects.select_related('branch', 'contact', 'lead', 'review'), self.request.user)
        for key, choices in [('status', ['answered', 'missed', 'voicemail']), ('direction', ['incoming', 'outgoing'])]:
            if self.request.query_params.get(key):
                rows = rows.filter(**{key: serializers.ChoiceField(choices=choices).run_validation(self.request.query_params[key])})
        search = self.request.query_params.get('search', '').strip()
        if search:
            if len(search) > 200:
                raise serializers.ValidationError({'search': 'Search is limited to 200 characters.'})
            rows = rows.filter(Q(caller_phone__icontains=search) | Q(contact__full_name__icontains=search) |
                Q(caller_name__icontains=search) | Q(forwarded_to__icontains=search))
        return rows

    @extend_schema(request=EnquiryInput, responses=CallSerializer)
    @action(detail=True, methods=['post'], url_path='create-enquiry')
    def create_enquiry(self, request, pk=None):
        call = self.get_object()
        form = EnquiryInput(data=request.data)
        form.is_valid(raise_exception=True)
        result = services.create_enquiry(actor=request.user, call=call, **form.validated_data)
        return Response(self.get_serializer(result).data)

    @extend_schema(request=ResolveInput, responses=CallSerializer)
    @action(detail=True, methods=['post'], url_path='resolve-contact')
    def resolve_contact(self, request, pk=None):
        call = self.get_object()
        form = ResolveInput(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        result = services.resolve_contact(actor=request.user, call=call, **form.validated_data)
        return Response(self.get_serializer(result).data)
