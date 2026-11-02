# Ubuntu production deployment

This runbook is for Ubuntu 24.04, existing PostgreSQL 14, domain `crm.edulearnntech.in` and EC2 public address `13.207.184.245`. It installs the CRM alongside existing databases, with no PostgreSQL restart or configuration change. Run as `ubuntu` in `~/apps/centralcrm-test` unless a command explicitly uses sudo. The folder name does not select test mode; services select `config.production_settings`.

Production infrastructure does not enable external integrations. WhatsApp remains mock; Google Contacts and website secrets start empty. No existing local data or passwords are copied from the Windows workspace.

## DNS and network

Create an A record `crm` under `edulearnntech.in` pointing to `13.207.184.245`. Remove a conflicting AAAA record unless IPv6 is deliberately configured. Use an Elastic IP for a stable EC2 address.

In the EC2 security group allow inbound TCP 80 and 443 for the website. Keep SSH 22 limited to your administration addresses. Do not add public access for 8100, 3100 or 6381. Review current access to 5432: do not remove rules needed by existing clients, and restrict them to those clients rather than exposing the database to everyone.

```bash
getent ahostsv4 crm.edulearnntech.in
free -h
df -h /
sudo ss -ltnp
```

Confirm DNS resolves to the EC2 address and ports 80, 443, 3100, 8100 and 6381 are available. Build resources depend on the instance; check memory before running the frontend build. Do not start services if these ports belong to other applications.

## Install runtime packages

```bash
cd ~/apps/centralcrm-test
git pull --ff-only origin main
sudo apt update
sudo apt install -y python3-venv python3-pip curl ca-certificates xz-utils nginx certbot redis-server
bash deploy/ubuntu/install_node.sh
export PATH="$HOME/.local/bin:$PATH"
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock.txt
cd frontend
npm ci
cd ..
```

The Node installer uses official Node 22 archives and validates their published SHA256 digest. It installs under your home directory. The new CRM Redis instance will use 6381 rather than the system Redis port. Do not stop any existing Redis service.

## Create the dedicated database

Choose a unique database password of at least 16 characters. For the environment generator, use letters, digits and punctuation without whitespace, quotes, backslashes or dollar signs. Do not reuse an existing database password. Enter the following interactively; if a role or database already exists, stop and inspect it rather than deleting or overwriting it.

```bash
sudo -u postgres psql -v ON_ERROR_STOP=1
```

Inside psql:

```sql
CREATE ROLE centralcrm_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
\password centralcrm_app
CREATE DATABASE centralcrm_prod OWNER centralcrm_app;
REVOKE ALL ON DATABASE centralcrm_prod FROM PUBLIC;
\connect centralcrm_prod
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO centralcrm_app;
\q
```

This changes only the new CRM role and database. The dedicated login has no administrator privileges; have the database administrator review any PUBLIC grants on other databases if stronger cross-database separation is required. Databases on the same PostgreSQL server still share CPU, memory and disk.

## Create secrets and initialize the CRM

```bash
.venv/bin/python deploy/ubuntu/prepare_environment.py
export DJANGO_SETTINGS_MODULE=config.production_settings
.venv/bin/python backend/manage.py check --deploy --fail-level WARNING
.venv/bin/python backend/manage.py migrate --plan
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py bootstrap_branches
.venv/bin/python backend/manage.py createsuperuser
.venv/bin/python backend/manage.py collectstatic --noinput
sudo install -d -m 755 /var/www/centralcrm/static /var/www/centralcrm/acme
sudo cp -R backend/staticfiles/. /var/www/centralcrm/static/
sudo find /var/www/centralcrm/static -type d -exec chmod 755 {} +
sudo find /var/www/centralcrm/static -type f -exec chmod 644 {} +
```

The environment generator asks for the database password entered in psql. It generates independent Django and Redis secrets and refuses to overwrite an existing `.env`. Do not paste `.env` content into chat or commit it.

## Build and review services

```bash
export DJANGO_API_ORIGIN=http://127.0.0.1:8100
cd frontend
npm run typecheck
npm run lint
npm run build
cd ..
.venv/bin/python deploy/ubuntu/create_service_files.py
cat .cache/systemd/centralcrm-*.service
sudo systemd-analyze verify .cache/systemd/centralcrm-*.service
sudo cp .cache/systemd/centralcrm-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now centralcrm-redis centralcrm-backend centralcrm-frontend centralcrm-worker centralcrm-beat
sudo systemctl --no-pager status centralcrm-redis centralcrm-backend centralcrm-frontend centralcrm-worker centralcrm-beat
```

Gunicorn listens only on 8100, Next.js on 3100, and the private authenticated Redis process on 6381. Only Nginx exposes the website. Worker and scheduler use the same PostgreSQL settings as Gunicorn. Do not also run `run_local_jobs` or a second Celery beat scheduler. Redis persists its queue in `var/redis`.

## Obtain HTTPS and configure Nginx

DNS must be correct and port 80 reachable before requesting a certificate. Create only this site's configuration; retain configurations for other domains. First create an HTTP-only ACME bootstrap:

```bash
sudo tee /etc/nginx/sites-available/centralcrm >/dev/null <<'NGINX'
server {
    listen 80;
    server_name crm.edulearnntech.in;
    location /.well-known/acme-challenge/ { root /var/www/centralcrm/acme; }
    location / { return 503; }
}
NGINX
sudo ln -s /etc/nginx/sites-available/centralcrm /etc/nginx/sites-enabled/centralcrm
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/centralcrm/acme -d crm.edulearnntech.in
```

Enter your own notification email when Certbot asks. If the site file or symlink already exists, inspect it before replacing it. Then install the HTTPS configuration:

```bash
sudo install -m 644 deploy/ubuntu/centralcrm-proxy.conf /etc/nginx/snippets/centralcrm-proxy.conf
sudo install -m 644 deploy/ubuntu/nginx.conf /etc/nginx/sites-available/centralcrm
sudo nginx -t
sudo systemctl reload nginx
sudo install -d /etc/letsencrypt/renewal-hooks/deploy
printf '#!/bin/sh\n/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx\n' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/centralcrm-nginx.sh >/dev/null
sudo chmod 755 /etc/letsencrypt/renewal-hooks/deploy/centralcrm-nginx.sh
sudo certbot renew --dry-run
```

## Verify before staff use

```bash
curl -I http://crm.edulearnntech.in
curl -I https://crm.edulearnntech.in
curl -sS https://crm.edulearnntech.in/api/v1/auth/csrf/
sudo ss -ltnp
sudo journalctl -u centralcrm-backend -u centralcrm-worker -u centralcrm-beat -n 50 --no-pager
```

HTTP should redirect to HTTPS, the frontend should return 200, and CSRF should return JSON. Open the HTTPS site and sign in with the new superuser. Verify employee branch access, create a test contact/enquiry, confirm assignment and task processing, and check mock messages without contacting real customers. Run isolated PostgreSQL concurrency tests with a separate test database/user, never the production credentials; see `config/postgres_test_settings.py` and the verification runbooks. The shipped settings tests do not replace server-side PostgreSQL and browser verification.

## Backups and updates

```bash
.venv/bin/python deploy/ubuntu/backup_database.py
```

This writes a private custom-format backup under `var/backups` without exposing the password. Copy backups to a private off-server location, automate a schedule and retention policy, and restore a backup into a separate database to verify recovery before relying on the CRM. Monitor disk use, failed units, HTTPS expiry and queue health. Preserve `.env` securely for recovery.

For updates, back up first, review migration plans and use a maintenance window. Stop only the CRM services, pull with `--ff-only`, install locked dependencies, build the frontend, apply migrations with `DJANGO_SETTINGS_MODULE=config.production_settings`, collect/copy static assets again, and restart the five CRM services. Recheck login and follow-up processing. Code rollback alone may not reverse database migrations.

## References

- Django PostgreSQL requirements: https://docs.djangoproject.com/en/5.2/ref/databases/#postgresql-notes
- Django deployment checklist: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- Node release archives: https://nodejs.org/dist/latest-v22.x/
- Gunicorn deployment: https://docs.gunicorn.org/en/stable/deploy.html
- Nginx login limiting: https://nginx.org/en/docs/http/ngx_http_limit_req_module.html
