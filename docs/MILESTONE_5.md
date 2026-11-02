# Milestone 5 — official WhatsApp Cloud API and shared inbox

Implemented the official Meta Graph API transport, a branch-scoped shared inbox at `/inbox`, durable signature-verified webhooks, idempotent inbound processing, an outbound database queue, approved template sync, customer-service window enforcement, consent/opt-outs, delivery states and bounded retries. Default configuration is **mock mode with live sends disabled**. No real messages were sent during implementation or verification.

## Setup and safe simulation

Install existing backend/frontend dependencies, then migrate a dedicated development database:

```powershell
.\.venv\Scripts\python.exe backend\manage.py migrate
```

Use PostgreSQL for workers and concurrent requests. The workspace's pre-existing SQLite default and disabled SSL redirect were preserved; configure PostgreSQL and HTTPS before deployment. `config.postgres_test_settings` is an explicit isolated test configuration and requires all `POSTGRES_TEST_*` connection variables; it never silently selects the development database.

Keep these defaults until a live pilot has been explicitly approved:

```dotenv
WHATSAPP_MODE=mock
WHATSAPP_LIVE_SENDS_ENABLED=false
WHATSAPP_GRAPH_VERSION=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_APP_SECRET=
WHATSAPP_VERIFY_TOKEN=
```

Credentials are read only from environment variables (or the ignored root `.env`), never stored in CRM models, exposed through API responses, embedded in the frontend, or copied into logs. A single Meta app/token serves the configured channels. The database stores only non-secret WABA/phone IDs. Pin a Meta-supported Graph API version before live reads or sends; no API version is silently guessed. Tokens travel in the Authorization header, never query strings. The HTTP client uses a fixed Graph hostname, a 15-second timeout, and rejects redirects.

Global management can add a business inbox in the UI using a branch, Meta Phone Number ID and WABA ID. Channel identity/branch cannot be changed through the API. A superuser can deactivate a channel through Django admin. To test template composition locally, obtain that channel UUID from `GET /api/v1/whatsapp/channels/` and run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py sync_whatsapp_templates CHANNEL_UUID --mock
```

This explicit command installs `mock_welcome`, marked as simulation-only. It makes no network request. Open a conversation with a test number, record synthetic consent evidence and queue a mock template. A new conversation alone sends nothing. Mock sends receive `mock.*` identifiers and are visibly labelled in the UI; they do not claim real customer delivery. Mock templates/messages cannot become live when configuration changes.

The existing Celery worker and one beat scheduler process webhooks and the outbox every ten seconds. Start them using the Milestone 3 instructions. Alternatively:

```powershell
# Receipts only; does not dispatch outbound messages.
.\.venv\Scripts\python.exe backend\manage.py process_whatsapp
# Explicitly dispatches the outbox using the configured mode and live-send gate.
.\.venv\Scripts\python.exe backend\manage.py process_whatsapp --dispatch
```

No automatic customer reply or message is queued by an inbound webhook.

## Meta configuration and eventual live pilot

Create/configure a Meta business app with the WhatsApp product, WABA and registered business number. Provision a suitable system-user access token with messaging/template permissions and store it in `WHATSAPP_ACCESS_TOKEN`; put the app secret in `WHATSAPP_APP_SECRET`. Choose a strong random `WHATSAPP_VERIFY_TOKEN`. Configure an HTTPS webhook callback at `/api/v1/whatsapp/webhook/`; subscribe the app to the WABA and the `messages` and `message_template_status_update` webhook fields. Configure matching database channels before routing webhook traffic. Verify exact current Meta requirements in the linked references below.

GET verification checks `hub.mode=subscribe`, compares `hub.verify_token` in constant time and returns `hub.challenge`. POST verification computes HMAC-SHA256 over the untouched request bytes and checks `X-Hub-Signature-256` before parsing or storing anything. This endpoint uses signature authentication and is CSRF-exempt. Session-authenticated CRM writes retain Django CSRF protection. Missing app-secret configuration returns 503; bad signatures return 403, malformed envelopes 400 and oversized bodies 413.

Template sync is read-only and never sends messages. After configuring credentials and `WHATSAPP_MODE=live` while **keeping `WHATSAPP_LIVE_SENDS_ENABLED=false`**, run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py sync_whatsapp_templates CHANNEL_UUID
```

All pages of the template catalog are fetched before updating local approvals. Pagination uses cursors against the fixed Graph endpoint rather than following provider-supplied URLs. Only `APPROVED` templates with a body, optional static footer and contiguous numbered text body parameters are sendable. Media/header/button/authentication/named-parameter variants remain visible as unsupported and cannot be queued. Missing templates are disabled; signed template-status changes invalidate approvals immediately. Even an APPROVED status webhook requires an authenticated resync before use. Sync within 24 hours of use and whenever Meta changes a template.

**Enabling live sends requires the user's explicit approval.** No implementation/test step enables them. After approval and configuration review, an operator may set `WHATSAPP_MODE=live` and `WHATSAPP_LIVE_SENDS_ENABLED=true`, restart backend/workers, and run the agreed pilot. Both enqueue and dispatch enforce these settings; the transport checks again. Existing queued mock messages are blocked across mode changes. Already claimed requests cannot be recalled by changing configuration.

## Inbox, identity and permissions

Management/superusers see all authorized inboxes; branch managers, counsellors and support see only their branch. Accounts-only users cannot access messaging. Only global management creates channels. Staff can record consent evidence and queue replies in active authorized inboxes. A branch manager or global manager can explicitly link an unlinked conversation to an existing contact in the inbox's branch. Inbound phone numbers never silently merge contacts, create canonical identities or change lead ownership. Existing links cannot be replaced through the API.

Conversations are unique by business phone channel and customer WhatsApp number. Consent is scoped to that conversation. Template messages require explicit recorded opt-in with evidence, inside or outside the service window. STOP, UNSUBSCRIBE, CANCEL, END and QUIT revoke consent and block all subsequent sends, including queued messages. Re-enabling requires new explicit consent evidence; arbitrary inbound text never silently restores consent. Consent changes retain actor/evidence records.

Free-form text is allowed only strictly within 24 hours of the latest customer message timestamp. The worker rechecks the window, opt-out, active branch/channel, active sender permissions, template approval/freshness and mode before claiming a dispatch. Delayed/old webhooks cannot reopen the window. Unsupported inbound media are recorded as clearly labelled placeholders; files are not downloaded, rendered or forwarded. Inbox queries poll every ten seconds and support search/pagination, loading/error/empty states and server validation messages. UI retries reuse the same client key for an unchanged draft.

## Durability, retries and operations

- Signed envelopes are stored transactionally before returning 200. Processing is independent of Redis availability; beat/commands poll pending receipts. Exact-envelope SHA-256 hashes prevent receipt duplication; event keys and unique provider message IDs prevent duplicates across different envelopes.
- PostgreSQL row locks serialize claims per channel. Outbound `(conversation, client_key)` uniqueness makes submission retries idempotent; changing a payload with the same key is rejected. Clients must generate a fresh key for a genuinely new message.
- Messages are claimed and committed **before** HTTP dispatch. Multiple workers cannot send a queued row twice. A process crash or claim older than five minutes becomes `unknown`, never an automatic resend.
- Definite rate-limit/transient rejections retry up to five attempts with exponential backoff starting at 30 seconds; Retry-After is respected up to an hour. Permanent rejection becomes `failed`. Transport timeouts, malformed successful responses and potentially ambiguous HTTP 5xx outcomes become `unknown` because Meta may already have accepted the message. Exactly-once delivery across a network timeout cannot be guaranteed by a local database.
- Meta delivery webhooks correlate by provider message ID or outbound UUID callback, always requiring a matching channel and recipient. `sent`, `delivered`, `read` and `failed` are idempotent; late lower states never undo delivery/read. A signed status can reconcile an unknown send. Numeric failure codes are retained without raw provider diagnostics. Failed delivery notifications do not automatically generate a new message.
- Valid items in a mixed webhook batch persist even if another item is malformed or unmatched. Unmatched statuses/configuration errors retry up to five receipt attempts. Malformed/exhausted receipts stay available as dead letters. Superusers can inspect them in Django admin, correct configuration and explicitly schedule idempotent reprocessing. Reprocessing does not resend outbound messages.
- Superusers can inspect message queue state, errors and webhook receipts in read-only admin views. For unknown outbound outcomes, check Meta's delivery evidence/provider ID before composing any new message. There is deliberately no automatic or one-click retry of an unknown send. Raw signed receipts contain customer data and require a production retention/access policy.

## API

All CRM routes below require session authentication and return private/no-store responses:

| Endpoint | Behavior |
| --- | --- |
| `/api/v1/whatsapp/channels/` | Scoped GET; global-management-only POST |
| `/api/v1/whatsapp/conversations/` | Scoped GET and open-conversation POST |
| `/api/v1/whatsapp/conversations/{id}/` | Scoped GET, including live/mock and window state |
| `/api/v1/whatsapp/conversations/{id}/consent/` | POST `state`, `evidence` |
| `/api/v1/whatsapp/conversations/{id}/link/` | Manager-only POST `contact` |
| `/api/v1/whatsapp/messages/?conversation={id}` | Scoped GET; POST queues a text/template message and returns 202 |
| `/api/v1/whatsapp/templates/?channel={id}` | Scoped read-only template catalog |

Example queue payloads:

```json
{"conversation":"UUID","client_key":"unique-request-key","text":"How can we help?"}
```

```json
{"conversation":"UUID","client_key":"another-request-key","template":"TEMPLATE_UUID","parameters":["Student"]}
```

Queue/provider statuses, credentials and other system-owned fields cannot be supplied by API clients. The public Meta webhook is documented separately above and is authenticated by its app-secret signature.

## Verification

Final checks on 25 October 2026: **118 backend tests passed on isolated PostgreSQL 16.15 with zero skips; 13 frontend tests passed; TypeScript, ESLint, production build, Django system checks, migration consistency and OpenAPI validation passed.** The temporary PostgreSQL server was stopped and its temporary password file removed.

All Meta HTTP operations were mocked. Tests cover signature/handshake, receipt/event deduplication, malformed batches, old timestamps, scope and role/CSRF denials, protected fields, approval freshness/revocation, consent, mode changes, window expiry between enqueue/dispatch, transient/permanent/ambiguous outcomes, retry bounds, stale claims, payload shape, Authorization transport, redirect blocking, template pagination and unsupported components. PostgreSQL tests cover concurrent submission, competing dispatch workers and duplicate receipt processing. Frontend tests cover window blocking and retention of a draft/client key after an API failure.

```powershell
.\.venv\Scripts\python.exe backend\manage.py test accounts branches common contacts leads activities routing followups messaging --settings=config.test_settings
.\.venv\Scripts\python.exe backend\manage.py makemigrations --settings=config.test_settings --check --dry-run
.\.venv\Scripts\python.exe backend\manage.py spectacular --settings=config.test_settings --file docs/openapi.yaml --validate --fail-on-warn
cd frontend
npm test
npm run typecheck
npm run lint
npm run build
```

SQLite deliberately skips PostgreSQL concurrency tests. PostgreSQL verification uses `config.postgres_test_settings` against a new isolated cluster; production/development customer databases are untouched. Live Meta credentials, webhook delivery from Meta, Redis/Celery deployment and browser end-to-end behavior are not represented as verified. No provider account was configured and no real message was sent.

## Provider references

- [Meta WhatsApp Cloud API documentation](https://developers.facebook.com/documentation/business-messaging/whatsapp/overview)
- [Meta's official send-text request](https://www.postman.com/meta/whatsapp-business-platform/request/8gvd47s/send-text-message)
- [Meta's official template catalog request](https://www.postman.com/meta/whatsapp-business-platform/request/qtgr0i7/get-all-templates-default-fields)
- [Meta-hosted webhook verification reference](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/webhooks/start/)

Meta's current documentation site returned HTTP 429 during implementation; transport references were cross-checked against Meta's official Postman collection and Meta-hosted SDK webhook reference. The archived SDK is used only as protocol documentation, not as an application dependency.
