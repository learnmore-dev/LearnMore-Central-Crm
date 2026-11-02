from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q, Min
from common.identifiers import canonical_identifier_search
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from branches.models import Branch
from common.access import branch_scope, visible_contacts
from common.permissions import CRMRecordPermissions, has_global_scope
from common.serializers import StrictInputMixin
from .models import Contact, ContactIdentifier, DuplicateReview
from .normalization import normalize_identifier
from .history import ContactCommunicationHistorySerializer
from . import services


class IdentifierInputSerializer(StrictInputMixin, serializers.Serializer):
    kind = serializers.ChoiceField(choices=ContactIdentifier.Kind.choices)
    value = serializers.CharField(max_length=254)
    namespace = serializers.CharField(max_length=40, required=False, allow_blank=True, default='')

    def validate(self, attrs):
        try:
            normalize_identifier(attrs['kind'], attrs['value'], attrs['namespace'])
        except DjangoValidationError as error:
            raise serializers.ValidationError({'value': error.messages})
        return attrs


class IdentifierSerializer(StrictInputMixin, serializers.ModelSerializer):
    class Meta:
        model = ContactIdentifier
        fields = ['id', 'contact', 'kind', 'value', 'normalized_value', 'namespace', 'created_at']
        read_only_fields = ['id', 'normalized_value', 'created_at']
        # Service handles normalized duplicate/idempotency semantics under a lock.
        validators = []

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['contact'].queryset = visible_contacts(request.user) if request else Contact.objects.none()
        return fields

    def validate(self, attrs):
        services.prepare_identifiers([attrs])
        return attrs


class ContactSerializer(StrictInputMixin, serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    can_edit = serializers.SerializerMethodField()
    first_enquiry_at = serializers.SerializerMethodField()

    def get_first_enquiry_at(self, obj) -> str | None:
        from leads.models import Lead
        earliest = branch_scope(Lead.objects.filter(contact=obj), self.context['request'].user).aggregate(value=Min('received_at'))['value']
        return earliest.isoformat() if earliest else None

    def get_can_edit(self, obj) -> bool:
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        user = request.user
        return has_global_scope(user) or (user.branch_id == obj.branch_id and user.role in ('branch_manager', 'counsellor'))
    identifiers = IdentifierInputSerializer(many=True, write_only=True, allow_empty=False, max_length=20)
    identifier_records = IdentifierSerializer(source='identifiers', many=True, read_only=True)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.none(), required=False)

    class Meta:
        model = Contact
        fields = ['id', 'contact_id', 'full_name', 'branch', 'source', 'identifiers',
                  'identifier_records', 'created_by', 'created_at', 'updated_at', 'branch_name', 'can_edit', 'first_enquiry_at']
        read_only_fields = ['id', 'contact_id', 'created_by', 'created_at', 'updated_at']

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request:
            fields['branch'].queryset = branch_scope(Branch.objects.filter(is_active=True), request.user, 'pk')
        if self.instance:
            # Changing identity or branch cannot be hidden inside a profile edit.
            for name in ('branch', 'source', 'identifiers'):
                fields[name].read_only = True
        return fields

    def validate(self, attrs):
        if self.instance is None:
            branch = attrs.get('branch') or self.context['request'].user.branch
            if branch is None:
                raise serializers.ValidationError({'branch': 'Choose an active branch.'})
            attrs['branch'] = branch
            attrs['identifiers'] = services.prepare_identifiers(attrs['identifiers'])
        return attrs

    def create(self, validated_data):
        return services.create_contact(actor=self.context['request'].user, **validated_data)

    def update(self, instance, validated_data):
        return services.update_contact(actor=self.context['request'].user, contact=instance,
                                       full_name=validated_data.get('full_name', instance.full_name))


class DuplicateReviewSerializer(serializers.ModelSerializer):
    candidate_contacts = serializers.SerializerMethodField()
    resolved_contact = serializers.SerializerMethodField()

    class Meta:
        model = DuplicateReview
        fields = ['id', 'branch', 'full_name', 'source', 'identifiers', 'target_contact', 'status',
                  'candidate_contacts', 'resolved_contact', 'reason', 'created_by', 'resolved_by', 'created_at', 'resolved_at']
        read_only_fields = fields

    def get_candidate_contacts(self, obj) -> list[str]:
        user = self.context['request'].user
        return [str(pk) for pk in visible_contacts(user).filter(duplicate_reviews=obj).values_list('pk', flat=True)]

    def get_resolved_contact(self, obj) -> str | None:
        if obj.resolved_contact_id and visible_contacts(self.context['request'].user).filter(pk=obj.resolved_contact_id).exists():
            return str(obj.resolved_contact_id)
        return None


class MatchSerializer(StrictInputMixin, serializers.Serializer):
    identifiers = IdentifierInputSerializer(many=True, allow_empty=False, max_length=20)


class MatchResultSerializer(serializers.Serializer):
    needs_review = serializers.BooleanField()
    candidate_contacts = serializers.ListField(child=serializers.UUIDField())


class ResolveSerializer(StrictInputMixin, serializers.Serializer):
    decision = serializers.ChoiceField(choices=['linked', 'separate', 'rejected'])
    reason = serializers.CharField(max_length=2000)
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.none(), required=False)

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['contact'].queryset = visible_contacts(request.user) if request else Contact.objects.none()
        return fields


class ContactViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                     mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ContactSerializer
    permission_classes = [CRMRecordPermissions]

    @extend_schema(responses=ContactCommunicationHistorySerializer)
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        from .history import contact_history
        return contact_history(request, self.get_object())

    def get_queryset(self):
        queryset = visible_contacts(self.request.user).select_related('branch', 'created_by').prefetch_related('identifiers')
        search = canonical_identifier_search(self.request.query_params.get('search', '').strip())
        if len(search) > 200:
            raise serializers.ValidationError({'search': 'Search is limited to 200 characters.'})
        return queryset.filter(Q(full_name__icontains=search) | Q(contact_id__icontains=search)) if search else queryset

    @extend_schema(responses={201: ContactSerializer, 409: DuplicateReviewSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        if isinstance(result, DuplicateReview):
            return Response(DuplicateReviewSerializer(result, context=self.get_serializer_context()).data, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(result).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=MatchSerializer, responses=MatchResultSerializer)
    @action(detail=False, methods=['post'])
    def match(self, request):
        serializer = MatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidates = services.candidates_for(services.prepare_identifiers(serializer.validated_data['identifiers']))
        visible = visible_contacts(request.user).filter(pk__in=candidates.values('pk'))
        return Response({'needs_review': candidates.exists(), 'candidate_contacts': [str(pk) for pk in visible.values_list('pk', flat=True)]})


class IdentifierViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = IdentifierSerializer
    permission_classes = [CRMRecordPermissions]

    def get_queryset(self):
        return ContactIdentifier.objects.filter(contact__in=visible_contacts(self.request.user)).select_related('contact')

    @extend_schema(responses={201: IdentifierSerializer, 409: DuplicateReviewSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.add_identifier(actor=request.user, **serializer.validated_data)
        if isinstance(result, DuplicateReview):
            return Response(DuplicateReviewSerializer(result, context=self.get_serializer_context()).data, status=409)
        return Response(self.get_serializer(result).data, status=201)


class DuplicateReviewViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = DuplicateReviewSerializer
    permission_classes = [CRMRecordPermissions]

    def get_queryset(self):
        return branch_scope(DuplicateReview.objects.all(), self.request.user)

    @extend_schema(request=ResolveSerializer, responses=DuplicateReviewSerializer)
    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        review = self.get_object()
        serializer = ResolveSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        review = services.resolve_review(actor=request.user, review=review, **serializer.validated_data)
        return Response(self.get_serializer(review).data)
