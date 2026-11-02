# Website forms → CRM enquiries

The CRM now accepts signed submissions from `learnmoretech.in` and `learnmoretechnologies.in`. Every accepted submission is visible under **Website enquiries** (`/enquiries`). New contacts produce a lead in the **Lead pipeline** with source `website`, course/title, follow-up task and automatic branch routing. Possible duplicate identities remain visible for a manager to verify; matching phone numbers never silently merge people.

## Current local status

- CRM: `http://127.0.0.1:3001/enquiries`; Django API: port 8000.
- Accessible website checkout: `websites/learnmore-website-1`, from `https://github.com/learnmore-dev/learnmore-website-1` (learnmoretech.in). Its `/api/enroll` handler now signs and forwards enquiries and maintains a durable retry outbox. Its local preview runs on `http://127.0.0.1:3002` with SMTP disabled.
- Local synthetic test created **LM-L-000001**, named **Local integration test (synthetic)**. The local website returned a CRM receipt, and its emailSent result was false. No public website was submitted to or changed. The synthetic addition to the website's tracked `data/leads.json` was restored; the CRM test enquiry remains available to inspect.
- The second website repository, `learnmore-dev/learnmore-website-old`, is private and this session has no confirmed repository access. Its CRM receiver/configuration and reusable forwarding adapter are ready, but its form handler has **not** been edited. The supplied repository listing indicates a Next.js App Router site; the actual handlers must be inspected once access is available.
- The CRM is not hosted. Neither public website is connected to this local receiver. Code changes are local and have not been pushed/deployed.

Local signing secrets were generated into backend/website process environments only. They are not committed or printed. After stopping these preview processes, configure matching persistent server environment variables before restarting the integration. Existing CRM login credentials were preserved; restarting Django with a fresh local signing key may require signing in again.

## CRM setup

Run migrations against the intended development database. Use PostgreSQL for concurrent production intake.

```powershell
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py configure_website learnmoretech --branch marathahalli --allowed-branch btm-layout --allowed-branch kalyan-nagar
.\.venv\Scripts\python.exe backend\manage.py configure_website learnmoretechnologies --branch marathahalli --allowed-branch btm-layout --allowed-branch kalyan-nagar
```

The commands create dedicated non-login integration actors with unusable passwords and no staff/admin privileges. The service restricts intake to each source's default branch or explicitly permitted branch codes. Marathahalli is the local default; change the configuration to the business's preferred routing policy. If no eligible counsellor is available, the normal unassigned queue retains the enquiry with a reason.

Set independent random secrets of at least 32 characters in Django's server environment:

```dotenv
WEBSITE_LEARNMORETECH_SECRET=
WEBSITE_LEARNMORETECHNOLOGIES_SECRET=
```

Never put these keys in `NEXT_PUBLIC_*`, HTML or browser JavaScript. Website forms submit to their own server; that server signs requests to Django. No browser CORS allowance or public CRM login credential is needed.

## Website setup

The first repository's forwarding module is [crmForwarder.mjs](../websites/learnmore-website-1/lib/crmForwarder.mjs). It uses only Node built-ins and can be reused in the second website after inspecting its actual handlers. Its caller supplies a stable server-side submission ID and mapped form data:

```typescript
// Only in a Node server route/action, after normal form validation.
import { queueCrmLead } from '@/lib/crmForwarder.mjs';

await queueCrmLead({
  id: savedSubmission.id,
  name,
  email,
  phone,
  program: course,
  message,
  form_name: 'Contact form',
  landing_page: '/contact-us',
  preferred_branch: branchName,
  branch_code: permittedBranchCode,
  training_mode: trainingMode,
});
```

The first site's existing enquiry/demo/course forms converge on `/api/enroll`, so forwarding is applied once in that handler. It preserves existing lead storage and email behavior. It removes the ineffective localhost GET sync and unsigned fire-and-forget webhook. The legacy lead-export API now requires an environment secret instead of a hard-coded fallback. Newsletter subscriptions and WhatsApp/call links are separate flows and do not generate course enquiries through this integration.

Set server-only website variables. Use `learnmoretechnologies` and its corresponding secret/endpoint on the second site:

```dotenv
CRM_INTAKE_ENABLED=true
CRM_WEBSITE_SOURCE=learnmoretech
CRM_INTAKE_URL=https://YOUR-CRM-HOST/api/v1/intake/websites/learnmoretech/
CRM_INTAKE_SECRET=
CRM_OUTBOX_DIR=/private/persistent/path/crm-outbox
```

The matching CRM and website keys must be equal for that source. HTTPS is required except on loopback for local testing. Production cannot use `localhost` or `127.0.0.1`: those addresses refer to the website's own server. The CRM must first be deployed at a reachable HTTPS address with secure settings, database and ingress.

The outbox directory must be private, writable and persistent across releases. Do not put it under `public/` or commit its contents. An ephemeral/serverless filesystem is not a durable outbox; use a persistent worker/storage deployment or replace the adapter storage before deploying there.

Schedule a server job every minute with the same environment as the website:

```sh
node --env-file=/private/path/website.env scripts/retry-crm-outbox.mjs
```

The adapter stores each event before forwarding, uses a five-second HTTP timeout, rejects redirects, and accepts only a valid 202 receipt. Transient/network errors retry with exponential backoff up to 12 attempts. Permanent validation/authentication failures and exhausted retries remain failed records for inspection. After fixing the problem, explicitly replay them with `--retry-failed`. Replays reuse the same submission ID and do not create duplicate CRM enquiries. Only operational counts are printed; secrets and customer details are not logged by the forwarding module. Establish a retention policy for received/failed outbox files.

## API and security contract

Public receiver:

```text
POST /api/v1/intake/websites/learnmoretech/
POST /api/v1/intake/websites/learnmoretechnologies/
Content-Type: application/json
X-Website-Timestamp: UNIX_SECONDS
X-Website-Signature: sha256=HEX_HMAC
```

Sign the exact UTF-8 bytes of `SITE.TIMESTAMP.` followed by the JSON request body using HMAC-SHA256 and that site's secret. The receiver checks the signature in constant time, requires timestamps within five minutes, limits request size and rate, and rejects unknown/system-owned fields. Example payload:

```json
{
  "submission_id": "stable-form-event-uuid",
  "full_name": "Student name",
  "phone": "+919876543210",
  "email": "student@example.com",
  "course": "Python Full Stack",
  "message": "Please call after 5 pm",
  "page_url": "https://learnmoretech.in/contact-us",
  "form_name": "Free demo",
  "branch_code": "marathahalli",
  "preferred_branch": "Marathahalli",
  "training_mode": "Classroom",
  "utm": {"source": "google", "medium": "cpc", "campaign": "python"}
}
```

A name and at least one valid phone/email are required. Phone numbers are normalized to E.164. Source-page URLs must belong to that website; query strings/fragments are stripped. Course/message, training preference and attribution are retained, with useful details recorded in the contact timeline. Submitted branch/owner/status IDs cannot bypass configured routing. A customer request to be contacted is not treated as WhatsApp marketing consent; this integration sends no automatic WhatsApp message.

The public response is only `{"received":true,"receipt_id":"UUID"}` with HTTP 202. It does not reveal CRM matches, contact/lead IDs or counsellors. `(website source, submission_id)` is unique; an unchanged retry returns the same receipt, while changing data under the same ID is rejected.

Authenticated CRM routes:

- `GET /api/v1/website-enquiries/` — scoped submission list, optionally `?status=created|review|rejected`.
- `GET /api/v1/website-enquiries/{id}/` — scoped details, linked lead and visible identity candidates.
- `POST /api/v1/website-enquiries/{id}/resolve/` — manager-only identity decision (`linked`, `separate`, `rejected`) with a reason and, for `linked`, a visible candidate contact.

Resolving a website duplicate creates its lead transactionally, preserving the submitted course/message. Out-of-branch candidate details are redacted. All CRM reads/writes retain branch authorization and session/CSRF checks. Database transactions preserve atomic intake, readable IDs, routing and review history.

## Validation

- Full isolated PostgreSQL 16.15 suite: **130 tests passed, zero skips, in 22.239 seconds**; test database teardown and server shutdown succeeded.
- Frontend: **15 tests passed**; TypeScript, ESLint and production build passed, including `/enquiries`.
- Website adapter: **five Node tests passed**, all HTTP calls mocked. Its Next.js form handler passed the website's TypeScript check.
- OpenAPI validation and migration consistency checks passed.
- Real local HTTP test: website on port 3002 → signed Django receiver on port 8000 → enquiry LM-L-000001, with email disabled. CRM page and same-origin API both returned HTTP 200.

Tests cover routing, normalized validation, idempotent retries, source separation, signature expiry, branch restrictions, atomic rollback, duplicate review permissions/redaction, concurrent identical submissions, distinct shared identities and durable website retries. No request was submitted to a public form and no real email/WhatsApp message was sent. The private second website and public deployment remain pending access/hosting.
