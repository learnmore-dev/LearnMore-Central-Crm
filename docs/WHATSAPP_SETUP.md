# WhatsApp connection setup

Open **WhatsApp → Settings** (`/whatsapp/settings`). An organization administrator (including a superuser) can save the shared Meta credentials and run a read-only connection check. Branch managers and counsellors see readiness without credential-editing controls. Configuration does not enable sending or queue messages.

## Server preparation

Apply `messaging.0004_whatsapp_connection` before starting the updated web app and workers:

```powershell
.\.venv\Scripts\python.exe backend\manage.py migrate
```

Set a private, stable `WHATSAPP_ENCRYPTION_KEY` in the **root backend `.env`** or deployment secret store. Generate a Fernet key with `cryptography.fernet.Fernet.generate_key()`. Do not put it in `frontend/.env`, `NEXT_PUBLIC_*`, source control or browser storage. Restart web and worker processes after changing server environment configuration. The local workspace has a generated key and the migration applied; no Meta credentials were invented or added.

Credentials saved through the UI are Fernet-encrypted in `WhatsAppConnection`. The encryption key is not stored in the database. Keep a secure copy with your deployment secrets: losing or replacing it makes existing saved credentials unreadable. There is no automatic key-rotation routine; arrange re-encryption or re-enter credentials when intentionally rotating the key. Invalid or missing keys fail closed.

## Connect LearnMore

1. In **WhatsApp → Accounts**, add the correct branch, public business number, Meta phone number ID and WhatsApp Business account ID. These identifiers are not the access token.
2. In **Settings**, enter the Graph API version supported by your Meta app, the access token, app secret and webhook verification token. Use a token with access to the selected WhatsApp Business account. The version is deliberately not hardcoded.
3. Enter your public HTTPS callback URL ending in `/api/v1/whatsapp/webhook/`. The UI can generate and copy a verification token. Copy a generated token into Meta before saving, because the saved value will not be returned to the browser.
4. Save settings. Blank secret inputs preserve existing credentials, and successfully saved secret inputs clear. Saved encrypted fields override their corresponding legacy `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET` and `WHATSAPP_VERIFY_TOKEN` environment values. Unset fields keep using server environment values. The Graph API version follows the same saved-then-environment precedence.
5. Select an enabled account and choose **Check Meta connection**. The server performs `GET /<WABA_ID>/phone_numbers` against the fixed HTTPS Graph API host and verifies the saved phone ID belongs to that account. Cursor pagination never follows provider-returned URLs. This check sends no message and does not prove template, sending, or webhook readiness.
6. In Meta, configure the callback URL with the same verification token and subscribe to WhatsApp `messages` events. A successful challenge records `webhook_verified_at`; credential/configuration changes clear that timestamp. Incoming webhook signatures use the saved app secret. Refresh readiness after verifying the callback.

Use the [Meta app dashboard](https://developers.facebook.com/apps/) and [Meta's WhatsApp Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api) for the account's setup details. The callback must be publicly reachable; localhost is not accessible to Meta.

## Sending and automation

`WHATSAPP_MODE` and `WHATSAPP_LIVE_SENDS_ENABLED` remain server-owned and cannot be submitted through the settings API. Saving credentials does not change them. Existing consent, template, service-window and outbound queue checks remain in effect. Bulk live sends remain disabled, and automation-rule message steps remain audit previews. No message is sent by saving settings or checking account access.

## API

- `GET /api/v1/whatsapp/settings/`: readiness flags, Graph version, callback URL and challenge timestamp; no secret values.
- `PATCH /api/v1/whatsapp/settings/`: global-administrator-only write-only secret updates, Graph version and public callback URL. Unknown fields such as live-send controls are rejected.
- `POST /api/v1/whatsapp/settings/check/`: global-administrator-only check with `{ "channel": "<UUID>" }`. Limited to ten checks per user per minute. Returns sanitized status/details and the provider's business display name/number on success. Raw provider diagnostics and tokens are never returned.

Back-end tests mock every Meta network boundary, covering encrypted storage, unchanged sending gates, permissions, blank preservation, signature verification, account membership, pagination and error redaction. UI tests cover saving/clearing secrets, account checks, administrator-only controls, token generation/copy and unavailable storage.
