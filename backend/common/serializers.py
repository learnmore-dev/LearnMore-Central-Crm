from rest_framework import serializers


class StrictInputMixin:
    """Reject spoofed read-only/unknown fields instead of silently ignoring them."""
    def to_internal_value(self, data):
        if isinstance(data, dict):
            invalid = set(data) - {name for name, field in self.fields.items() if not field.read_only}
            if invalid:
                raise serializers.ValidationError({name: 'This field cannot be supplied.' for name in invalid})
        return super().to_internal_value(data)
