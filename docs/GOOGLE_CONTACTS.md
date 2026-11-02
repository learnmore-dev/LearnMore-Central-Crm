# Shared Google Contacts integration

Open `/admin/google-contacts` using the existing `admin` account or a CRM Admin. The sidebar entry is **Google Contacts**. The integration is one-way: CRM contact names, phones, emails, company, first enquiry date, enquiry IDs/branches/counsellors/stages and a profile link are published to one shared Google account. Private chat messages, discussion notes, call logs, audio and passwords are not exported. No Google contacts are deleted.

## 1. Configure Google and the server

1. Create/select a project in Google Cloud Console and enable **People API**.
2. Configure the Google Auth Platform consent screen. For a normal Gmail account choose the external audience; in Testing mode add the shared Gmail address as a test user. For internal Google Workspace deployment use the audience supported by your organization. Request `openid`, `email` and `https://www.googleapis.com/auth/contacts`.
3. Create an OAuth client of type **Web application**. Register the exact Authorized redirect URI displayed by the CRM. For the current local preview it is:

   ```text
   http://127.0.0.1:3100/api/v1/integrations/google-contacts/callback/
   ```

   Use `127.0.0.1` consistently while signing in and authorizing; do not switch to `localhost` mid-flow. Production uses the public HTTPS origin and the same callback path. The callback and CRM origin must have identical scheme/host/port. OAuth session cookies must reach Django through the same-origin proxy.
4. Set these variables in the private root `.env` or your production secret manager. Do not enter secrets in chat, frontend code or Git:

   ```dotenv
   GOOGLE_CONTACTS_CLIENT_ID=<web-client-id>
   GOOGLE_CONTACTS_CLIENT_SECRET=<web-client-secret>
   GOOGLE_CONTACTS_ENCRYPTION_KEY=<fernet-key>
   GOOGLE_CONTACTS_REDIRECT_URI=http://127.0.0.1:3100/api/v1/integrations/google-contacts/callback/
   GOOGLE_CONTACTS_CRM_ORIGIN=http://127.0.0.1:3100
   GOOGLE_CONTACTS_EXPECTED_EMAIL=<your-shared-company-google-account>
   ```

5. Generate the encryption key privately in a terminal:

   ```powershell
   .venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Keep this key stable and back it up separately from the database. Changing/losing it requires reconnecting Google. Also configure a persistent `DJANGO_SECRET_KEY`; restarting with a different Django secret invalidates the OAuth browser session. `DJANGO_DEBUG=true` permits local HTTP only. Production must use HTTPS and secure deployment settings.
6. Install the locked requirements, run migrations and restart Django. The frontend proxies to Django through `DJANGO_API_ORIGIN`; the current preview uses backend `http://127.0.0.1:8100` and frontend port 3100.

Google's Testing-mode refresh tokens for these scopes normally expire after seven days. Configure the appropriate publishing/verification status for durable production use; publishing alone does not exempt an application from Google's verification requirements. Never bypass Google security warnings. See [OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server) and [People API contacts](https://developers.google.com/people/v1/contacts).

## 2. Connect and preview

Click **Connect Google account**, choose the shared account and authorize Contacts access. Only the same active CRM administrator/browser session can complete that short-lived, single-use authorization attempt. The server uses authorization code + PKCE, verifies Google account identity/email and requires offline access. It stores only an encrypted refresh token, never the Gmail password. Client secrets and token values are never returned by status/history APIs.

Click **Preview contact sync**. This reads Google contacts and stores an exact local plan; it does not create/update Google contacts. Previews expire after 30 minutes. Example display name: `Rahul · LMT-C-000042`. One person has one Google contact, with multiple enquiry summaries in notes. The stable mapping uses the CRM UUID and a persistent installation marker, so readable-ID changes do not generate a new person.

- **Create:** no existing mapped or matching Google contact.
- **Update:** a mapped contact whose Google managed values have not changed independently.
- **Unchanged:** a known mapping or recovered matching CRM marker requiring no Google field update.
- **Review:** personal Google match, remote edit, shared CRM identity, missing mapped contact or an unknown previous create result.
- **Skip:** no phone/email.

For a personal match or remote-edit review, choose the displayed Google contact, verify identity and explicitly approve replacement of its CRM-managed name/phones/emails/company/notes/CRM link. This saves a local link/baseline only. Build a **new** preview, inspect it and then approve sync. Other custom fields, addresses and birthdays are not part of the update mask. Shared phone/email identities in the CRM must be resolved before automatic creation; the system does not silently merge people. Deleting a mapped Google contact causes review rather than automatic recreation.

## 3. Approve and process

Click **Review & sync → Sync these contacts**. The plan is queued; a worker performs writes sequentially for the Google account. For local development:

```powershell
.venv/Scripts/python.exe backend/manage.py process_google_contacts --watch
```

For deployed operation run the existing Celery worker and beat. Beat invokes `google_contacts.process` every minute. Each tick processes up to 20 items. The UI shows queued/running/complete/partial states, per-item errors and the worker heartbeat. A stopped worker cannot complete queued jobs. Up to 5,000 CRM contacts are supported per plan; the Google scan is capped at 30 pages of up to 1,000 contacts. Larger datasets fail explicitly without a partial scan/write.

The worker rechecks CRM data and Google etags/baselines before writing. A create whose response is lost is marked uncertain and never blindly repeated; a later preview can recover the stable marker after Google propagation. If no matching marker becomes visible, verify the outcome in Google and reconcile operationally rather than forcing another creation. Concurrent manual Google matches after preview stop creation. Do not edit CRM-managed Google fields on mobiles unless you expect a conflict review on the next sync.

## 4. Enable scheduled sync and mobile contacts

After reviewing the first result, enable automatic sync in **Sync settings** (5–1,440-minute interval). This explicitly authorizes future new/changed CRM contacts from all branches to sync to the shared account. Conflict cases continue to be skipped for review. Each full job must finish before the next begins. Automatic processing stops if the connecting administrator loses CRM-admin access, the token requires reconnection or credentials are unavailable.

On each team mobile, sign in to that same Google account and enable Contacts sync. Everyone using the shared account sees the synced contact list; CRM branch permissions do not restrict that Google list. Mobile sync timing is controlled by Google/device settings, not by the CRM. Confirm successful writes at contacts.google.com before troubleshooting a handset.

**Disconnect CRM sync** clears the stored refresh token, cancels queued jobs and disables scheduling. Google contacts remain. It does not revoke the whole OAuth grant; remove the application's permission in Google Account settings separately if desired. Reconnecting the same account can reuse existing stable mappings.

## Operations and privacy

Use the admin screen's status, worker heartbeat and history to inspect failures. Raw Google error bodies and credentials are never logged. Django and Next.js development access logging suppress/redact callback query secrets; production proxies/load balancers must also omit callback query strings from access logs. Do not add analytics to callback URLs. Sync plans contain contact PII and proposed notes, so protect database backups and admin access. No Google writes were performed during implementation; tests mock Google endpoints.
