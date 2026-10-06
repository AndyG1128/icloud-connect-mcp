"""Local/hosted CI only: fresh dependency download, then network-isolated tests.

No account configuration, host home, runtime state or Docker socket is mounted
into the containers. Results/dependencies remain local; nothing is uploaded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

IMAGE = 'python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d'
ROOT = Path(__file__).resolve().parents[1]


def run(args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, help='New local evidence directory; never uploaded.')
    parser.add_argument('--revision', help='Public source/CI commit SHA; defaults to checkout HEAD.')
    parser.add_argument('--source-dir', type=Path, default=ROOT, help='Public checkout to validate; defaults to this checkout.')
    args = parser.parse_args()
    root = args.source_dir.resolve()
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    revision = args.revision or head
    dirty = bool(subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True).strip())
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        parser.error('Expected a full source revision SHA.')
    if revision != head:
        parser.error('Revision does not match the checkout HEAD; refusing mislabeled evidence.')
    output = Path(args.output).resolve()
    if output.exists():
        parser.error('Use a new output directory to avoid reusing dependencies or test evidence.')
    output.mkdir(parents=True, mode=0o700)
    source, wheels, results = (output / n for n in ('source', 'wheelhouse', 'results'))
    for directory in (source, wheels, results):
        directory.mkdir(mode=0o700)
    # Copy public source paths only. Ignored local environments/credentials/state
    # and Git metadata are excluded even when this runs in a configured checkout.
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard', '-z']).decode().rstrip('\0').split('\0')
    allowed_dirs = {'.github', 'src', 'tests', 'scripts', 'docs', 'examples', 'notices'}
    allowed_files = {'README.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md', 'LICENSE', 'NOTICE.md',
                     'THIRD_PARTY_NOTICES.md', 'MANIFEST.in', 'pyproject.toml', '.gitignore',
                     'requirements.lock', 'requirements-build.lock', 'requirements-dev.lock'}
    manifest = []
    for name in sorted(names):
        parts = Path(name).parts
        if not parts or (parts[0] not in allowed_dirs and name not in allowed_files):
            continue
        path = root / name
        if any((root / Path(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)) or not path.is_file():
            raise ValueError('Source snapshot contains an unsafe path.')
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        manifest.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (results / 'source-files.json').write_text(json.dumps(manifest, indent=2) + '\n')
    common = ['docker', 'run', '--rm', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
              '--pids-limit', '128', '--memory', '2g', '--cpus', '2', '--user', f'{os.getuid()}:{os.getgid()}',
              '--tmpfs', f'/tmp:uid={os.getuid()},gid={os.getgid()},mode=0700,exec,size=1g',
              '--mount', f'type=bind,src={source},dst=/source,readonly',
              '--mount', f'type=bind,src={ROOT / "scripts/offline_validate.py"},dst=/validator.py,readonly',
              '--mount', f'type=bind,src={ROOT / "README.md"},dst=/onboarding.md,readonly',
              '-e', 'HOME=/tmp/home', '-e', 'XDG_CACHE_HOME=/tmp/cache', '-e', 'PIP_NO_CACHE_DIR=1',
              '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'PYTHONPATH=']
    print('Setup: pulling the pinned test base and freshly downloading hash-locked wheels.', flush=True)
    run(['docker', 'pull', IMAGE])
    run(common + ['--mount', f'type=bind,src={wheels},dst=/wheels', IMAGE,
                 'python', '-m', 'pip', 'download', '--quiet', '--no-cache-dir', '--only-binary=:all:', '--require-hashes',
                 '-r', '/source/requirements-dev.lock', '--dest', '/wheels'])
    print('Offline phase: --network none; no host configuration, state, home or credentials.', flush=True)
    run(common + ['--network', 'none', '--mount', f'type=bind,src={wheels},dst=/wheels,readonly',
                 '--mount', f'type=bind,src={results},dst=/results', '-e', f'VALIDATION_SOURCE_REVISION={revision}',
                 '-e', f'VALIDATION_SOURCE_HAS_CHANGES={int(dirty)}', IMAGE, 'python', '/validator.py'])


if __name__ == '__main__':
    main()
