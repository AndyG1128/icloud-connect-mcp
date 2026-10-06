"""Operator-run secure local storage for a separately approved tunnel key.

No network requests, key creation, account lookups or tunnel startup. Refuses
existing files. This helper is optional: run_tunnel also supports explicit env.
"""
import getpass
import os
from pathlib import Path
import sys
import warnings
from run_tunnel import validate_key
from setup_credentials import create_private, private_directory


def save_key(root, key):
    value = validate_key(key)
    directory = Path(root) / '.config'
    private_directory(directory)
    path = directory / 'tunnel_runtime_key'
    create_private(path, value + '\n')
    return path


def main():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print('Use a private local terminal; never enter a key through chat or redirected input.', file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    path = root / '.config/tunnel_runtime_key'
    if os.path.lexists(path):
        print('A runtime-key file already exists; it will not be overwritten.', file=sys.stderr)
        return 1
    print(f'Optional approved credential storage: {path} (0600, ignored by Git).', file=sys.stderr)
    if input('Confirm saving a tunnel key here by typing SAVE: ').strip() != 'SAVE':
        return 2
    warnings.simplefilter('error', getpass.GetPassWarning)
    key = getpass.getpass('Existing or dedicated tunnel runtime key (hidden): ')
    try:
        save_key(root, key)
    except Exception:
        print('KEY_SETUP_FAILED: check permissions and prior setup locally; values suppressed.', file=sys.stderr)
        return 1
    finally:
        key = None
    print('Runtime key saved privately. No network requests or tunnel started.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
