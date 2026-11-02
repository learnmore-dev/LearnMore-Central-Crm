# Milestone 3: routing, availability and SLA tasks

Implemented in separate `routing` and `followups` apps. Existing contacts, identifiers and duplicate-review workflows are retained. New lead intake now calls the routing service inside the same transaction. Migrations add lead assignment version/deadlines, counsellor profiles, per-branch routing policies, immutable assignment history and durable follow-up tasks. No production data, external messages or deployment is involved.

## Routing policy

Route by branch, preserve an eligible existing owner and distribute new enquiries among eligible branch counsellors.

- The branch is explicitly supplied or defaults to the authenticated employee's branch. Global management must supply a branch when they have no default. No cross-branch fallback is performed.
- A routing profile must exist, be available and have `can_receive_leads=true`. The employee must be active, be a counsellor/branch manager, belong to the lead branch and have spare workload capacity. Missing profiles are deliberately ineligible. New profiles default to unavailable.
- Workload counts `new`, `contacted` and `qualified` leads. Closed leads release capacity. `max_active_leads=0` prevents any assignment. Existing-owner checks exclude the current lead before comparing capacity, so an owner exactly at capacity keeps their own enquiry, while an owner already over capacity becomes ineligible.
- An eligible existing lead owner keeps the branch, acknowledgement deadline, acknowledgement state and rotation position. Repeated routing creates no duplicate history or tasks. Existing Milestone 2 ownership with assignment version zero is baselined on its first routing operation.
- A distinct new enquiry can reuse the eligible owner of the most recent active enquiry for that contact **within the explicitly selected branch**. It remains a separate lead. An explicit initial-owner request cannot replace this eligible owner. A deliberately separate enquiry at a different branch does not move or rewrite earlier leads.
- Otherwise, rotation uses persistent profile IDs in ascending order, wrapping after the stored branch cursor. Only eligible profiles participate. The cursor advances on round-robin assignment, not on owner preservation, explicit initial assignment or manager override.
- For compatibility with Milestone 2, intake can request a valid initial owner; counsellors may only request themselves and managers may request eligible staff in their branch. Such assignments are explicitly labelled in history. Later changes require the manager override endpoint and a mandatory user-supplied reason.
- If nobody is eligible, the enquiry remains in its branch with `owner=null`, a queue reason, an immutable queued event and one durable manager alert task. Repeated failed attempts do not duplicate alerts/history. The queue retry job processes oldest leads first, up to 100 **per branch** per run, so a blocked branch cannot starve another branch.

These services operate on identified contacts/leads; phone-only identity merging remains prohibited by Milestone 2. Inbound adapters should resolve identity and the relevant active lead before invoking routing. Passing another branch to an existing-lead route request is rejected; changing branches requires the explicit transfer operation.

## PostgreSQL concurrency and history

Every supported assignment, profile availability/capacity change and lead-status update first locks the branch row using `SELECT FOR UPDATE`. Cross-branch transfers lock both branches in sorted UUID order before locking the lead. Routing also locks candidate profiles/users and checks committed workload under the branch lock. Creation, cursor movement, assignment, history, timeline and SLA task writes commit or roll back together.

A lead whose branch changed between the initial lookup and lock acquisition returns a retryable `409` rather than acquiring locks in a conflicting order. Background batches retry such leads on a later tick. All production mutation paths must use these services; direct bulk ORM writes, user membership edits and maintenance scripts are not supported routing interfaces. Admin role/branch membership maintenance should be coordinated with routing operations.

AssignmentHistory captures lead, previous/new owner, previous/current branch, reason, timestamp, actor (null for system jobs), status and assignment version. Events include assigned, reassigned, queued, transferred, acknowledged and escalated. History is read-only in the API/model, with a reversible PostgreSQL trigger rejecting raw SQL UPDATE/DELETE. Earlier activities keep their original branch scope after a transfer. History records are scoped to the branch where the event occurred.

Only branch managers/management may override assignments, and they cannot assign an unavailable, unauthorized or over-capacity employee. Only global Management/Super Admin can transfer a lead between branches; a reason and a different active destination are mandatory. Destination rotation chooses a local owner, or retains the transferred enquiry in that branch's queue. An override resets the bounded SLA reassignment counter. No silent branch moves occur.

## SLA behavior

RoutingPolicy defaults: acknowledgement within 15 minutes, initial follow-up within 60 minutes and at most two automatic acknowledgement-timeout reassignments per lead. Managers may configure these per branch. Policy changes affect new deadlines, not existing assignment deadlines.

- A new enquiry without an explicit next-action plan gets `Contact new enquiry` and the configured follow-up deadline. Explicit action/deadline and no-follow-up validation from Milestone 2 remains enforced.
- Each assignment version gets an owner acknowledgement task and, where required, a next-action task. Unassigned leads get a manager queue task instead of an owner reminder. Task deduplication keys are unique in the database.
- Only the assigned owner may acknowledge. Acknowledgement is idempotent and creates immutable history. The generic task-completion endpoint cannot acknowledge on another employee's behalf.
- Overdue acknowledgements produce a manager escalation and try another eligible counsellor in the same branch, excluding the missed owner for that attempt. If there is no alternative, the lead enters the queue. Queue retries can reconsider currently eligible employees. After the configured reassignment limit, the current assignment is retained for manager intervention; no endless automatic rotation occurs.
- Overdue follow-ups, callbacks and appointments escalate to a manager without changing ownership. Alerts do not recursively create more alerts. Manager attention is represented by durable, branch-scoped tasks, not email, WhatsApp or desktop notifications.
- Superseded pending tasks are cancelled. Assignment versions prevent stale tasks from affecting new owners. Closing a lead cancels pending tasks; reopening starts a fresh acknowledgement cycle and follow-up plan. Previously escalated tasks remain historical until explicitly resolved.
- Next-action changes cancel the superseded pending reminder and create/reuse a task keyed by assignment version and normalized action/deadline. Completing the current next-action task requires a replacement action/deadline or an explicit `no_followup_reason`; outcome and next plan are saved atomically. Manual callback/appointment tasks can be completed independently, with a mandatory outcome.
- Callbacks and demo/counselling appointments are supported as explicit tasks. Automatic missed-call ingestion and unanswered-conversation SLAs await their telephony/inbox milestones.

SLA processing locks branch, lead and task, and rechecks task status inside the transaction. Duplicate scheduler deliveries and overlapping workers therefore do not double-reassign or double-escalate. SLA batches process up to 200 pending overdue tasks per tick. Deadlines use timezone-aware datetimes and elapsed minutes; business-hour/holiday calendars are not implemented.

## API

All endpoints use `/api/v1/`, existing session/CSRF authentication, pagination and branch scope. Unknown/generated fields are rejected. Accounts and support roles cannot perform sales writes. Counsellors see their own tasks; branch managers and management see branch/global task queues, including unassigned escalation alerts.

| Endpoint | Operations |
| --- | --- |
| `counsellor-profiles/` | GET profiles/workload; POST manager creates a profile with `user` UUID and optional availability/limit fields |
| `counsellor-profiles/{integer-id}/` | GET; PATCH/PUT settings; counsellors may change only their own `is_available` |
| `routing-policies/` | GET; POST manager configures a branch policy using a branch UUID |
| `routing-policies/{branch-uuid}/` | GET; PATCH/PUT acknowledgement/follow-up minutes and max reassignments |
| `routing/route/` | POST `{ "lead": "UUID" }`; preserve eligible owner or route within the lead branch |
| `routing/override/` | POST `{ "lead": "UUID", "owner": "USER-UUID-or-null", "reason": "..." }`; manager only |
| `routing/transfer/` | POST `{ "lead": "UUID", "branch": "DESTINATION-UUID", "reason": "..." }`; global management only |
| `routing/acknowledge/` | POST `{ "lead": "UUID" }`; owner only |
| `assignment-history/` | GET branch-scoped immutable history, optional `lead=UUID`; detail GET at `{uuid}/` |
| `unassigned/` | GET scoped active unassigned leads; detail GET at `{lead-uuid}/` |
| `follow-up-tasks/` | GET task center; optional `lead`, `status`, `overdue=true`; POST explicit callback, appointment or follow-up |
| `follow-up-tasks/{uuid}/` | GET task; no arbitrary update/delete |
| `follow-up-tasks/{uuid}/complete/` | POST outcome and, for the current next-action task, a new plan or no-follow-up reason |

Availability example (a manager creates/enables a profile; get employee UUIDs from Django admin user URLs):

```json
{"user": "EMPLOYEE-UUID", "is_available": true, "can_receive_leads": true, "max_active_leads": 30}
```

After creation, use the integer profile ID to PATCH availability/limits. Existing profiles/policies should be updated using PATCH rather than POST. A routing policy is created automatically with defaults on first routing; its cursor is always server-controlled.

Manual task creation:

```json
{"lead": "LEAD-UUID", "kind": "callback", "title": "Return missed call", "due_at": "2026-10-26T10:00:00+05:30"}
```

Completing the lead's current next action:

```json
{"resolution": "Counselling completed", "next_action": "Confirm demo attendance", "next_action_at": "2026-10-27T10:00:00+05:30"}
```

Alternatively supply `resolution` plus `no_followup_reason`. Separate manually created callback/appointment tasks only require `resolution` unless the caller also wants to change the lead plan.

## Local setup and jobs

Update the isolated environment and development database:

```powershell
.\.venv\Scripts\python.exe -m ensurepip --upgrade
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt
.\.venv\Scripts\python.exe backend\manage.py migrate
```

Use manager credentials to enable profiles deliberately. The migration does not assume staff availability or reassign old enquiries. Legacy assigned leads retain their owner and version zero until explicitly routed; enable their profiles first, then POST `routing/route/` to establish their baseline history/tasks. Existing unassigned active leads are eligible for queue retry. Inspect this setup before enabling workers against any existing data; do not run it against customer/production records without authorization.

Docker (after migrations and profile setup):

```powershell
docker compose build backend worker beat
docker compose up -d backend worker beat
```

Run exactly one beat scheduler. Redis/db health checks gate worker startup; workers use container database port 5432 even if the host uses another port. In `.env`, set `POSTGRES_PORT=55432` if the existing PostgreSQL 11 service occupies host port 5432. Redis remains loopback-only in local Compose. Docker/Redis broker execution requires a running Docker Desktop engine and is separately identified in the verification record.

For native local development with a reachable Redis, run separate PowerShell terminals from `backend`:

```powershell
..\.venv\Scripts\celery.exe -A config worker --pool=solo --loglevel=info
..\.venv\Scripts\celery.exe -A config beat --loglevel=info
```

Linux containers are the supported worker path; the Windows solo command is a development convenience. Without a broker, one explicit batch can be run from the workspace root:

```powershell
.\.venv\Scripts\python.exe backend\manage.py process_slas
```

No scheduler is installed into Windows automatically. Celery wrappers use the same tested database services and retry operational database errors with bounded exponential backoff.

## Checks

```powershell
.\.venv\Scripts\python.exe backend\manage.py check --database default
.\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe backend\manage.py test accounts branches common contacts leads activities routing followups
.\.venv\Scripts\python.exe backend\manage.py spectacular --file docs\openapi.yaml --validate --fail-on-warn
```

Use a dedicated local PostgreSQL database for these checks. The isolated SQLite settings skip PostgreSQL concurrency/trigger tests and do not establish locking correctness. See `VERIFICATION.md` for actual results, including concurrency, fallback, migration reversal and cleanup checks. Milestones 4–8 remain deferred.
