from django.contrib.auth import get_user_model
from branches.models import Branch
from contacts.models import Contact


def crm_fixtures():
    a = Branch.objects.create(name='Marathahalli', code='marathahalli')
    b = Branch.objects.create(name='BTM Layout', code='btm-layout')
    User = get_user_model()
    owner = User.objects.create_user(username='owner', branch=a)
    manager = User.objects.create_user(username='manager', role='branch_manager', branch=a)
    other = User.objects.create_user(username='other', branch=b)
    management = User.objects.create_user(username='management', role='management')
    from routing.models import CounsellorProfile
    for employee in (owner, manager, other):
        CounsellorProfile.objects.create(user=employee, is_available=True, max_active_leads=100)
    contact = Contact.objects.create(full_name='Test Person', branch=a, created_by=owner)
    return a, b, owner, manager, other, management, contact
