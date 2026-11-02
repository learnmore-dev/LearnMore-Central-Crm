"""Server-side credentials. Never return decrypted values to serializers or logs."""
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from .models import WhatsAppConnection


class CredentialError(Exception):
    pass


def cipher():
    try:
        return Fernet(settings.WHATSAPP_ENCRYPTION_KEY.encode())
    except (ValueError, AttributeError):
        raise CredentialError('credential_storage_unavailable') from None


def storage_ready():
    try:
        cipher()
        return True
    except CredentialError:
        return False


def credentials():
    row = WhatsAppConnection.objects.filter(pk=1).first()
    result = {'graph_version': row.graph_version if row and row.graph_version else settings.WHATSAPP_GRAPH_VERSION}
    for name in ('access_token', 'app_secret', 'verify_token'):
        encrypted = getattr(row, name + '_encrypted', '') if row else ''
        if encrypted:
            try:
                result[name] = cipher().decrypt(encrypted.encode()).decode()
            except (InvalidToken, ValueError, UnicodeDecodeError):
                raise CredentialError('credential_storage_unavailable') from None
        else:
            result[name] = getattr(settings, 'WHATSAPP_' + name.upper())
    return result


def readiness():
    row = WhatsAppConnection.objects.filter(pk=1).first()
    values = {'mode': settings.WHATSAPP_MODE, 'live_sends_enabled': settings.WHATSAPP_LIVE_SENDS_ENABLED,
              'bulk_sends_enabled': False, 'storage_ready': storage_ready(),
              'graph_version': row.graph_version if row and row.graph_version else settings.WHATSAPP_GRAPH_VERSION,
              'webhook_path': '/api/v1/whatsapp/webhook/', 'webhook_url': row.webhook_url if row else '',
              'webhook_verified_at': row.webhook_verified_at if row else None}
    for name in ('access_token', 'app_secret', 'verify_token'):
        values[name + '_configured'] = bool(getattr(row, name + '_encrypted', '') if row else '') or bool(getattr(settings, 'WHATSAPP_' + name.upper()))
    return values
