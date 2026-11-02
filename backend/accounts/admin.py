from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CRMUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('CRM', {'fields': ('role', 'branch')}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('CRM', {'fields': ('role', 'branch')}),)
    list_display = ('username', 'role', 'branch', 'is_active')

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False  # deactivate accounts to preserve future ownership history
