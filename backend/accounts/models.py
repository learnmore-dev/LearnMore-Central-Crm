import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = 'super_admin', 'Super Admin'
        MANAGEMENT = 'management', 'Management'
        BRANCH_MANAGER = 'branch_manager', 'Branch Manager'
        COUNSELLOR = 'counsellor', 'Counsellor'
        INTERN = 'intern', 'Intern (branch read-only)'
        ACCOUNTS = 'accounts', 'Accounts Team'
        SUPPORT = 'support', 'Trainer/Student Support'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.COUNSELLOR)
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, null=True, blank=True, related_name='users')

    class Meta:
        constraints = [models.CheckConstraint(
            condition=models.Q(is_superuser=True) | models.Q(role__in=['super_admin', 'management']) | models.Q(branch__isnull=False),
            name='scoped_user_requires_branch',
        )]


class UserAccessEvent(models.Model):
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='access_changes_made')
    target = models.ForeignKey(User, on_delete=models.PROTECT, related_name='access_changes')
    action = models.CharField(max_length=30)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
