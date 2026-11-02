# Local CRM

Open http://127.0.0.1:3100 and sign in with your existing account (an active `admin` account is present). Your existing password has not been changed.

The local database is `backend/db.sqlite3`. Back it up before making database changes. This workspace currently uses SQLite; PostgreSQL concurrency and production deployment remain separate work.

Start these commands in three PowerShell terminals from the workspace root:

```powershell
.\.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8000 --noreload
```

```powershell
Set-Location frontend
node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3100
```

```powershell
.\.venv\Scripts\python.exe backend\manage.py run_local_jobs
```

After frontend source changes, run `npm run build` in `frontend` before restarting it. Stop a terminal process with Ctrl+C. Background processes started during setup log to `.cache/backend-local*`, `.cache/frontend-local*`, and `.cache/jobs-local*`; they need restarting after a computer reboot.

`run_local_jobs` processes follow-ups, demo tasks, SLA reminders, assignment retries, received WhatsApp webhook records and simulated outgoing messages every 30 seconds. It requires debug and mock messaging mode. It does not run Google Contacts sync; that integration requires separately configured credentials and its queue processor/Celery.

Local checks: Django system checks and migrations, the frontend production build and lint. Run backend tests from `backend` with `..\.venv\Scripts\python.exe manage.py test --settings=config.test_settings`; SQLite skips PostgreSQL-specific checks.
