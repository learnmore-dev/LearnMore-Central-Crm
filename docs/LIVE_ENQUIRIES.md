# Unified live enquiries dashboard

Open **Live enquiries** in the sidebar or visit `http://127.0.0.1:3001/live-enquiries`.

The dashboard combines records already received by this CRM into a single newest-first monitoring feed. It checks for changes every **five seconds**, including while the tab is in the background (subject to browser scheduling), and provides pause/resume and manual refresh controls. It uses polling, not a WebSocket connection. The status bar shows the last successful server timestamp in IST; failed refreshes retain prior data with a visible stale-data warning.

## What appears

| Source | Entry behavior |
| --- | --- |
| Website forms | Every stored website submission, including identity reviews/rejections and submissions with a linked lead |
| Calls | Every stored incoming call, including missed calls and calls not yet converted to an enquiry |
| WhatsApp | One row per conversation with an actual stored inbound message; the latest inbound message moves it up the feed |
| Manual / other direct enquiries | Standalone CRM leads that are not already represented by a linked website submission or incoming call |

An explicitly linked source record and lead count once. Separate manual enquiries remain separate records; phone/contact matches alone do not merge distinct opportunities. Outbound-only WhatsApp conversations and campaign messages do not become incoming enquiries. Outgoing calls are not themselves arrivals, but an enquiry explicitly created from an outgoing call appears as a direct lead.

Each row shows source, caller/contact, course or enquiry title, latest message/notes, originating branch, visible owner, status and receipt time. Recent arrivals have a “Just received” highlight for two minutes. Calls show their original call time separately from when the record entered the CRM. Website links target the exact submission; call links search the caller's number; WhatsApp links open the conversation. When a linked lead is visible, the action opens that enquiry directly.

## Monitoring controls

- Filter by authorized branch, source and workflow state; search name, phone/email or course/title.
- Default period is **Today (IST)**, based on CRM receipt time. Use **Last 24 hours** or **All time** for older records.
- Counters show all arrivals, unassigned created leads, identity reviews and WhatsApp reply alerts. Arrivals that still need a new enquiry are counted separately.
- Source totals respect branch, time and search filters. Status filtering narrows the table while retaining the selected source's summary counts.
- A WhatsApp conversation remains awaiting reply until a real, accepted outbound reply follows the latest inbound timestamp. Mock replies and failed delivery states do not clear that alert. Provider acceptance is not a guarantee that the customer read a reply.
- Pagination returns at most 25 rows per page with a stable timestamp/key order. Database-side unions, counts and pagination avoid loading the entire history into application memory.

## Access and privacy

The read-only API is `GET /api/v1/enquiry-dashboard/`, with optional `branch`, `source`, `status`, `period`, `search` and `page` parameters. It requires an authenticated session and uses private/no-store responses. A dedicated rate limit of 30 reads per minute supports five-second monitoring without consuming the general CRM request allowance.

All source queries are scoped before aggregation. Branch filters cannot expand a user's access. Accounts-only users receive no WhatsApp conversation previews or counts; that source is unavailable to them. Canonical contacts and transferred lead/owner details are only projected when the user can see those records. A transferred lead outside scope is labelled transferred without exposing its owner or lead ID.

This dashboard does not create leads automatically, assign new permissions, change existing accounts or send messages. The existing contact review, enquiry creation, routing and follow-up rules remain in their respective workflows.

## Current integration limits

The feed shows what has reached this database. MyOperator API import remains deferred, public website connection still requires hosting/deployment, and WhatsApp remains in the configured mock/live provider mode. Adding a Call logs or WhatsApp menu alone does not import external provider records. Local manual call records, local website submissions and verified inbound webhook records appear on the next successful poll.

No extra database tables or data migrations are needed for this read-only feature. The local backend/website previews were restarted together with matching environment-only intake secrets; live WhatsApp sends and SMTP notifications remain disabled. Existing account credentials and roles were not changed.

## Verification

The full isolated PostgreSQL suite passed **156 tests, zero skips, in 55.960 seconds**, including source deduplication, latest inbound aggregation, mock-reply behavior, transferred-lead redaction, role/branch restrictions, filters and bounded pagination. The temporary server was stopped after test-database teardown.

All **27 frontend tests passed** across five files. Coverage exercises combined source links, real five-second timer refetches, pause behavior, filter requests and error states. TypeScript, ESLint, production build, OpenAPI validation and migration consistency checks passed. The running `/live-enquiries` page returned HTTP 200 and its unauthenticated API correctly returned HTTP 403. No real provider calls or messages were sent and no sample enquiries were inserted into the user's database.
