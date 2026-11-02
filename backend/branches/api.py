from rest_framework import mixins, serializers, viewsets
from common.permissions import BranchPermissions, has_global_scope
from .models import Branch

class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ['id', 'name', 'code', 'address', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']

class BranchViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                    mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = BranchSerializer
    permission_classes = [BranchPermissions]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Branch.objects.none()
        return Branch.objects.all() if has_global_scope(user) else Branch.objects.filter(pk=user.branch_id)
