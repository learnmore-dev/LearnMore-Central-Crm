# Call logs and enquiry creation

The **Call logs** section (`/calls`) is ready for manual records while MyOperator API integration is deferred. It does not connect to MyOperator, retrieve live calls, dial numbers, send notifications or store recordings.

Staff with sales write access can add incoming/outgoing calls with caller/business numbers, branch, status (answered, missed or voicemail), call time, duration, received-by/forwarded-to text and notes. Search by caller number, contact name or receiving team member; filter by direction and status. Records are scoped to the user's branch; global management can view all branches. Read-only roles cannot add calls or create enquiries.

## Contact matching

Phone numbers are normalized to E.164. A unique existing contact in the call's branch is linked automatically without changing its name or identifiers. A new phone number creates a contact with source `call`; if the caller name is unknown, its initial name is `Caller +NUMBER`. Shared numbers or matches outside the branch create an identity review instead of silently linking people. Candidate details outside the user's scope are redacted. Branch/global managers resolve reviews with a reason before staff create an enquiry.

Saving a call records its details in the contact timeline once its contact is linked. Repeated submissions with the same request key do not create another call/contact; changing the data under that key is rejected. Call records cannot be edited or deleted through the API.

## Right-side enquiry action

Each linked call has a **Create enquiry** button on the right. Enter the enquiry title/course; the server creates a lead with source `call`, keeps the call/contact link and notes, and runs existing branch assignment and follow-up logic. If no counsellor is eligible, the lead remains in the normal unassigned queue.

One call links to one enquiry. Repeated clicks return the existing enquiry, including under concurrent requests. After creation, the row displays **View enquiry**. Unresolved identities show **Review contact** for managers; other staff see the pending-review state.

## API

| Route | Purpose |
| --- | --- |
| `GET /api/v1/call-logs/` | Scoped list; `search`, `status`, `direction` and `page` filters |
| `POST /api/v1/call-logs/` | Authenticated manual entry with stable `client_key`; automatically matches/creates a contact |
| `GET /api/v1/call-logs/{id}/` | Scoped call detail |
| `POST /api/v1/call-logs/{id}/create-enquiry/` | Sales-only action with `title` |
| `POST /api/v1/call-logs/{id}/resolve-contact/` | Manager-only identity decision with reason and optional verified candidate |

Provider origin, contact links and lead links are server-owned. API clients cannot spoof them. All writes retain session authentication, CSRF checks, branch validation and service-layer permissions. There is no public telephony webhook at this stage.

## Setup and verification

```powershell
.\.venv\Scripts\python.exe backend/manage.py migrate
.\.venv\Scripts\python.exe backend/manage.py test calls --settings=config.test_settings
```

Use PostgreSQL to verify concurrency. Tests cover new/existing callers, shared-number reviews, cross-branch redaction, idempotent call creation, enquiry routing and duplicate-click prevention, filters and protected fields. Frontend tests cover the call-row enquiry action and the read-only/disconnected state. No sample calls are inserted into the user's database automatically.

Later MyOperator integration will need its actual webhook/API contract, verified authentication and provider event IDs before importing calls. The current UI explicitly labels all records as manual and displays that the API is not connected.

Verified on 25 October 2026: all **139 backend tests passed on isolated PostgreSQL**, including concurrent call creation and enquiry actions; **17 frontend tests passed**; TypeScript, ESLint, production build, OpenAPI validation and migration checks passed. The isolated PostgreSQL server stopped successfully. The migration is applied locally; open `http://127.0.0.1:3001/calls` and sign in with your existing account. No live MyOperator requests, calls, email or WhatsApp messages were sent.
