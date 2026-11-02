"""Preserve expired task deadlines before completion, rescheduling or reassignment."""
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone


def task_details(task):
    origin = task._meta.app_label
    if origin == 'followups':
        lead, branch = task.lead, task.branch
        title, name, course = task.title, lead.contact.full_name, lead.title
        target = f'/leads/{lead.pk}'
    elif origin == 'automation':
        lead, branch = task.run.lead, task.branch
        title, name = task.title, task.run.name
        course = lead.title if lead else 'Callback / conversation'
        target = f'/leads/{lead.pk}' if lead else '/automation'
    else:
        lead, branch = task.demo.lead, task.demo.branch
        title, name, course = task.get_kind_display(), lead.contact.full_name, task.demo.course
        target = f'/demos?lead={lead.pk}'
    return dict(origin=origin, task_id=task.pk, branch=branch, assignee_id=task.assignee_id,
                lead_id=lead.pk if lead else None, name=name, course=course, title=title,
                target=target, due_at=task.due_at)


def capture_deadlines(rows, now=None):
    from followups.models import DeadlineMiss
    now = now or timezone.now()
    rows = rows.filter(Q(status__in=['pending', 'escalated'], due_at__lt=now) |
                       Q(status='completed', completed_at__gt=F('due_at')))
    rows = rows.exclude(pk__in=DeadlineMiss.objects.filter(origin=rows.model._meta.app_label).values('task_id'))
    for task in rows.iterator():
        # A task's first expired deadline and responsible assignee are immutable.
        DeadlineMiss.objects.get_or_create(origin=task._meta.app_label, task_id=task.pk,
            defaults={k: v for k, v in task_details(task).items() if k not in ('origin', 'task_id')})


class DeadlineQuerySet(models.QuerySet):
    def update(self, **kwargs):
        with transaction.atomic():
            if {'status', 'due_at', 'assignee', 'assignee_id'} & kwargs.keys():
                capture_deadlines(self)
            return super().update(**kwargs)


class DeadlineTracked(models.Model):
    objects = DeadlineQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if not self._state.adding:
                capture_deadlines(type(self).objects.filter(pk=self.pk))
            return super().save(*args, **kwargs)
