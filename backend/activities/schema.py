def activity_kinds():
    from .models import Activity
    return Activity.Kind.choices
