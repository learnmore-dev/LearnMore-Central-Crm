# Milestone 2: contacts, identity, enquiries and timeline

Milestone 3 now extends lead intake with routing and adds assignment/task endpoints. The identity contract below remains current; for automatic owner selection, overrides, transfers, task setup and the complete test command, see [MILESTONE_3.md](MILESTONE_3.md).

The Django monolith now has separate `contacts`, `leads` and `activities` apps, with shared authorization and identifier counters in `common`. Apply the new migrations using the existing Windows guide. No external service, frontend, routing engine or customer-data import is part of this milestone.

## Identity and readable IDs

Every Contact and Lead has an internal UUID and an immutable readable `LM-C-000001` or `LM-L-000001` ID. Counters are stored independently of record counts, with a unique primary key and PostgreSQL `SELECT FOR UPDATE` inside the creating transaction. Allocation rolls back with a failed transaction. Committed IDs do not depend on deletions and are never intentionally recycled; IDs are not promised to be gapless. UUIDs and readable IDs are read-only in the API. PostgreSQL triggers also reject updates to readable IDs.

ContactIdentifier supports multiple phones, emails and provider IDs per contact. The `phonenumbers` library validates phone numbers using India as the default region and formats them as E.164. Explicit international numbers retain their country code. Indian trunk prefixes, spaces and punctuation are accepted; invalid numbers, letters and extensions are rejected. Email matching trims whitespace and case-folds the entire address as an explicit CRM matching policy. Provider IDs retain case and require a lowercase provider namespace such as `google` or `meta`. A WhatsApp phone number should be stored as a phone identifier; a separate opaque provider resource ID can use the external kind.

Constraints prevent the same normalized identifier appearing twice on one contact. Phones/emails are deliberately **not globally unique**, since families may share them. A provider resource ID is unique within its provider namespace across the CRM. Deleting contacts, identifiers, leads or timeline events is not exposed by these APIs.

## Duplicate review workflow

1. Intake normalizes identifiers, takes the contact counter lock, searches globally for identifier overlap and inserts in the same transaction. All API identity additions use the same lock, preventing two simultaneous identical intakes from both creating a person.
2. No match creates a Contact, its identifiers and a contact-created Activity atomically (`201`). One or more matches creates a persistent pending DuplicateReview (`409`), without creating or merging a Contact. Even a single exact shared phone or email requires review. Names alone are not a matching key.
3. A branch manager or management resolves the review with a mandatory reason: `linked` explicitly selects an existing candidate; `separate` confirms a distinct person; `rejected` declines the intake. Resolutions record actor, timestamp and reason. Resolved reviews cannot be resolved again.
4. Linking preserves the existing UUID, name, branch, identifiers, leads and activities. It does not copy submitted fields over the existing person or add conflicting identifiers. The reviewed submission remains in the review record. Create a separate Lead for the new enquiry, and add any genuinely new identifiers explicitly.
5. Confirming separate permits a shared phone/email but never a duplicate provider resource ID. Identifier-addition conflicts also create reviews; for those reviews, `separate` confirms the shared identifier on the specified existing contact, while `rejected` leaves it unchanged. They cannot link two existing contacts.

Candidate IDs and resolved-contact IDs are returned only if the viewer can access that contact. A cross-branch collision can return an empty candidate list while still requiring review; management must handle hidden candidates. Pending reviews are available through the duplicate-review list. No automatic or destructive merge is implemented. Matching is exact after normalization, without fuzzy-name matching or an inferred ownership change.

The global contact-counter lock intentionally serializes identity intake/additions. This favors correctness for the initial institute workload. Bulk imports must use the service layer; future optimization should replace this with ordered per-identity locks only after PostgreSQL concurrency tests establish equivalent behavior. Direct bulk ORM writes are not a supported intake path.

## API endpoints

All paths are prefixed `/api/v1/`, require the existing session authentication and CSRF protection on writes, and use paginated lists. UUIDs identify resource URLs. Unknown/read-only input fields are rejected instead of silently accepted.

| Path | Methods and behavior |
| --- | --- |
| `contacts/` | GET scoped list; optional `search` matches name/readable ID; POST safe intake |
| `contacts/{uuid}/` | GET detail; PATCH/PUT name only |
| `contacts/match/` | POST identifiers; returns `needs_review` and visible candidate UUIDs; does not write |
| `contact-identifiers/` | GET scoped list; POST add identifier to a visible, writable contact (idempotent for an existing identical identifier, otherwise 201 or review 409) |
| `contact-identifiers/{uuid}/` | GET; identifiers cannot be edited/deleted |
| `duplicate-reviews/` | GET branch-scoped review queue |
| `duplicate-reviews/{uuid}/` | GET review |
| `duplicate-reviews/{uuid}/resolve/` | POST manager decision/reason and optional candidate `contact` |
| `leads/` | GET scoped list; POST a distinct enquiry; filters `contact`, `owner`, `branch` (UUIDs), `status` |
| `leads/{uuid}/` | GET; PATCH/PUT title, status and next-action fields |
| `activities/` | GET branch-scoped timeline, filtered by `contact` or `lead`; POST an internal note |
| `activities/{uuid}/` | GET immutable event |

Example contact intake:

```json
{
  "full_name": "Example Student",
  "source": "website",
  "identifiers": [
    {"kind": "phone", "value": "9876543210"},
    {"kind": "email", "value": "student@example.com"}
  ]
}
```

Branch-scoped staff default to their own branch; management users without a branch must explicitly supply an active branch UUID. Responses include `identifier_records` with normalized values and generated IDs. Sources are `manual`, `website`, `whatsapp`, `call`; they describe provenance and do not claim a live integration.

Example lead (substitute real development UUIDs):

```json
{
  "contact": "CONTACT-UUID",
  "owner": "COUNSELLOR-UUID",
  "title": "Python course enquiry",
  "source": "manual",
  "next_action": "Call to arrange a demo",
  "next_action_at": "2026-10-26T10:00:00+05:30"
}
```

Statuses are `new`, `contacted`, `qualified`, `won`, `lost`. An active enquiry requires a next action plus deadline, or an explicit `no_followup_reason`. These alternatives cannot be combined. An unowned enquiry must include `unassigned_reason`; this is the explicit queue exception pending Milestone 3 routing. Assigned leads cannot carry an unassigned reason. Database checks enforce the minimum next-action and queue requirements as well.

Owners must be active counsellors/branch managers within the lead branch. Counsellors can initially assign only themselves; managers may select eligible staff in their branch. After creation, owner, branch, contact and source are immutable through these endpoints. Transfers, reassignment, acknowledgement deadlines, availability/capacity and round-robin selection are reserved for Milestone 3's audited routing service.

An internal note supplies `contact`, `body`, optionally `lead`, and `branch` for global users. The backend sets `actor`, `kind=note` and timestamp. Lead/contact/branch references must agree. Automatic events are written in the same transaction as contact/lead changes. Timeline entries cannot be edited/deleted through the API or model save; PostgreSQL also rejects SQL UPDATE/DELETE using a trigger. List order is newest first, with UUID tie-breaking.

## Permissions

| Role | Read | Write |
| --- | --- | --- |
| Super Admin / Management | All branches | Contact/lead/note operations and duplicate resolution |
| Branch Manager | Own branch | Own-branch sales operations and duplicate resolution |
| Counsellor | Own branch | Home-branch contacts/identifiers, own assigned leads and own-branch notes; no duplicate resolution |
| Accounts / Trainer–Support | Own branch | No Milestone 2 sales writes |

A contact becomes visible to another branch only through an explicitly created lead in that branch. The contact's home branch stays unchanged, and only its home branch or management can edit its canonical profile/identifiers. Each lead and Activity retains its own branch scope: seeing a shared contact does not reveal another branch's enquiries or timeline. Inactive branches reject new writes. Branch query parameters cannot expand authorization scope. No financial access is introduced.

## Validation

From the workspace root, use explicit app labels (a bare `manage.py test` from this root does not discover the nested backend apps):

```powershell
.\.venv\Scripts\python.exe -m ensurepip --upgrade
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py check
.\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe backend\manage.py test accounts branches common contacts leads activities
.\.venv\Scripts\python.exe backend\manage.py spectacular --file docs\openapi.yaml --validate --fail-on-warn
```

Use a **dedicated local PostgreSQL database/user**, never production/customer records. SQLite `config.test_settings` remains a smoke-test option, with PostgreSQL trigger/concurrency tests explicitly skipped. See the verification record for results.
