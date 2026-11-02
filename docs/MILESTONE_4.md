# Milestone 4 — CRM workspace

The Next.js TypeScript frontend integrates Django session, contact, lead, activity, branch, routing, assignment and task APIs. It adds no mock business records. See [frontend setup](../frontend/README.md) for startup and verification commands.

Delivered pages: dashboard with authorized branch selection and pipeline totals; searchable contacts and details with identifiers, timelines, duplicate review and enquiry creation; lead pipeline and unassigned queue; lead editing, acknowledgement, reasoned assignment override and branch transfer; branch creation/editing/deactivation; counsellor availability and workload limits; immutable assignment history; follow-up tasks and profile.

New Django endpoints are `GET /api/v1/dashboard/` and `GET /api/v1/employees/`. Dashboard selections cannot expand branch scope; task totals respect assignee visibility. The scoped employee directory exposes names, roles and routing profile IDs without passwords or email addresses. Serializers provide readable labels, capabilities and record edit flags. APIs independently enforce service-layer permissions, strict input validation and branch scope. Versioned API responses use `Cache-Control: no-store, private`.

Frontend requests use same-origin Next.js rewrites, session cookies and fresh Django CSRF tokens for writes. Query errors expose retry actions; mutations expose server validation errors. Login/session transitions clear cached CRM data. Pagination is explicit; pipeline lane counts represent the current page. Responsive navigation, labelled controls, keyboard focus, native dialogs and reduced-motion styling support desktop and mobile use.

## Verification — 25 October 2026

- Django SQLite smoke suite: **91 tests, nine PostgreSQL-only skips**. New integration tests cover dashboard totals/scope, forbidden branch filters, support task visibility, directory privacy/read-only behavior, superuser capabilities, protected serializer fields, owner edit restrictions and anonymous access.
- Frontend: **11 tests passed**, TypeScript and ESLint checked, and Next.js production build succeeded.
- OpenAPI regenerated and validated without warnings; migration check reports no changes.

No browser end-to-end verification or new PostgreSQL concurrency run is claimed for this milestone; prior PostgreSQL verification is recorded in [VERIFICATION.md](VERIFICATION.md).

The workspace's existing default database configuration currently selects SQLite and disables SSL redirect. Those local settings were preserved. Use PostgreSQL for routing/concurrency validation and secure HTTPS settings before deployment. No customer records were modified, external messages sent or application deployed.
