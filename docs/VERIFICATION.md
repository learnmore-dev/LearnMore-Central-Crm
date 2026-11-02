# LearnMore Connect verification

## Unified live enquiries dashboard

Added a branch-scoped cross-source feed and `/live-enquiries` page combining website submissions, incoming calls, inbound WhatsApp conversations and independent manual leads. Five-second polling, pause/manual refresh, receipt highlights, filters, summary counters and links to source workflows support live monitoring. Linked website/call leads are not counted twice; WhatsApp mock replies do not clear real customer reply alerts. Role/branch and transferred-lead details are independently protected before aggregation.

All **156 backend tests passed on isolated PostgreSQL with zero skips in 55.960 seconds**. The test database was destroyed and temporary server stopped. All **27 frontend tests passed**, including timed polling, pause behavior, multi-source links, filtering and errors. TypeScript, ESLint, production build, OpenAPI validation and migration consistency checks passed. The live page returned HTTP 200; unauthenticated feed access returned HTTP 403. This feature adds no database tables or account/permission changes. No real provider messages were sent or sample records seeded. See [LIVE_ENQUIRIES.md](LIVE_ENQUIRIES.md) for behavior and external-integration limits.

## WhatsApp workspace verification — 25 October 2026

Added the expandable WhatsApp submenu and eight functional local management screens: mock campaign drafts/queue progress, synced templates, message trail, canned replies with chat insertion, accounts, click-to-chat widget/QR generation, ad attribution drafts and read-only settings. Live bulk sends are explicitly rejected; Ads does not publish or spend. New APIs independently enforce roles, branch scope and existing consent/template send policy. See [WHATSAPP_WORKSPACE.md](WHATSAPP_WORKSPACE.md) for exact limits.

Full PostgreSQL suite: **149 tests passed with zero skips in 34.489 seconds**; test database destruction and isolated server shutdown succeeded. Frontend: **23 tests passed**; TypeScript, ESLint, production build and OpenAPI validation passed. All eight running submenu routes returned HTTP 200. The local database was backed up and the migration applied. Backend/website previews were restarted with environment-only credentials, mock mode, live WhatsApp sends disabled and SMTP disabled. No real messages or ads were sent/published, and no sample workspace records were seeded.

## Call-log section verification — 25 October 2026

Added manual call records and the Call logs page, automatic unique-phone contact matching/new-contact creation, manager-reviewed ambiguous matches, and a right-side Create enquiry action. Enquiries retain the call/contact link, source `call`, timeline notes and normal branch routing. MyOperator API integration remains deferred; no public telephony webhook or recordings are implemented.

All **139 tests passed on isolated PostgreSQL 16.15 in 53.951 seconds, zero skips**, including concurrent call retries and enquiry creation. The test database was destroyed and the temporary server stopped. All **17 frontend tests passed**; TypeScript, ESLint, Next.js production build and OpenAPI validation passed. The local database was backed up before applying `calls.0001_initial`; backend and website previews were restarted with matching environment-only intake secrets, with live WhatsApp sends and SMTP notifications disabled. No sample call records were inserted into the user's database. See [CALL_LOGS.md](CALL_LOGS.md) for use and permissions.

## Website enquiry integration — 25 October 2026

Added signed website intake, source/branch configuration, dedicated non-login actors, a scoped Website enquiries page, manager identity review and normal lead routing. Updated the local checkout of `learnmore-dev/learnmore-website-1` with signed forwarding and a persistent retry outbox. The private `learnmore-website-old` receiver is supported, but its form handler remains unmodified pending repository access. Neither public website was changed; the CRM is not hosted.

Full PostgreSQL suite: **130 tests passed, zero skips, in 22.239 seconds**, including two new intake concurrency tests. Test database teardown succeeded, the isolated server on port 55438 stopped, and its temporary password file was removed. Frontend: **15 tests passed**, TypeScript/ESLint/production build passed. Website: **five mocked Node tests passed** and its TypeScript check passed. OpenAPI and migration consistency checks passed.

The local website on port 3002 returned a signed CRM receipt and created synthetic enquiry **LM-L-000001**. Email was disabled; no WhatsApp message was queued. The CRM enquiry remains for inspection; the synthetic change to the cloned website's tracked leads file was restored. Source signing secrets exist only in preview-process environments. See [WEBSITE_ENQUIRIES.md](WEBSITE_ENQUIRIES.md) for exact setup, limits, access and hosting requirements.

## Milestone 5 verification — 25 October 2026

Implemented the official Meta WhatsApp Cloud API adapter, branch-scoped shared inbox, HMAC-verified durable webhook receipts, event deduplication, idempotent outbound queue, consent/opt-outs, 24-hour service windows, approved-template sync, delivery states and bounded retry handling. Credentials are environment-only; configuration defaults to mock mode with live sends disabled. See [MILESTONE_5.md](MILESTONE_5.md) for setup, permissions, policy and recovery operations.

| Check | Final result |
| --- | --- |
| Full SQLite smoke suite, all nine apps | 118 tests passed with 12 PostgreSQL-only skips |
| Full isolated PostgreSQL 16.15 suite, all nine apps | **118 tests passed, zero skips, in 20.622 seconds; test database destruction succeeded** |
| Frontend Vitest/Testing Library | **13 tests passed across three files** |
| TypeScript, ESLint and Next.js production build | Passed; `/inbox` included in production routes |
| Django system check | No issues |
| Migration consistency | No changes detected; messaging initial migration generated |
| OpenAPI regeneration/validation | Passed without warnings |

PostgreSQL verification used a fresh workspace-local cluster on loopback port 55437 with random temporary SCRAM credentials, database `learnmore_m5_verify`, and explicit `config.postgres_test_settings`. It applied all migrations in the test database and exercised concurrent queue submission, competing dispatcher claims and duplicate receipt processing. The prior ID/routing/SLA concurrency tests also passed. The server stopped successfully and the temporary password file was removed. The ignored local runner is `.tools/verify_m5.ps1`; existing PostgreSQL services and the development SQLite database were untouched.

Every Meta HTTP boundary was mocked, including enabled-live-mode transport tests. No real WhatsApp messages were sent, no Meta account was configured, and no application was deployed. Live Meta webhook delivery, Redis/Celery startup and browser end-to-end behavior remain unverified. Supported templates are limited to text-body positional parameters with optional static footer; unsupported variants cannot be sent. Ambiguous outbound outcomes require reconciliation rather than automatic resend. Historical milestone verification follows.

## Milestone 4 verification — 25 October 2026

Resumed and completed the Next.js TypeScript CRM workspace and Django dashboard/directory integration. TypeScript, ESLint and Next.js production build passed. All **11 frontend tests** passed. Django's **91-test SQLite smoke suite passed with nine PostgreSQL-only skips**. OpenAPI regeneration/validation and migration consistency checks passed. No new PostgreSQL concurrency run or browser end-to-end test was performed. See [MILESTONE_4.md](MILESTONE_4.md) for functionality, setup and local database/security configuration limits. Historical milestone results follow.

Milestone 2 implementation details are documented in [MILESTONE_2.md](MILESTONE_2.md), and current routing/task behavior in [MILESTONE_3.md](MILESTONE_3.md). Earlier records below are retained as historical verification; Milestone 3 results follow them.

Verified on 24 October 2026 in this Windows workspace. Milestone 1 passes its database, authentication and permission checks; no later milestone has been started.

## Files delivered

- `backend/config/`: PostgreSQL settings, isolated smoke-test settings, API routes, ASGI and WSGI.
- `backend/accounts/`: custom UUID user, six CRM roles, database branch requirement, protected admin, login/logout/CSRF/profile API, initial migration and authentication tests.
- `backend/branches/`: branch model, scoped list/detail/create/update APIs, protected admin, initial migration, idempotent branch bootstrap command and authorization tests.
- `backend/common/permissions.py`: shared global/branch policy.
- `backend/requirements.txt`, `backend/requirements.lock.txt`: dependency constraints and resolved cross-platform versions.
- `backend/Dockerfile`, `compose.yaml`: local backend, PostgreSQL 16 and Redis.
- `.env.example`, `.gitignore`, `.dockerignore`: configuration template and secret/build exclusions.
- `docs/IMPLEMENTATION_PLAN.md`, `docs/WINDOWS_SETUP.md`, `docs/openapi.yaml`, this record, root/frontend READMEs.

## Commands and results

Initial inspection used `Get-ChildItem -Force`, `rg --files`, `git status --short`, Python/Node/npm/Docker version commands, `python -m pip list`, `docker info`, service inspection and a localhost port probe. No Git repository or existing workspace code was present. PATH selected Python 3.8; Python 3.12.10 was subsequently discovered outside PATH. PostgreSQL 11 occupies port 5432; it was not accessed or modified. Docker CLI exists but its engine was unavailable.

Installed workspace-local `uv` with pip, created `.venv` with Python 3.12.10, and installed dependencies. Resolved Django 5.2.18, DRF 3.16.1 and psycopg 3.3.6. Generated the cross-platform lock using:

```powershell
.\.tools\bin\uv.exe pip compile backend\requirements.txt --universal --output-file backend\requirements.lock.txt
```

The following ran with `.\.venv\Scripts\python.exe backend\manage.py`:

| Arguments | Result |
| --- | --- |
| `makemigrations branches accounts --settings=config.test_settings` | Initial migrations generated |
| `check --settings=config.test_settings` | No issues |
| `test accounts branches --settings=config.test_settings --verbosity 2` | Initial 11-test smoke suite passed on SQLite |
| `spectacular --settings=config.test_settings --file docs/openapi.yaml --validate --fail-on-warn` | Passed; schema generated and revalidated after final API changes |
| `makemigrations --settings=config.test_settings --check --dry-run` | No changes detected |
| `check --deploy --fail-level WARNING` | Passed with DEBUG=false, SSL redirect enabled and a temporary verification secret |

Downloaded the official EDB PostgreSQL 16.15 portable Windows binaries into ignored `.tools/`. Used `initdb` to create a **new isolated cluster**, SCRAM password authentication, random temporary credentials, loopback listener `127.0.0.1:55436` and database `learnmore_verify`. No existing server or customer records were used. Against normal PostgreSQL settings, ran:

```powershell
python backend\manage.py migrate --noinput
python backend\manage.py bootstrap_branches
python backend\manage.py check
python backend\manage.py makemigrations --check --dry-run
python backend\manage.py test accounts branches --verbosity 2
```

All migrations applied; all three configured branches were created; no system-check issues or migration drift. **All 13 tests passed on PostgreSQL 16 in 24.601 seconds.** Django removed its test database, the temporary server was stopped with `pg_ctl -m fast -w stop`, and its temporary password file was removed. The ignored verification cluster/binaries remain local development artifacts; no server is left running and no usable verification credentials are delivered.

`docker compose config --quiet` also passed using a temporary copy of `.env.example`, which was removed immediately afterward. No permanent `.env` was created.

The final PostgreSQL suite covers login/session/logout and CSRF rotation, cross-origin rejection, inactive users, generic credential failures, login validation/throttling, immutable profile role, scoped-user database constraints, staff-admin restrictions, anonymous access, all six roles, cross-branch detail/list filtering, branch writes, uniqueness, deactivation and idempotent bootstrap. Tests contain synthetic records and send no external API requests.

## Remaining manual steps and limits

Follow `WINDOWS_SETUP.md`: create a private `.env`, start Docker Desktop or provision a separate PostgreSQL 16 instance, avoid the existing port 5432, migrate/bootstrap and create your own superuser. No default password is included. The Compose configuration is validated separately; image build/startup was not exercised because the Docker engine was stopped. The Next.js UI and business modules begin at later milestones. Deployment checks are configuration validation, not a production security certification. Shared rate-limit infrastructure, business audit trails, backups, monitoring, integrations and pilot deployment remain gated by later milestones.

## Milestone 2 verification — 24 October 2026

Implemented separate Contact/ContactIdentifier/DuplicateReview, Lead and Activity modules, their APIs/services/tests and database migrations. Shared modules now contain branch-scope helpers, strict input handling, CRM sales permissions and a locked identifier counter. Existing accounts/branches code and initial migrations were preserved; the original 13 tests remain part of the full suite. Settings/URLs, the dependency lock, OpenAPI, README, implementation plan and Windows test instructions were updated. `phonenumbers==9.0.41` is the only added runtime dependency. The workspace still has no Git repository, so Git diff/status verification is unavailable.

Generated the migrations with:

```powershell
.\.venv\Scripts\python.exe backend\manage.py makemigrations common contacts leads activities --settings=config.test_settings
```

Additional reversible PostgreSQL migrations protect readable IDs and Activity history; counter rows are initialized with a data migration. SQLite deliberately omits these PostgreSQL triggers.

| Check | Final result |
| --- | --- |
| Smoke suite, explicit six app labels, SQLite | Initial 49-test suite passed with 4 PostgreSQL-only skips; later additions were validated on PostgreSQL |
| Milestone 1 accounts/branches migrations followed by all Milestone 2 migrations | Passed in a new isolated PostgreSQL 16.15 cluster |
| `bootstrap_branches` | Passed |
| `migrate common 0002` followed by `migrate` | Readable-ID trigger reverse/reapply passed |
| `migrate activities 0003` followed by `migrate` | Timeline trigger reverse/reapply passed |
| `check --database default` | No issues |
| `makemigrations --check --dry-run` | No changes detected |
| `test accounts branches common contacts leads activities --verbosity 2` | **52 tests passed, 0 skipped, in 35.906 seconds; test database destruction succeeded; exit code 0** |
| `spectacular --file docs/openapi.yaml --validate --fail-on-warn` | Passed without warnings/errors |
| `check --deploy --fail-level WARNING` with production security flags and temporary verification secret | No issues |

The complete PostgreSQL command sequence is retained in ignored local `.tools/verify_m2.ps1`; repeatable standard commands are in `MILESTONE_2.md`. Verification used random temporary SCRAM credentials, a new database `learnmore_m2_verify`, a distinct workspace-local cluster and loopback port 55436. PostgreSQL 11 on port 5432 was untouched. The verification server was stopped and the password file removed; no `.env` or real customer data was created. No integration sends or deployment occurred. Docker image execution remains unverified as recorded in Milestone 1.

Earlier development runs exposed a serializer branch-filter error, a schema enum naming issue and unclosed concurrency-worker connections during test teardown. These were fixed before the final successful run. Root-level test discovery requires explicit app labels; the documented commands now include all six tested apps.

Coverage includes E.164 variants/invalid phones, normalized emails/provider IDs, multiple identifiers, identifier uniqueness, shared-phone review without merging, conflicting matches, manager-only decisions with reasons, rejected/repeated resolutions, provider-ID collision protection, cross-branch candidate redaction, canonical profile protection, independent enquiry IDs, next-action/queue invariants, owner eligibility, sales-role access, scope-safe filters, protected API fields, transaction rollback, append-only timeline and PostgreSQL SQL-mutation protection. Threaded PostgreSQL tests use separate connections and barriers to verify unique contact/lead allocations, serialized duplicate intake, a single winning review resolution and counter rollback behavior.

For an existing development installation, install the updated lock and run `migrate` against its development PostgreSQL database. See `MILESTONE_2.md` for endpoint contracts, sample payloads, permission policy and the deliberate global identity-intake lock. Milestones 3–8 remain deferred.

## Milestone 3 verification — 24 October 2026

Added `routing/` models, services, API, migrations, unit tests and separate PostgreSQL concurrency tests; `followups/` task models, services, APIs, Celery wrappers, command and tests; `config/celery.py`; lead assignment/deadline fields and transactional intake/status integration; new Activity kinds. Updated settings, URLs, dependency constraints/lock, Compose worker/beat/health configuration, API schema, Windows setup and milestone documents. Existing migration files were preserved. Earlier tests were retained, with expectations updated where lead creation now produces an assignment event or automatically routes an unowned enquiry.

Generated migrations with:

```powershell
.\.venv\Scripts\python.exe backend\manage.py makemigrations leads activities routing followups --settings=config.test_settings
```

Added a reversible PostgreSQL trigger migration for immutable assignment history. Dependency locking/install resolved `celery==5.6.3`, `redis==6.4.0` and their transport dependencies. No live broker requests are made by tests; Celery wrappers are tested directly with mocked service calls, and database services are tested on PostgreSQL.

| Check | Final result |
| --- | --- |
| Full SQLite smoke suite, all eight apps | 84 tests passed with 9 PostgreSQL-only skips in 2.935 seconds |
| Milestone 2 lead/activity/counter schema, followed by all Milestone 3 migrations | Passed on isolated PostgreSQL 16.15 |
| Counter/Activity trigger reversal/reapplication | Passed |
| `migrate routing 0001` followed by `migrate` | Assignment-history trigger reversal/reapplication passed |
| `bootstrap_branches` and `process_slas` | Passed; empty verification database reported 0 due tasks and 0 queued assignments |
| `check --database default` | No issues |
| `makemigrations --check --dry-run` | No changes detected |
| `test accounts branches common contacts leads activities routing followups --verbosity 2` | **84 tests passed, 0 skipped, in 29.327 seconds; test database destruction succeeded; exit code 0** |
| `spectacular --file docs/openapi.yaml --validate --fail-on-warn` | Passed without warnings/errors |
| `check --deploy --fail-level WARNING` with production security flags | No issues |
| `docker compose config --quiet` | Passed with a temporary `.env.example` copy; the copy was removed afterward |

The final PostgreSQL sequence ran via ignored local `.tools/verify_m3.ps1`, using a new workspace-local cluster, random temporary SCRAM credentials, database `learnmore_m3_verify` and loopback port 55436. It first applied the prior milestone schema and then the new migrations. The existing PostgreSQL 11 service on port 5432 was untouched. The verification server stopped successfully and its password file was removed. No permanent `.env` or customer records were created. The workspace has no Git repository, so Git status/diff is unavailable.

New tests cover persisted branch rotation/fairness; branch-local eligibility; sticky contact/lead ownership and unchanged deadlines; inactive, unavailable, unauthorized and over-capacity employees; missing routing profiles; queue deduplication/recovery; capacity released by closure; manager-only reasoned overrides; global-only explicit branch transfers with previous-owner/branch history; acknowledgement idempotency; profile/limit authorization; assignment rollback; immutable model/API/SQL history; task deadlines; bounded SLA reassignment; no-alternative fallback; overdue follow-up escalation; old-version cancellation; next-action rescheduling/completion; fresh tasks on reopening; task scope and system-field spoofing; synchronous command/Celery adapters.

PostgreSQL concurrency tests use barriers and separate connections, explicitly closed on completion. Six simultaneous enquiries with two one-slot counsellors assigned exactly two leads and queued four, each with history/manager alerts. Six requests for one ineligible-owned lead produced a single reassignment. Six workers claiming one overdue acknowledgement escalated/reassigned once. Opposite-direction branch transfers completed under ordered locks without deadlock. Existing Milestone 2 ID/identity concurrency tests also passed.

Earlier development checks identified schema component/path warnings, which were corrected before the final run. Follow-up completion/reopening cases were added after lifecycle review and passed in the final suite. Docker/Redis worker and beat startup is **not verified** because Docker Desktop's engine is stopped; static Compose validation, Celery wrapper tests and synchronous/PostgreSQL job tests passed. No external notification delivery is claimed: manager alerts are durable tasks. No integration sends or production deployment occurred.

Remaining local steps: install the updated lock, migrate a dedicated development database, configure availability/limits via manager APIs, explicitly baseline any legacy assigned leads, then start Redis plus one worker/one beat scheduler or run `process_slas` manually. Details are in `MILESTONE_3.md`. Milestones 4–8 remain deferred.

## Automation release — 26 October 2026

Implemented branch/source rules, new-arrival enrollment, callback queues, configurable sequences, pause/stop/resume, reply handoff, opt-out/closure checks, task escalation and audit previews. See [AUTOMATION.md](AUTOMATION.md). All message actions are simulation-only and never enter the WhatsApp outbox.

Validation: 174 tests passed with zero skips on isolated PostgreSQL 16 (38.592 seconds), including four-worker enrollment/execution concurrency. A subsequent focused automation SQLite run passed 18 tests and skipped the PostgreSQL-only concurrency case; it includes the final blank-acknowledgement validation test. All 32 frontend tests passed. TypeScript, ESLint, production build and warning-free OpenAPI validation passed. Local migration applied after a database backup; the simulation poller and preview are running. No real messages, calls or privileged-account changes occurred.

## Edtech qualification, demos and manager monitoring — 26 October 2026

Added structured student qualification, internal demo booking, staff reminders, explicit attendance outcomes, no-show rebooking/admission follow-up tasks and a manager attention dashboard with worker-health and 30-day source outcomes. See [EDTECH_WORKFLOWS.md](EDTECH_WORKFLOWS.md).

The full isolated PostgreSQL regression suite passed **190 tests, zero skips, in 51.901 seconds**, including simultaneous competing demo bookings with exactly one successful reservation. The temporary PostgreSQL server shut down after teardown. A final focused SQLite education run passed 14 tests with its PostgreSQL-only test skipped. All **37 frontend tests passed** with `npm test -- --maxWorkers=2`; running tests simultaneously with a production build had caused existing one-second async UI waits to time out, so the final run used limited concurrency. TypeScript, ESLint, production build, warning-free OpenAPI validation and migration consistency checks passed.

Applied `education.0001_initial` after a consistent SQLite backup using the SQLite backup API. Restarted the identified local backend, matching website preview and mock-only polling worker. `/demos` and `/attention` returned HTTP 200; the three education list/monitor APIs returned 403 without a session. Worker logs reported successful rule/demo cycles without errors. No student/demo/rule seed data, privileged accounts or real outbound messages were created. The health heartbeat is the only new operational row created automatically by the worker.
