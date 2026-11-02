"""Create production secrets without overwriting an existing environment file."""
import getpass
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[2]
if sys.platform != 'linux':
    raise SystemExit('Run this on the Ubuntu server.')
if (ROOT / '.env').exists():
    raise SystemExit('.env already exists. Review it manually; no files were overwritten.')
password = getpass.getpass('Password you assigned to PostgreSQL role centralcrm_app: ')
if len(password) < 16:
    raise SystemExit('Use a unique database password of at least 16 characters.')
if any(c.isspace() for c in password) or any(c in password for c in ('"', '\\', '$', "'")):
    raise SystemExit('Use letters, digits and punctuation other than whitespace, quotes, backslashes or dollar signs.')
redis_password = secrets.token_urlsafe(36)
text = (ROOT / 'deploy/ubuntu/production.env.example').read_text()
text = text.replace('replace-with-a-random-secret-of-at-least-50-characters', secrets.token_urlsafe(64))
text = text.replace('replace-with-a-unique-database-password', password)
text = text.replace('replace-with-a-random-url-safe-password', redis_password)
text = text.replace('replace-with-the-same-redis-password', redis_password)
with os.fdopen(os.open(ROOT / '.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file:
    file.write(text)
var = ROOT / 'var'
(var / 'redis').mkdir(parents=True, exist_ok=True)
os.chmod(var, 0o700)
redis_config = '\n'.join([
    'bind 127.0.0.1', 'protected-mode yes', 'port 6381',
    f'requirepass {redis_password}', f'dir {var / "redis"}',
    'appendonly yes', 'appendfsync everysec', 'daemonize no',
    'supervised no', 'logfile ""', '',
])
with os.fdopen(os.open(var / 'redis.conf', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file:
    file.write(redis_config)
print('Created private .env and var/redis.conf. No secret values were printed.')
