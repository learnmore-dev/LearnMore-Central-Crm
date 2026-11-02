"""Private custom-format backup of only the configured CRM database."""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
env = dotenv_values(root / '.env')
if env.get('POSTGRES_DB') != 'centralcrm_prod' or env.get('POSTGRES_USER') != 'centralcrm_app':
    raise SystemExit('This backup script is restricted to centralcrm_prod as centralcrm_app.')
backup_dir = root / 'var/backups'
backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
name = 'centralcrm-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.dump'
target = backup_dir / name
child_env = os.environ.copy()
child_env['PGPASSWORD'] = env['POSTGRES_PASSWORD']
with os.fdopen(os.open(str(target) + '.partial', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as file:
    subprocess.run(['pg_dump', '--format=custom', '--no-owner',
                    '--host', env['POSTGRES_HOST'], '--port', env.get('POSTGRES_PORT', '5432'),
                    '--username', env['POSTGRES_USER'], '--dbname', env['POSTGRES_DB']],
                   env=child_env, stdout=file, check=True)
Path(str(target) + '.partial').rename(target)
print(target)
