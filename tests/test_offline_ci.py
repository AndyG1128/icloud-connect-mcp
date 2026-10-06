"""CI boundary checks; fake Git responses and Docker calls, no network or credentials."""
import importlib.util
import json
from pathlib import Path
import sys
import pytest


@pytest.fixture
def ci(monkeypatch, tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts/offline_ci.py'
    spec = importlib.util.spec_from_file_location('offline_ci_test_subject', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / 'checkout'
    root.mkdir()
    for name in ['README.md', 'src/icloud_mcp/example.py', '.config/config.toml', '.state/identity.key']:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic fixture only')
    monkeypatch.setattr(module, 'ROOT', root)
    sha = '1' * 40
    def fake_git(args, **kwargs):
        if args[-2:] == ['rev-parse', 'HEAD']:
            return sha + '\n'
        if args[-2:] == ['status', '--porcelain']:
            return ''
        assert 'ls-files' in args
        return b'README.md\0src/icloud_mcp/example.py\0.config/config.toml\0.state/identity.key\0'
    monkeypatch.setattr(module.subprocess, 'check_output', fake_git)
    commands = []
    monkeypatch.setattr(module, 'run', commands.append)
    output = tmp_path / 'evidence'
    monkeypatch.setattr(sys, 'argv', ['offline_ci.py', '--output', str(output)])
    return module, root, output, commands, sha


def test_snapshot_excludes_operational_files_and_test_network_is_disabled(ci):
    module, root, output, commands, sha = ci
    module.main()
    copied = json.loads((output / 'results/source-files.json').read_text())
    assert {x['path'] for x in copied} == {'README.md', 'src/icloud_mcp/example.py'}
    assert not (output / 'source/.config').exists() and not (output / 'source/.state').exists()
    assert len(commands) == 3 and commands[0][:2] == ['docker', 'pull']
    offline = commands[-1]
    assert offline[offline.index('--network') + 1] == 'none'
    assert '--read-only' in offline and '--cap-drop' in offline
    assert 'VALIDATION_SOURCE_REVISION=' + sha in offline
    assert not any('docker.sock' in arg or 'OPENAI_API_KEY=' in arg for arg in offline)


def test_revision_mismatch_is_rejected_before_setup(ci, monkeypatch):
    module, root, output, commands, sha = ci
    monkeypatch.setattr(sys, 'argv', ['offline_ci.py', '--output', str(output), '--revision', '2' * 40])
    with pytest.raises(SystemExit):
        module.main()
    assert not output.exists() and commands == []


def test_existing_output_is_rejected_without_dependency_reuse(ci):
    module, root, output, commands, sha = ci
    output.mkdir()
    with pytest.raises(SystemExit):
        module.main()
    assert commands == []


def test_symlink_cannot_expose_operational_files(ci):
    module, root, output, commands, sha = ci
    path = root / 'src/icloud_mcp/example.py'
    path.unlink()
    path.symlink_to(root / '.config/config.toml')
    with pytest.raises(ValueError, match='unsafe path'):
        module.main()
    assert commands == []
