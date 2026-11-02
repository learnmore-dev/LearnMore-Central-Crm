"""Fixed-host transport with redacted errors; no raw provider bodies or credentials in logs."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from django.conf import settings

FIELDS = 'names,phoneNumbers,emailAddresses,organizations,biographies,urls,userDefined,metadata'
MANAGED = FIELDS.replace(',metadata', '')
CONTACT_SCOPE = 'https://www.googleapis.com/auth/contacts'


class GoogleError(Exception):
    def __init__(self, code, ambiguous=False):
        self.code, self.ambiguous = code, ambiguous
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, method='GET', payload=None, token=None, form=False):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer '+token
    data = None
    if payload is not None:
        data = urlencode(payload).encode() if form else json.dumps(payload).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    try:
        with build_opener(NoRedirect()).open(Request(url, data=data, headers=headers, method=method), timeout=15) as response:
            value = json.loads(response.read(5_000_001))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except HTTPError as error:
        code = 'google_http_'+str(error.code)
        if error.code in (400, 401):
            try:
                if json.loads(error.read(65536)).get('error') == 'invalid_grant':
                    code = 'google_reconnect_required'
            except (ValueError, TypeError):
                pass
        raise GoogleError(code, ambiguous=method != 'GET' and error.code >= 500) from None
    except (URLError, OSError, TimeoutError, ValueError):
        raise GoogleError('google_transport_error', ambiguous=method != 'GET') from None


def exchange(code, verifier):
    return request('https://oauth2.googleapis.com/token', 'POST', dict(code=code, code_verifier=verifier,
        client_id=settings.GOOGLE_CONTACTS_CLIENT_ID, client_secret=settings.GOOGLE_CONTACTS_CLIENT_SECRET,
        redirect_uri=settings.GOOGLE_CONTACTS_REDIRECT_URI, grant_type='authorization_code'), form=True)


def refresh(refresh_token):
    value = request('https://oauth2.googleapis.com/token', 'POST', dict(refresh_token=refresh_token,
        client_id=settings.GOOGLE_CONTACTS_CLIENT_ID, client_secret=settings.GOOGLE_CONTACTS_CLIENT_SECRET,
        grant_type='refresh_token'), form=True)
    if not isinstance(value.get('access_token'), str):
        raise GoogleError('invalid_token_response')
    return value['access_token']


def identity(token):
    return request('https://openidconnect.googleapis.com/v1/userinfo', token=token)


def resource(name):
    if not re.fullmatch(r'people/[A-Za-z0-9_-]{1,200}', name):
        raise GoogleError('invalid_google_resource')
    return name


def get_person(token, name):
    return request('https://people.googleapis.com/v1/'+resource(name)+'?'+urlencode({'personFields': FIELDS, 'sources': 'READ_SOURCE_TYPE_CONTACT'}), token=token)


def list_people(token, heartbeat=None):
    people, page, seen = [], '', set()
    for _ in range(30):
        if heartbeat:
            heartbeat()
        params = {'personFields': FIELDS, 'pageSize': 1000, 'sources': 'READ_SOURCE_TYPE_CONTACT'}
        if page:
            params['pageToken'] = page
        result = request('https://people.googleapis.com/v1/people/me/connections?'+urlencode(params), token=token)
        people.extend(result.get('connections', []))
        page = result.get('nextPageToken', '')
        if not page:
            return people
        if page in seen:
            break
        seen.add(page)
    raise GoogleError('google_contact_list_too_large')


def create_person(token, payload):
    return request('https://people.googleapis.com/v1/people:createContact?'+urlencode({'personFields': FIELDS}), 'POST', payload, token)


def update_person(token, name, payload, previous):
    sources = [s for s in previous.get('metadata', {}).get('sources', []) if s.get('type') == 'CONTACT']
    if not sources or not sources[0].get('etag'):
        raise GoogleError('google_contact_etag_missing')
    custom = [x for x in previous.get('userDefined', []) if not x.get('key', '').startswith('lmt_crm_')]
    body = {**payload, 'userDefined': custom+payload.get('userDefined', []), 'metadata': {'sources': sources}, 'etag': previous.get('etag', '')}
    return request('https://people.googleapis.com/v1/'+resource(name)+':updateContact?'+urlencode({'updatePersonFields': MANAGED, 'personFields': FIELDS}), 'PATCH', body, token)
