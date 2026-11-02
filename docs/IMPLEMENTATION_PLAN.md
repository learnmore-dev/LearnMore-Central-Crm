# LearnMore Connect implementation plan

## Inspection (24 October 2026)

The workspace was empty, with no Git metadata, application, dependencies file or AGENTS.md. No existing code was changed. The host has Python 3.8.1 (32-bit), Django 4.2.6, Node 24.14.0, npm 11.9.0 and Docker CLI 27.3.1. PostgreSQL CLI is absent and the Docker engine is not running. Existing global Python packages are not a suitable production runtime.

## Architecture and proposed structure

Use a modular Django monolith with versioned DRF APIs, PostgreSQL, Redis-backed Celery and a separate Next.js/React/TypeScript client. Browser authentication uses Django sessions with CSRF protection, preferably through a same-origin reverse proxy. Business services own transactions; provider adapters never own CRM records. Production uses HTTPS, managed secrets, private S3, RDS and Redis on AWS. Channels is deferred until inbox requirements justify it.

```text
backend/
  config/              settings, URLs, ASGI/WSGI, later Celery
  accounts/            custom UUID user, roles, authentication
  branches/            branches and scoped branch API
  common/              shared permission policy
  contacts/            identity, identifiers, duplicate reviews (M2)
  leads/               pipeline (M2)
  activities/          timeline (M2)
  routing/             round-robin and immutable assignments (M3)
  followups/           deadlines and escalation (M3)
  messaging/           conversations, messages, templates (M5)
  enrolments/ fees/ academics/                         (M6)
  calls/ directory/ integrations/ audit/ reports/      (M7)
frontend/              Next.js client (M4; no placeholder live data)
docs/                  setup, architecture and verification
compose.yaml           local PostgreSQL, Redis and backend
```

Dependencies: Python 3.12+, Django 5.2 LTS, DRF, psycopg 3, django-cors-headers, drf-spectacular, python-dotenv, Gunicorn. Celery/Redis, Channels, provider SDKs and Next.js dependencies are added at their milestones. Resolve compatible patched versions and retain the generated lock before release.

Further inspection discovered Python 3.12.10 outside PATH and an existing PostgreSQL 11 service on port 5432. The supported Python is used in an isolated `.venv`; the old PostgreSQL service is left untouched. A cross-platform `backend/requirements.lock.txt` records the resolved dependencies used by Docker and native setup.

## Milestones and acceptance gates

1. **Completed:** project settings, PostgreSQL, custom user before first migration, six roles, three branches, session login/logout/profile, branch authorization, OpenAPI, Windows setup and authentication/permission tests.
2. **Completed:** Contacts and leads: atomic readable ID sequences, E.164 normalization, multiple identities, ambiguous-match review, immutable timeline. See `MILESTONE_2.md` for model/API boundaries and matching policy.
3. **Completed:** Routing and follow-ups: branch rotation, availability/capacity, immutable assignment history, manager queue, acknowledgements and SLA jobs. See `MILESTONE_3.md`.
4. **Completed:** Next.js login/profile, management/branch dashboards, contact/lead pages, queue/tasks, branches, availability and assignment history; loading/error/empty states backed by real API responses. See `MILESTONE_4.md`.
5. **Completed:** Official Meta Cloud API adapter, signed durable/idempotent webhooks, bounded retries, shared inbox, consent/opt-outs, 24-hour window, approved templates and delivery status. Mock mode/live-send gate enforced. See `MILESTONE_5.md`; live sends require explicit approval. Inbox polling is used; Channels is deferred.
6. Enrolments, support ownership, courses/trainers/batches, schedules and separate financial ledger. Restrict financial access; no card data.
7. Provider telephony and manual call logs (no recordings), safe Google People directory sync with conflict review, audit and reports. No SIM-history assumptions.
8. Security review, PostgreSQL concurrency/integration tests, AWS runbooks, backup/restore and authorized pilot deployment.

## Security boundaries

No self-registration or API role escalation. User administration is initially restricted to superusers in Django admin. Management and Super Admin see branches globally; all other roles are scoped to their assigned branch. Branch configuration writes are limited to management and superusers. Future financial endpoints must add explicit accounts/management authorization rather than inheriting generic branch visibility. Inactive users cannot authenticate. Never accept branch scope from client input without authorization.

## Prerequisites and external services

Install Python 3.12+ x64 or start Docker Desktop with Linux containers. PostgreSQL 16 is required for the supported runtime; SQLite is only an explicitly selected isolated smoke-test fallback, never routing/concurrency validation. Redis is provisioned locally for future jobs; no worker is represented as implemented. No API credentials or real customer data are needed in M1. Meta, telephony, Google OAuth, S3 and AWS remain unconfigured until their milestones; development adapters must be clearly labelled when introduced.

Milestones 6–8 remain deferred. Milestones 4 and 5 are documented in their respective runbooks. This foundation is not a production launch.

## Milestone 1 outcome

Implemented and verified against an isolated PostgreSQL 16.15 cluster: initial migrations, branch bootstrap, system checks, migration consistency and 13 passing authentication/authorization tests. OpenAPI validation and production-setting checks also pass. See `VERIFICATION.md` for commands, exact results and remaining setup steps. Docker image execution is unverified because its engine is stopped. No external integrations, deployment or real customer operations were performed.

## Milestone 2 outcome

Implemented Contact, ContactIdentifier, persistent DuplicateReview, Lead and immutable Activity models with scoped REST APIs and transactional services. Normalized identity matching never silently merges people. Locked counters allocate unique readable IDs; PostgreSQL triggers protect those IDs and timeline history. Leads validate owner/branch eligibility, explicit queue reasons and next actions; transfers are deferred to audited routing in Milestone 3.

Verified initial/upgrade migrations, trigger reversal/reapplication, database checks, migration consistency, OpenAPI and deployment settings against isolated PostgreSQL 16.15. All 52 tests passed, including concurrent ID allocation, duplicate intake and duplicate-review resolution; test teardown succeeded. `MILESTONE_2.md` documents the API and policies; `VERIFICATION.md` records commands and results. No production/customer database was accessed.

## Milestone 3 outcome

Implemented branch-local persistent round-robin, sticky eligible ownership, opt-in availability and workload limits, queue fallback/retries, reasoned manager overrides, explicit management-only branch transfers, owner acknowledgement and immutable assignment history protected by PostgreSQL triggers. Branch-first locks cover routing, availability/capacity changes and lead-status updates; cross-branch locks are ordered by UUID. New enquiry intake now routes transactionally. Legacy assigned leads are explicitly baselined after profiles are configured.

Added durable follow-up/callback/appointment/SLA tasks, bounded acknowledgement-timeout reassignment and manager alerts; stale tasks are isolated by assignment version. Celery 5.6.3 with Redis transport supplies minute-based SLA/queue jobs, with a synchronous management command for local verification. Docker Compose includes worker/beat services and Redis health checks. `MILESTONE_3.md` documents exact policy, API, limits and Windows setup.

All 84 tests passed on isolated PostgreSQL 16.15 with successful teardown, including concurrent capacity/fallback, same-lead routing, duplicate SLA workers and opposite branch transfers. Database checks, migration consistency, upgrade/trigger reversal, OpenAPI, deployment settings and Compose validation passed. Live Docker/Redis worker execution remains unverified because the Docker engine is stopped. No customer data, external sends or deployment were involved.
