def identifier_kinds():
    from .models import ContactIdentifier
    return ContactIdentifier.Kind.choices


def sources():
    from .models import Source
    return Source.choices
