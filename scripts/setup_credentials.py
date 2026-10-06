"""Local, TTY-only setup for this project's dedicated read-only credentials.

Makes no network requests. Never inspects another application's configuration.
Existing credential/config files are never overwritten.
"""
import getpass
import json
import os
from pathlib import Path
import stat
import sys
import warnings

from icloud_mcp.config import Config

ROOT = Path(__file__).resolve().parents[1]


def private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('Private directory must be operator-owned, mode 0700, and not a symlink.')


def create_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def save_setup(root, account, username, timezone, password):
    config_dir, state_dir = root / '.config', root / '.state'
    private_directory(config_dir)
    private_directory(state_dir)
    password_path, config_path = config_dir / 'icloud_app_password', config_dir / 'config.toml'
    if any(os.path.lexists(p) for p in (password_path, config_path)):
        raise ValueError('Setup already exists; inspect it locally rather than overwrite credentials.')
    if not password or len(password.encode()) > 1024 or any(c in password for c in '\r\n\x00'):
        raise ValueError('Invalid app-password input.')
    if not username or any(c in username for c in '\r\n\x00'):
        raise ValueError('Invalid authentication username.')
    options = dict(profile='read-only', account_email=account, username=username,
                   timezone=timezone, password_file=str(password_path), state_dir=str(state_dir),
                   permanent_expunge=False, timeout_seconds=30, max_results=100,
                   max_date_days=31, max_calendar_resources=200)
    Config(**options)  # Validate before saving a credential, without reading one.
    body = '# Independent host stdio configuration. Operator-only; no writes.\n'
    for key, value in options.items():
        body += f'{key} = {json.dumps(value, ensure_ascii=False)}\n'
    create_private(password_path, password + '\n')
    create_private(config_path, body)
    return config_path


def main():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print('Run this prompt in a local interactive terminal, never chat or redirected input.', file=sys.stderr)
        return 2
    print('Independent iCloud MCP: dedicated app-password setup; no network access.', file=sys.stderr)
    if input('Confirm approved read-only credential setup by typing READ-ONLY: ').strip() != 'READ-ONLY':
        return 2
    account = input('Personal iCloud mail address (configured account identity): ').strip()
    username = input('iCloud authentication username / Apple Account address: ').strip()
    zone = input('Default IANA timezone [UTC] (e.g. America/Chicago): ').strip() or 'UTC'
    warnings.simplefilter('error', getpass.GetPassWarning)
    password = getpass.getpass('NEW dedicated iCloud MCP app-specific password (hidden): ')
    try:
        path = save_setup(ROOT, account, username, zone, password)
    except Exception:
        print('SETUP_FAILED: check private directory permissions, prior setup and account/timezone inputs locally. No values logged.', file=sys.stderr)
        return 1
    finally:
        password = None
    print(f'Prepared {path}; credential mode 0600. No server or tunnel started.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
