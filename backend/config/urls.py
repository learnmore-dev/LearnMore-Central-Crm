from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAdminUser
from accounts.api import CSRFView, LoginView, LogoutView, ProfileView
from branches.api import BranchViewSet
from contacts.api import ContactViewSet, IdentifierViewSet, DuplicateReviewViewSet
from leads.api import LeadViewSet
from activities.api import ActivityViewSet
from routing.api import ProfileViewSet, PolicyViewSet, HistoryViewSet, RoutingViewSet, UnassignedViewSet
from followups.api import TaskViewSet
from accounts.directory import EmployeeViewSet
from accounts.employee_admin import EmployeeAdminViewSet, UserAccessEventViewSet
from common.dashboard import DashboardView
from common.enquiries import LiveEnquiryView
from messaging.api import WebhookView, ChannelViewSet, ConversationViewSet, MessageViewSet, TemplateViewSet
from intake.api import WebsiteWebhook, WebsiteSubmissionViewSet
from calls.api import CallViewSet
from messaging.workspace import CannedViewSet, CampaignViewSet, AdViewSet, WorkspaceSettings
from automation.api import RuleViewSet, RunViewSet, WorkViewSet, EventViewSet
from education.api import QualificationView, DemoViewSet, DemoTaskViewSet
from education.monitor import AttentionView
from education.reports import FunnelReportView
from education.workday import WorkdayView
from followups.reporting import FollowUpReportView
from google_contacts.api import GoogleIntegrationViewSet, GoogleSyncJobViewSet, GoogleSyncItemViewSet

router = DefaultRouter()
router.register('integrations/google-contacts', GoogleIntegrationViewSet, basename='google-contacts')
router.register('integrations/google-contact-jobs', GoogleSyncJobViewSet, basename='google-contact-job')
router.register('integrations/google-contact-items', GoogleSyncItemViewSet, basename='google-contact-item')
router.register('admin/employees', EmployeeAdminViewSet, basename='employee-admin')
router.register('admin/access-events', UserAccessEventViewSet, basename='employee-access-event')
router.register('education/demos', DemoViewSet, basename='education-demo')
router.register('education/tasks', DemoTaskViewSet, basename='education-task')
router.register('automation/rules', RuleViewSet, basename='automation-rule')
router.register('automation/runs', RunViewSet, basename='automation-run')
router.register('automation/work', WorkViewSet, basename='automation-work')
router.register('automation/audit', EventViewSet, basename='automation-event')
router.register('branches', BranchViewSet, basename='branch')
router.register('contacts', ContactViewSet, basename='contact')
router.register('contact-identifiers', IdentifierViewSet, basename='contact-identifier')
router.register('duplicate-reviews', DuplicateReviewViewSet, basename='duplicate-review')
router.register('leads', LeadViewSet, basename='lead')
router.register('activities', ActivityViewSet, basename='activity')
router.register('counsellor-profiles', ProfileViewSet, basename='counsellor-profile')
router.register('routing-policies', PolicyViewSet, basename='routing-policy')
router.register('assignment-history', HistoryViewSet, basename='assignment-history')
router.register('routing', RoutingViewSet, basename='routing')
router.register('unassigned', UnassignedViewSet, basename='unassigned')
router.register('follow-up-tasks', TaskViewSet, basename='follow-up-task')
router.register('employees', EmployeeViewSet, basename='employee')
router.register('whatsapp/channels', ChannelViewSet, basename='whatsapp-channel')
router.register('whatsapp/conversations', ConversationViewSet, basename='whatsapp-conversation')
router.register('whatsapp/messages', MessageViewSet, basename='whatsapp-message')
router.register('whatsapp/templates', TemplateViewSet, basename='whatsapp-template')
router.register('website-enquiries', WebsiteSubmissionViewSet, basename='website-enquiry')
router.register('call-logs', CallViewSet, basename='call-log')
router.register('whatsapp/canned-messages', CannedViewSet, basename='whatsapp-canned')
router.register('whatsapp/campaigns', CampaignViewSet, basename='whatsapp-campaign')
router.register('whatsapp/ad-drafts', AdViewSet, basename='whatsapp-ad-draft')
urlpatterns = [
    path('api/v1/follow-up-report/', FollowUpReportView.as_view()),
    path('api/v1/education/funnel/', FunnelReportView.as_view()),
    path('api/v1/education/workday/', WorkdayView.as_view()),
    path('api/v1/education/attention/', AttentionView.as_view()),
    path('api/v1/education/qualifications/<uuid:lead_id>/', QualificationView.as_view()),
    path('admin/', admin.site.urls),
    path('api/v1/auth/csrf/', CSRFView.as_view()),
    path('api/v1/auth/login/', LoginView.as_view()),
    path('api/v1/auth/logout/', LogoutView.as_view()),
    path('api/v1/auth/me/', ProfileView.as_view()),
    path('api/v1/dashboard/', DashboardView.as_view()),
    path('api/v1/enquiry-dashboard/', LiveEnquiryView.as_view()),
    path('api/v1/whatsapp/webhook/', WebhookView.as_view()),
    path('api/v1/whatsapp/settings/', WorkspaceSettings.as_view()),
    path('api/v1/intake/websites/<slug:site>/', WebsiteWebhook.as_view(), name='website-intake'),
    path('api/v1/', include(router.urls)),
    path('api/v1/schema/', SpectacularAPIView.as_view(permission_classes=[IsAdminUser]), name='schema'),
    path('api/v1/docs/', SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[IsAdminUser])),
]
