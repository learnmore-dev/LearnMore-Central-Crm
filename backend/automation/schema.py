def rule_sources():
    from .models import AutomationRule
    return AutomationRule._meta.get_field('source').choices
