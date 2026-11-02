# WhatsApp workspace

The sidebar now includes **Chat** (the existing shared WhatsApp inbox) and an expandable **WhatsApp** menu matching the requested sections. All pages require an authenticated messaging role and use branch-scoped Django APIs. Accounts-only users cannot access this workspace. No real messages, ad publishing or ad spending occurred during implementation.

| Section | Implemented behavior |
| --- | --- |
| Campaigns | Manager-created drafts with an account, approved template, text parameters and 1–200 opted-in conversations; explicit mock queue action and actual queue progress |
| Templates | Paginated catalog showing content, approval, supported format, provider mode and last sync; global managers can install a clearly marked mock template in mock mode |
| Message trail | Scoped inbound/outbound history, queue/delivery state, errors and links to the originating chat; refreshes every ten seconds |
| Canned messages | Managers create/edit/archive branch replies; staff insert active replies into the chat composer without automatically sending |
| Accounts | Scoped account list; global management creates/edits local name, enabled state and public WhatsApp number; existing provider IDs/branch cannot be changed |
| Chat widget & QR code | Generates a click-to-chat link, locally generated/downloadable QR PNG and escaped HTML link; uses the public business phone, never the Meta phone-number resource ID |
| Ads | Local Facebook/Instagram attribution drafts with UTM links to the two LearnMore websites; no Meta Marketing API, publishing, billing or spend management |
| Settings | Read-only provider mode, live-send gates, credential-presence flags, Graph version and webhook path; never exposes secret values |

Open `http://127.0.0.1:3001/whatsapp/campaigns`. The local backend migration is applied. Restarting Django with a new development signing key can require signing in again with the existing account.

## Campaign safety and limitations

Campaigns are **simulation-only**. The backend rejects bulk queueing in live mode even when individual live sends have been enabled. There is no live bulk-send endpoint or hidden UI toggle. Drafts do not send anything. A manager must explicitly click **Queue mock campaign**.

Queueing runs atomically under a channel/campaign lock and reuses deterministic message request keys. Repeated queue actions cannot duplicate messages. Every recipient is rechecked for account scope, explicit consent, supported approval, template freshness and provider mode using the existing send policy. If any recipient is no longer eligible, the whole queue transaction rolls back and the campaign remains a draft. Normal outbox workers simulate accepted messages; the existing worker still blocks mock messages across mode changes. No automatic live campaign dispatch has been introduced.

Draft editing/scheduling, recipient CSV import, personalized per-recipient parameters and live campaign delivery are outside this version. The current draft applies the entered text parameters to each selected opted-in conversation. Mock queue progress reports actual stored message state; simulation acceptance is not represented as delivery to a real customer.

## Replies, accounts and QR links

Canned replies are not Meta-approved templates and cannot bypass the 24-hour service window or opt-outs. Inserting one fills the editable reply field; sending still requires the user's explicit queue action and existing backend checks. Archived replies disappear from the insertion menu.

An account marked enabled is enabled locally, not verified as connected to Meta. Global management can set its public business phone under **Accounts**. QR/widget generation is disabled until an enabled account has a number. QR generation happens locally in the frontend with `qrcode`; no phone/message data is uploaded to an external QR service. Clicking the generated chat link opens a composed customer message; it does not automatically send it or grant consent.

Live template approval still uses the authenticated server sync documented in [MILESTONE_5.md](MILESTONE_5.md). A mock template cannot gain live approval by changing modes. Credentials and individual live-send approval remain in server environment variables. Settings displays presence flags only and does not claim a successful provider connection.

## APIs

New endpoints under `/api/v1/whatsapp/`:

- `campaigns/` — scoped GET and manager-only draft POST; `{id}/queue-mock/` explicitly queues a simulation.
- `canned-messages/` — scoped GET, manager-only POST/PATCH; filter with `branch` and `active=true`.
- `ad-drafts/` — scoped GET and manager-only draft POST; returns a generated UTM tracking URL.
- `settings/` — read-only mode, gates and configuration-presence flags.

Existing channel APIs now support global-management PATCH for local settings/public number and `{id}/mock-template/` for simulation setup. Conversation lists can filter by account. Message trail responses include recipient/account labels and support direction/status filters. All CRM API responses remain private/no-store, and writes retain CSRF and independent backend authorization.

## Verification — 25 October 2026

- Full isolated PostgreSQL 16.15 suite: **149 tests passed, zero skips, in 34.489 seconds**; temporary test database destroyed and server stopped.
- Frontend: **23 tests passed** across four files; TypeScript, ESLint and production build passed.
- OpenAPI validation passed; messaging migration generated and applied locally; all eight submenu routes returned HTTP 200.
- Tests cover submenu expansion/highlighting, role-dependent controls, saved-reply persistence/insertion, public-number QR targeting, mock-only campaign policy, queue idempotency/rollback on revoked consent, cross-branch restrictions, immutable provider identity, mock-template mode guards, tracking URLs and secret redaction.

The local database was backed up before migration. Backend and the existing local website preview were restarted with matching process-environment intake secrets. WhatsApp live sends and SMTP notifications remain disabled. No sample campaigns, accounts, recipients or advertisements were inserted into the user's database.
