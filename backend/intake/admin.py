from django.contrib import admin
from messaging.admin import SuperuserOnly
from .models import WebsiteSource, WebsiteSubmission


@admin.register(WebsiteSource)
class SourceAdmin(SuperuserOnly):
    list_display = ['slug', 'default_branch', 'is_active']


@admin.register(WebsiteSubmission)
class SubmissionAdmin(SuperuserOnly):
    list_display = ['id', 'source', 'branch', 'status', 'created_at']
    list_filter = ['source', 'status', 'branch']
