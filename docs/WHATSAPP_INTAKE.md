# WhatsApp identity, enquiry ownership and communication history

Apply migrations before running the updated backend. Configure an existing active manager for each business inbox. New inboxes created through the global-manager API use their creating manager as `intake_actor`; existing inboxes can be configured with:

```powershell
.venv/Scripts/python.exe backend/manage.py configure_whatsapp_intake --actor admin
```

Add `--channel <UUID>` to limit configuration. Optional `--retry-existing` processes previously received conversations and can create real contacts, enquiries and staff reminders. It sends no messages. Configuration does not provision Meta accounts, secrets, webhooks, workers or business phone numbers. Live sends stay behind the existing approval/configuration gate.

Only fresh, latest inbound messages run intake. Unique normalized phone matches in the same branch reuse the Contact ID; unknown phones create a contact with a readable ID. Unverified WhatsApp profile names only label new contacts and never overwrite a matched person's name. Shared-phone and cross-branch matches create a persistent manager identity review. Existing candidates outside branch scope are withheld. A verified cross-branch identity link requires an authorized global manager; it reuses the Contact ID and creates/links a separately scoped branch enquiry.

An existing active linked enquiry retains its counsellor and assignment history. With one active enquiry for the contact in that branch, intake links it. Multiple active course enquiries require a manager choice. If all enquiries are closed, the next fresh message can create a new enquiry with a new Enquiry ID under the same Contact ID. No course is guessed from message text; the default title is “WhatsApp course enquiry,” editable on the lead. Managers may explicitly link an existing enquiry or create a new course enquiry. A retry with the same current course title reuses that enquiry. New enquiries use existing branch availability, capacity and sticky/round-robin routing; lack of capacity sends them to the manager queue.

Inactive inboxes/branches, invalid intake actors and opt-outs do not start new work. Inbound opt-out is recorded without granting consent or creating sales tasks. `auto_intake=false` preserves receipt without automatic CRM creation. The webhook receipt remains durable and the normal `messaging.process_webhooks` worker performs intake. The automation worker alone does not process webhook receipts.

The inbox displays Contact ID, Enquiry ID, course and responsible counsellor. “Assigned to me” is an ownership filter; the shared branch inbox remains available to existing authorized inbox roles. This does not introduce strict per-counsellor chat isolation. Ownership is derived from the linked lead, so reassignment is reflected without maintaining a second owner field. Chat is linked to the person across course enquiries, not split into inferred course-specific message segments.

Managers resolve identity using `/whatsapp/conversations/{id}/resolve-identity/`, choose courses using `/enquiry/`, and retry configuration-blocked intake using `/retry-intake/`. API permissions independently enforce all decisions. Rejected reviews are never silently overridden on the next message.

`GET /contacts/{id}/history/?source=all&page=1` combines authorized WhatsApp messages, logged calls and immutable CRM activity using a database-paginated union. Source options: `all`, `whatsapp`, `call`, `activity`. Each entry shows the time, branch, staff attribution where known, mode/status and available discussion text. Enquiry cards identify ownership and stage. Existing call activity notes may also appear alongside their structured call record. Template history shows the template body and supplied parameters. Media content, voice messages, recordings, automatic transcription and messages predating the CRM connection are not imported.

Contact profile and inbox history respect branch permissions. No live credentials, external messages or fake business inboxes are created by this feature. Existing receipt-only conversations can be processed explicitly by a manager after configuration.
