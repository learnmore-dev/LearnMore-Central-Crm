from django.db import transaction
from django.utils import timezone
from automation.services import process_automations
from .models import JobHealth
from .services import process_demos


def run_cycle():
    """Each stage retries on the next cycle; health stores exception types, never payloads."""
    result, errors = {}, []
    from followups.reporting import snapshot_deadlines
    for name, job in [('deadlines', snapshot_deadlines), ('automation', process_automations), ('demos', process_demos)]:
        try:
            result[name] = job()
        except Exception as error:
            errors.append(name + ':' + type(error).__name__)
    now = timezone.now()
    with transaction.atomic():
        health, _ = JobHealth.objects.select_for_update().get_or_create(name='crm_followups', defaults={'last_attempt_at': now})
        health.last_attempt_at = now
        health.error_code = ','.join(errors)[:100]
        health.consecutive_failures = health.consecutive_failures+1 if errors else 0
        if not errors:
            health.last_success_at = now
        health.save()
    return {'status': 'retry_pending' if errors else 'ok', **result, 'errors': errors}
