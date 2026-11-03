def lead_statuses():
    from .models import Lead
    return Lead.Status.choices
