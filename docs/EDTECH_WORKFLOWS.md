# LearnMore student counselling workflows

## Student qualification

On an enquiry detail page, **Student learning goals → Update qualification** captures course interest, student/professional background, online/classroom/hybrid mode, preferred location, weekday/weekend preference, joining timeline, counsellor-assessed readiness and notes. The screen highlights missing course/background/mode/timeline details. Readiness is a staff assessment; it does not automatically promote the lead, infer a budget or mark an admission won.

Only the current enquiry owner and authorized managers can access these additional details. Updates are recorded in the contact/enquiry activity timeline. Saving partial details preserves previously captured values.

## Demo planning

Open **Demos & counselling** (`/demos`) or use **Demos & attendance** on an enquiry. Book a future online or classroom demo with course, time, duration (15–180 minutes) and location/meeting details. The demo does not reserve a trainer or provision an external meeting link. Managers see authorized branches; counsellors see their own enquiries.

- A lead can have one scheduled demo at a time. A booking request key makes retries idempotent. The same key with different details is rejected.
- Booking checks for overlapping scheduled demos for the enquiry's assigned counsellor in the same branch. PostgreSQL branch/lead locks prevent two concurrent bookings from taking the same counsellor slot. Reassignment after booking follows the current lead owner; it does not automatically resolve newly introduced calendar conflicts.
- Booking creates durable **staff tasks**: confirm the demo one hour before it starts and record attendance when it ends. These tasks appear under **Demo follow-ups**. Reminder tasks can be completed with a recorded outcome.
- Rescheduling requires a reason and the current version, cancels previous pending tasks and creates new ones. Stale actions are rejected. Cancelling requires a reason and cancels pending work.
- Staff explicitly record **Attended** or **Did not attend**. Attended cannot be recorded before the start; did-not-attend cannot be recorded before the end. An overdue attendance task does not automatically label a student absent.
- Attended creates an admission-discussion task due in 24 hours. Did-not-attend creates a rebooking task due in one hour. Rebooking cancels the prior pending no-show rebooking task. Completing a task requires an outcome.
- Tasks follow the current active lead owner, or enter the manager queue when unassigned. Closure, branch transfer, an inactive branch or an explicit no-follow-up reason cancels scheduled demos/pending work on the next worker cycle.

No student messages, phone calls, calendar invitations or emails are sent by this workflow. All existing automatic message steps remain simulated. Staff manually perform the callback/confirmation and record the result.

## Manager monitoring

**Needs attention** (`/attention`) is restricted to branch managers and management. It refreshes every 15 seconds and supports authorized branch filtering. Categories include unassigned enquiries, incomplete qualifications, admission-ready enquiries, overdue existing follow-ups, overdue/unassigned automation work, overdue demo tasks, failed/blocked/unknown outbound messages and WhatsApp conversations awaiting an accepted reply.

Each category shows a total and up to ten records linked to the relevant workflow. Categories can overlap; their totals should not be added together as unique student counts. Message review includes clearly labelled mock/live records. WhatsApp reply status follows the existing unified live-feed rules; a simulated reply does not count as a real accepted reply.

The source report counts enquiries **created in the last 30 days**, grouped by recorded source. It shows current won stage and whether those enquiries have any demo booking or attended demo. A booking column can include historical/cancelled bookings. These are enquiry-level counts, not revenue, verified payments or advertising attribution. Raw calls and identity-review submissions enter this report after they become leads.

The worker health card shows the last attempt/success, failure count and redacted exception type. A heartbeat older than two minutes is marked overdue. Each worker cycle independently retries rule processing and demo maintenance; one failed stage does not prevent the other. This health card covers CRM rule/demo maintenance, not the separate messaging transport worker or external provider availability.

## Operations and boundaries

`education.0001_initial` creates qualification, demo, demo-task and worker-health tables. The existing `automation.process` Celery beat job now runs both rule processing and demo maintenance every 30 seconds. For local development the same cycle runs via:

```powershell
.\.venv\Scripts\python.exe backend\manage.py process_automations --watch
```

Use one scheduler/poller. The local helper polls every ten seconds. PostgreSQL is required for production concurrency; SQLite is only the local preview. No default automation rule, student data or privileged user is created by these migrations.

APIs: `/api/v1/education/qualifications/<lead UUID>/`, `/api/v1/education/demos/`, `/api/v1/education/tasks/`, `/api/v1/education/attention/`. All require authenticated sales roles; the monitoring API additionally requires management permissions. System fields cannot be supplied by clients. Demos transferred outside a branch's scope are not exposed to that branch.

Live website forwarding still needs public CRM hosting and website deployment. MyOperator ingestion remains deferred; the private second website still needs source access. AI qualification, trainer scheduling, payments and live automatic WhatsApp sending are separate future work. Real outbound messages require explicit approval and the existing consent/template/window checks.

## Verification

The full isolated PostgreSQL suite passed 190 tests, including concurrent booking protection. All 37 frontend tests passed with two workers; production build, TypeScript, lint, OpenAPI and migration consistency checks passed. The local database was backed up and migrated, both new pages returned HTTP 200, unauthenticated APIs returned 403 and the worker reported healthy cycles. No student seed records or outbound messages were created.
