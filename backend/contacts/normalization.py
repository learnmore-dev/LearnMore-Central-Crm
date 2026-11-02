import re
import phonenumbers
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


def normalize_phone(value):
    """Use IN for national numbers; explicit international numbers retain country."""
    value = value.strip()
    if not re.fullmatch(r'[+\d\s().-]+', value, flags=re.ASCII):
        raise ValidationError('Enter a phone number without letters or extensions.')
    if value.startswith('00'):
        value = '+' + value[2:]
    try:
        number = phonenumbers.parse(value, 'IN')
    except phonenumbers.NumberParseException:
        raise ValidationError('Enter a valid phone number.')
    if number.extension or not phonenumbers.is_valid_number(number):
        raise ValidationError('Enter a valid phone number without an extension.')
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_identifier(kind, value, namespace=''):
    value, namespace = value.strip(), namespace.strip().lower()
    if not value or len(value) > 254:
        raise ValidationError('Identifier must contain between 1 and 254 characters.')
    if kind == 'phone':
        if namespace:
            raise ValidationError('Phone identifiers do not have a provider namespace.')
        return normalize_phone(value), ''
    if kind == 'email':
        if namespace:
            raise ValidationError('Email identifiers do not have a provider namespace.')
        validate_email(value)
        return value.casefold(), ''
    if kind == 'external':
        if not re.fullmatch(r'[a-z0-9_-]{1,40}', namespace):
            raise ValidationError('External identifiers require a provider namespace (letters, digits, _ or -).')
        return value, namespace  # provider IDs are case sensitive
    raise ValidationError('Unknown identifier kind.')
