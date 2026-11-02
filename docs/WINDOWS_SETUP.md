# Windows development setup

## Prerequisites

Use PowerShell, Git and either Docker Desktop with WSL2/Linux containers or Python 3.12+ x64 and PostgreSQL 16. Python 3.8 and the existing PostgreSQL 11 service must not be used. Django 5.2 supports modern Python versions: https://docs.djangoproject.com/en/5.2/releases/5.2/. Official PostgreSQL Windows downloads: https://www.postgresql.org/download/windows/.

Docker CLI alone is insufficient: start Docker Desktop and wait for `docker info` to display a healthy Server section. Do not uninstall or modify any existing database. If port 5432 is occupied, set `POSTGRES_PORT=55432` in `.env`. Compose maps that host port to container port 5432; native Python uses the same environment value.

## Environment

From `C:\django_workspace\centralcrm`:

```powershell
Copy-Item .env.example .env
# Generate two different secrets; paste one into DJANGO_SECRET_KEY and one into POSTGRES_PASSWORD.
# This uses a cryptographic generator and does not require Python.
$bytes = New-Object byte[] 48
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
[Convert]::ToBase64String($bytes)
$rng.GetBytes($bytes)
[Convert]::ToBase64String($bytes)
$rng.Dispose()
```

Edit `.env` before running anything. Keep it private. `DJANGO_DEBUG=true` and `DJANGO_SECURE_SSL_REDIRECT=false` are for local HTTP only. PostgreSQL image credentials are set on first initialization; changing `.env` does not change an existing database password. Never delete volumes containing data to fix a password mismatch.

## Option A: Docker (recommended)

```powershell
docker compose config --quiet
docker compose up -d db redis
docker compose build backend
docker compose run --rm backend python manage.py migrate
docker compose run --rm backend python manage.py bootstrap_branches
docker compose run --rm backend python manage.py createsuperuser
docker compose run --rm backend python manage.py check
docker compose run --rm backend python manage.py makemigrations --check --dry-run
docker compose run --rm backend python manage.py test accounts branches common contacts leads activities routing followups
docker compose up -d backend
```

Open http://localhost:8000/admin/. Create staff through the superuser-only Users admin and set each user's role and branch. Scoped users require a branch at the database level. CRM roles do not automatically grant Django admin access; only superusers can administer users and branches. API documentation is available for staff at http://localhost:8000/api/v1/docs/.

The database account can create test databases in this local setup. Tests use a separate `test_learnmore` database. Never point tests at a production server. Milestone 3 adds Celery/Redis jobs for SLA processing and queue retries. Enable counsellor profiles deliberately before starting worker/beat services; follow [MILESTONE_3.md](MILESTONE_3.md) for those steps and legacy-lead setup.

```powershell
docker compose logs backend
docker compose stop
```

`stop` preserves data. Do not run `down -v` on a database you want to retain. The Docker image uses Django's development server; it is not a production deployment configuration.

## Option B: native Python, container PostgreSQL

Use the actual Python 3.12+ executable if `py` or PATH still selects Python 3.8. For this computer, Python 3.12 was discovered at `C:\Users\prrah\AppData\Local\Programs\Python\Python312\python.exe`.

```powershell
& 'C:\Users\prrah\AppData\Local\Programs\Python\Python312\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt
docker compose up -d db redis
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py bootstrap_branches
.\.venv\Scripts\python.exe backend\manage.py createsuperuser
.\.venv\Scripts\python.exe backend\manage.py check
.\.venv\Scripts\python.exe backend\manage.py test accounts branches common contacts leads activities routing followups
.\.venv\Scripts\python.exe backend\manage.py runserver
```

Activation is optional, avoiding execution-policy changes. If using native PostgreSQL 16 instead, create a new dedicated database/user with SCRAM password authentication, set the `.env` connection values, and give a separate local test user CREATEDB permission. Never reuse production credentials.

## API authentication

1. GET `/api/v1/auth/csrf/` and retain both the session cookies and returned `csrfToken`.
2. POST JSON `{ "username": "...", "password": "..." }` to `/api/v1/auth/login/` with `X-CSRFToken` and cookies. Login itself requires CSRF protection.
3. Fetch a fresh CSRF token after login, because Django rotates it. Use cookies for authenticated GET `/api/v1/auth/me/` and `/api/v1/branches/` requests.
4. Include the fresh CSRF token on POST/PATCH/PUT and POST `/api/v1/auth/logout/`.

For the future frontend, send `credentials: 'include'`. CORS and CSRF origins must exactly match the browser's origin. Use `localhost` consistently rather than mixing it with `127.0.0.1`. Prefer same-origin proxying in production. No public signup, password reset or profile editing endpoint is currently exposed. Superusers provision and maintain accounts using Django admin.

## Isolated smoke tests without PostgreSQL

```powershell
.\.venv\Scripts\python.exe backend\manage.py test accounts branches common contacts leads activities routing followups --settings=config.test_settings
.\.venv\Scripts\python.exe backend\manage.py check --settings=config.test_settings
.\.venv\Scripts\python.exe backend\manage.py spectacular --settings=config.test_settings --file docs\openapi.yaml --validate --fail-on-warn
```

This configuration uses an in-memory SQLite database and a fast test-only password hasher. Never use it to run a real server. It cannot verify PostgreSQL transactions, locks or routing concurrency. The normal settings always use PostgreSQL.

## Before any production pilot

Milestone 8 is the production gate. Use a locked, reviewed dependency set; managed secrets; HTTPS; `DJANGO_DEBUG=false`; exact allowed hosts/origins; secure cookies; and `DJANGO_SECURE_SSL_REDIRECT=true`. Set trusted proxy headers only behind a proxy that strips spoofed values. Run `manage.py check --deploy`, migrations, PostgreSQL tests, backups and restore verification. Use Gunicorn behind a trusted proxy rather than runserver. Collect and serve static assets separately. Current rate limiting uses process-local cache: configure shared Redis cache plus ingress login limits before multiple workers. Logging, comprehensive business audit trails, password recovery, monitoring and external integrations belong to later milestones. Never send live API messages or deploy without authorization.
