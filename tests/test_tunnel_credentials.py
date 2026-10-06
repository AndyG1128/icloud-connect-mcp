"""Synthetic runtime-key sources. No provider requests or real credentials."""
from argparse import Namespace
import importlib.util
import os
from pathlib import Path
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
KEY = 'synthetic-runtime-key-value'


def script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_private_file_works_without_terminal(tmp_path, monkeypatch):
    s = script('run_tunnel')
    path = tmp_path / 'key'
    path.write_text(KEY + '\n'); path.chmod(0o600)
    monkeypatch.setattr(s.getpass, 'getpass', lambda *_: pytest.fail('Must not prompt for an explicitly configured key.'))
    assert s.runtime_key(Namespace(key_file=str(path), key_env=None)) == KEY


def test_maximum_key_with_storage_newline(tmp_path):
    s = script('run_tunnel')
    path = tmp_path / 'key'
    path.write_text('x' * 4096 + '\n'); path.chmod(0o600)
    assert s.read_key_file(path) == 'x' * 4096


@pytest.mark.parametrize('kind', ['public', 'symlink', 'hardlink', 'large', 'fifo'])
def test_unsafe_files_rejected(tmp_path, kind):
    s = script('run_tunnel'); path = tmp_path / 'key'
    if kind == 'fifo':
        os.mkfifo(path, 0o600)
    else:
        path.write_text(KEY + '\n'); path.chmod(0o600)
        if kind == 'public': path.chmod(0o644)
        elif kind == 'symlink':
            link = tmp_path / 'link'; link.symlink_to(path); path = link
        elif kind == 'hardlink': os.link(path, tmp_path / 'other')
        elif kind == 'large': path.write_text('x' * 4097)
    with pytest.raises((OSError, ValueError)):
        s.read_key_file(path)


def test_environment_is_explicit_and_never_inherited_automatically(monkeypatch):
    s = script('run_tunnel')
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    monkeypatch.setattr(s.sys.stdin, 'isatty', lambda: False)
    with pytest.raises(ValueError):
        s.runtime_key(Namespace(key_file=None, key_env=None))
    assert s.runtime_key(Namespace(key_file=None, key_env='OPENAI_API_KEY')) == KEY
    with pytest.raises(ValueError):
        s.runtime_key(Namespace(key_file=None, key_env='MISSING_KEY'))


@pytest.mark.parametrize('key', ['', 'synthetic\nsecret', 'synthetic secret', 'x' * 4097, '\x00synthetic', 'clé'])
def test_bad_key_errors_never_expose_value(key):
    with pytest.raises(ValueError) as error:
        script('run_tunnel').validate_key(key)
    assert str(error.value) == 'Invalid runtime key; value suppressed.'


def test_optional_setup_private_and_no_overwrite(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    s = script('setup_tunnel_key')
    path = s.save_key(tmp_path, KEY)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(FileExistsError):
        s.save_key(tmp_path, 'different-synthetic-key')
    assert path.read_text().strip() == KEY
