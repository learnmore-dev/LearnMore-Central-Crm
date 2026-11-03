"""Official Graph API transport. Never persist/log tokens or raw provider errors."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from django.conf import settings
from .configuration import credentials, CredentialError


class ProviderError(Exception):
    def __init__(self, code, *, retryable=False, ambiguous=False, retry_after=0):
        self.code = str(code)[:100]
        self.retryable = retryable
        self.ambiguous = ambiguous
        self.retry_after = min(max(retry_after, 0), 3600)
        super().__init__(self.code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def graph_request(resource, *, payload=None, params=None):
    try:
        config = credentials()
    except CredentialError:
        raise ProviderError('credential_storage_unavailable') from None
    version = config['graph_version']
    if not re.fullmatch(r'v\d+\.\d+', version) or not re.fullmatch(r'\d+/(messages|message_templates|phone_numbers)', resource):
        raise ProviderError('invalid_graph_configuration')
    if resource.endswith('/phone_numbers') and payload is not None:
        raise ProviderError('invalid_graph_configuration')
    if not config['access_token']:
        raise ProviderError('missing_access_token')
    url = f'https://graph.facebook.com/{version}/{resource}'
    if params:
        url += '?' + urlencode(params)
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization': 'Bearer ' + config['access_token'], 'Content-Type': 'application/json'},
        method='POST' if payload is not None else 'GET')
    try:
        # No redirects: credentials must never be forwarded to a different host.
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            result = json.loads(response.read(2_000_000))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except HTTPError as exc:
        try:
            error = json.loads(exc.read(65536)).get('error', {})
            code = int(error.get('code', exc.code))
            transient = error.get('is_transient') is True
        except (ValueError, TypeError, AttributeError):
            code, transient = exc.code, False
        try:
            retry_after = int(exc.headers.get('Retry-After', '0'))
        except (ValueError, TypeError):
            retry_after = 0
        raise ProviderError(f'graph_{code}', retryable=exc.code == 429 or (exc.code < 500 and transient),
            ambiguous=exc.code >= 500 and payload is not None, retry_after=retry_after) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ProviderError('transport_outcome_unknown', ambiguous=payload is not None, retryable=payload is None) from None


def send_message(message):
    if message.mode == 'mock':
        return 'mock.' + str(message.pk)
    # Defence in depth: direct adapter calls are also gated.
    if settings.WHATSAPP_MODE != 'live' or not settings.WHATSAPP_LIVE_SENDS_ENABLED:
        raise ProviderError('live_sends_disabled')
    payload = {'messaging_product': 'whatsapp', 'recipient_type': 'individual',
        'to': message.conversation.wa_id, 'type': message.kind, 'biz_opaque_callback_data': str(message.pk)}
    if message.kind == 'text':
        payload['text'] = {'body': message.text, 'preview_url': False}
    else:
        payload['template'] = {'name': message.template.name, 'language': {'code': message.template.language}}
        if message.parameters:
            payload['template']['components'] = [{'type': 'body', 'parameters': [{'type': 'text', 'text': p} for p in message.parameters]}]
    data = graph_request(message.conversation.channel.phone_number_id + '/messages', payload=payload)
    try:
        provider_id = data['messages'][0]['id']
        if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 254:
            raise ValueError()
        return provider_id
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProviderError('invalid_send_response', ambiguous=True) from None


def fetch_templates(channel):
    """Read-only; no mock approvals are ever inferred from real credentials."""
    rows, cursor, seen = [], None, set()
    for _ in range(100):
        data = graph_request(channel.waba_id + '/message_templates', params={
            'fields': 'id,name,language,status,category,components', 'limit': 100, **({'after': cursor} if cursor else {})})
        if not isinstance(data.get('data'), list):
            raise ProviderError('invalid_template_response')
        rows.extend(data['data'])
        paging = data.get('paging', {})
        if not isinstance(paging, dict):
            raise ProviderError('invalid_template_pagination')
        if not paging.get('next'):
            return rows
        cursors = paging.get('cursors', {})
        if not isinstance(cursors, dict):
            raise ProviderError('invalid_template_pagination')
        cursor = cursors.get('after')
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ProviderError('invalid_template_pagination')
        seen.add(cursor)
    raise ProviderError('template_pagination_limit')


def check_connection(channel):
    cursor, seen = None, set()
    for _ in range(100):
        data = graph_request(channel.waba_id + '/phone_numbers', params={
            'fields': 'id,display_phone_number,verified_name', 'limit': 100,
            **({'after': cursor} if cursor else {})})
        if not isinstance(data.get('data'), list):
            raise ProviderError('invalid_phone_number_response')
        for item in data['data']:
            if not isinstance(item, dict):
                raise ProviderError('invalid_phone_number_response')
            if str(item.get('id')) == channel.phone_number_id:
                return {'connected': True, 'code': 'account_access_verified',
                        'detail': 'Meta confirms access to this business account and phone number. Webhook delivery and sending permission must be checked separately.',
                        'display_phone_number': str(item.get('display_phone_number', ''))[:40],
                        'verified_name': str(item.get('verified_name', ''))[:150]}
        paging = data.get('paging', {})
        if not isinstance(paging, dict):
            raise ProviderError('invalid_phone_number_response')
        if not paging.get('next'):
            raise ProviderError('phone_number_not_in_account')
        cursors = paging.get('cursors', {})
        if not isinstance(cursors, dict):
            raise ProviderError('invalid_phone_number_pagination')
        cursor = cursors.get('after')
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ProviderError('invalid_phone_number_pagination')
        seen.add(cursor)
    raise ProviderError('phone_number_pagination_limit')
