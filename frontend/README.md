# LearnMore Connect frontend

Responsive Next.js TypeScript CRM backed by real Django APIs. Includes dashboard, contacts and timelines, duplicate review, lead pipeline and editing, routing, tasks, branches, availability, assignment history, profile and the shared WhatsApp inbox.

The `/inbox` page supports conversation search, consent evidence, text/template queueing, delivery states and manager-authorized contact linking. It polls every ten seconds. Mock mode is visibly labelled and is the default; see [WhatsApp setup](../docs/MILESTONE_5.md) for channel configuration, workers, template sync and the live-send approval gate.

Use Node 22 or newer. From this directory:

```powershell
npm ci
$env:DJANGO_API_ORIGIN = 'http://127.0.0.1:8000'
npm run dev
```

Open `http://127.0.0.1:3000`. Start Django separately and sign in with an existing active Django user. No default account is supplied. Next.js proxies `/api/v1/` to `DJANGO_API_ORIGIN`, which must be a plain HTTP(S) origin. Include the frontend origin in `DJANGO_CSRF_TRUSTED_ORIGINS`, for example `http://127.0.0.1:3000,http://localhost:3000`. Local HTTP requires `DJANGO_DEBUG=true`; production requires HTTPS and secure Django settings.

Queries provide loading, retryable error, empty and pagination states. Writes fetch fresh CSRF tokens and include session cookies. Session expiration clears cached CRM records. Backend capabilities and edit flags control actions; Django independently scopes reads and authorizes writes. Counsellors manage their availability; managers control eligibility and capacity. Branch transfers require global management access and a reason.

```powershell
npm run typecheck
npm run lint
npm test
npm run build
npm start
```

Vitest/Testing Library cover API transport, CSRF, session expiration, errors, permission controls, login, availability writes and history. No browser end-to-end suite is currently configured. See [Milestone 4](../docs/MILESTONE_4.md) for verification and limits.
