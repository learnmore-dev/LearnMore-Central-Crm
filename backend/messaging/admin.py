from django.contrib import admin
from django.utils import timezone
from .models import Channel, Conversation, Message, Template, WebhookDelivery, ConsentEvent


class SuperuserOnly(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Channel)
class ChannelAdmin(SuperuserOnly):
    list_display = ['name', 'branch', 'phone_number_id', 'is_active']
    readonly_fields = ['id', 'branch', 'phone_number_id', 'waba_id', 'name']

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)


@admin.register(WebhookDelivery)
class DeliveryAdmin(SuperuserOnly):
    list_display = ['id', 'status', 'attempts', 'error_code', 'created_at']
    list_filter = ['status']
    actions = ['retry_receipts']

    @admin.action(description='Reprocess selected failed webhook receipts after correcting configuration')
    def retry_receipts(self, request, queryset):
        if self.has_module_permission(request):
            count = queryset.filter(status='failed').update(status='retry', attempts=0, next_attempt_at=timezone.now(), error_code='')
            self.message_user(request, f'{count} receipts scheduled for idempotent reprocessing.')


@admin.register(Message)
class MessageAdmin(SuperuserOnly):
    list_display = ['id', 'direction', 'queue_status', 'delivery_status', 'mode', 'attempts', 'error_code']
    list_filter = ['queue_status', 'delivery_status', 'mode']
    search_fields = ['provider_id', 'client_key']


admin.site.register(Conversation, SuperuserOnly)
admin.site.register(Template, SuperuserOnly)
admin.site.register(ConsentEvent, SuperuserOnly)
