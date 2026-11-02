"""Render systemd unit files for review; does not install or start services."""
import getpass
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[2]
if sys.platform != 'linux' or getpass.getuser() == 'root':
    raise SystemExit('Run on Ubuntu as the non-root CRM deployment user.')
if any(c.isspace() for c in str(root)) or '%' in str(root):
    raise SystemExit('Use a deployment directory without whitespace or percent signs.')
node = shutil.which('node')
redis = shutil.which('redis-server')
if not node or not redis:
    raise SystemExit('Install Node 22+ and redis-server first.')
user = getpass.getuser()
output = root / '.cache/systemd'
output.mkdir(parents=True, exist_ok=True)
venv = root / '.venv/bin'
services = {
    'redis': (root, f'{redis} {root}/var/redis.conf', '', ''),
    'backend': (root / 'backend', f'{venv}/gunicorn config.wsgi:application --bind 127.0.0.1:8100 --workers 1 --threads 2 --timeout 60', 'centralcrm-redis.service', ''),
    'frontend': (root / 'frontend', f'{node} node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3100', '', 'Environment=DJANGO_API_ORIGIN=http://127.0.0.1:8100\n'),
    'worker': (root / 'backend', f'{venv}/celery -A config worker --loglevel=warning --pool=solo --concurrency=1 --hostname=centralcrm@%H', 'centralcrm-redis.service', ''),
    'beat': (root / 'backend', f'{venv}/celery -A config beat --loglevel=warning --schedule={root}/var/celerybeat-schedule', 'centralcrm-redis.service', ''),
}
for name, (cwd, command, dependency, extra) in services.items():
    # Frontend receives no Django or integration secrets.
    env = '' if name in ('redis', 'frontend') else f'EnvironmentFile={root}/.env\nEnvironment=DJANGO_SETTINGS_MODULE=config.production_settings\n'
    unit = f'''[Unit]
Description=Central CRM {name}
After=network-online.target {dependency}
Wants=network-online.target
{('Requires=' + dependency) if dependency else ''}

[Service]
Type=simple
User={user}
WorkingDirectory={cwd}
Environment=PATH={Path(node).parent}:/usr/local/bin:/usr/bin:/bin
{env}{extra}ExecStart={command}
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths={root}/var{(' ' + str(root / 'frontend/.next')) if name == 'frontend' else ''}
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
'''
    (output / f'centralcrm-{name}.service').write_text(unit)
print(f'Review service files in {output}. Nothing was installed or started.')
