from rest_framework import mixins, serializers, viewsets
from common.access import branch_scope
from .models import User


class EmployeeSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    routing_profile_id = serializers.IntegerField(source='counsellor_profile.pk', read_only=True, allow_null=True)

    def get_display_name(self, obj) -> str:
        return obj.get_full_name() or obj.username

    class Meta:
        model = User
        fields = ['id', 'display_name', 'role', 'branch', 'is_active', 'routing_profile_id']
        read_only_fields = fields


class EmployeeViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = EmployeeSerializer

    def get_queryset(self):
        return branch_scope(User.objects.filter(role__in=['counsellor', 'branch_manager']).select_related(
            'counsellor_profile').order_by('first_name', 'username'), self.request.user)
