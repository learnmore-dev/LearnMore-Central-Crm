from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from activities.api import ActivitySerializer
from activities.models import Activity
from branches.models import Branch
from followups.models import FollowUpTask
from leads.models import Lead
from routing.models import CounsellorProfile
from .access import branch_scope, visible_contacts
from .permissions import has_global_scope


class DashboardSerializer(serializers.Serializer):
    contacts = serializers.IntegerField()
    active_leads = serializers.IntegerField()
    unassigned = serializers.IntegerField()
    overdue_tasks = serializers.IntegerField()
    available_counsellors = serializers.IntegerField()
    pipeline = serializers.DictField(child=serializers.IntegerField())
    branches = serializers.ListField(child=serializers.DictField())
    recent_activities = ActivitySerializer(many=True)


class DashboardView(APIView):
    @extend_schema(responses=DashboardSerializer, parameters=[OpenApiParameter('branch', type=str)])
    def get(self, request):
        user = request.user
        branches = branch_scope(Branch.objects.all(), user, 'pk')
        selected = request.query_params.get('branch')
        if selected:
            pk = serializers.UUIDField().run_validation(selected)
            if not branches.filter(pk=pk).exists():
                raise serializers.ValidationError({'branch': 'Choose a branch in your scope.'})
            branches = branches.filter(pk=pk)
        branch_ids = branches.values_list('pk', flat=True)
        leads = Lead.objects.filter(branch_id__in=branch_ids)
        tasks = FollowUpTask.objects.filter(branch_id__in=branch_ids)
        if not has_global_scope(user) and user.role != 'branch_manager':
            tasks = tasks.filter(assignee=user)
        contacts = visible_contacts(user)
        if selected:
            contacts = contacts.filter(Q(branch_id=pk) | Q(leads__branch_id=pk)).distinct()
        activities = Activity.objects.filter(branch_id__in=branch_ids).select_related('contact', 'branch', 'actor')[:8]
        pipeline = {value: leads.filter(status=value).count() for value in Lead.Status.values}
        summaries = [{'id': str(branch.pk), 'name': branch.name, 'is_active': branch.is_active,
            'active_leads': leads.filter(branch=branch, status__in=['new', 'contacted', 'qualified']).count(),
            'unassigned': leads.filter(branch=branch, owner__isnull=True, status__in=['new', 'contacted', 'qualified']).count()}
            for branch in branches]
        return Response({'contacts': contacts.count(), 'active_leads': sum(pipeline[key] for key in ['new', 'contacted', 'qualified']),
            'unassigned': leads.filter(owner__isnull=True, status__in=['new', 'contacted', 'qualified']).count(),
            'overdue_tasks': tasks.filter(status__in=['pending', 'escalated'], due_at__lt=timezone.now()).count(),
            'available_counsellors': CounsellorProfile.objects.filter(user__branch_id__in=branch_ids,
                user__is_active=True, user__role__in=['counsellor', 'branch_manager'], is_available=True, can_receive_leads=True).count(),
            'pipeline': pipeline, 'branches': summaries,
            'recent_activities': ActivitySerializer(activities, many=True, context={'request': request}).data})
