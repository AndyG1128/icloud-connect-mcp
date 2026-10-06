"""Installed-wheel verification inside the network-disabled CI test container."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

SOURCE, RESULTS = Path('/tmp/source'), Path('/results')


def command(args, env, cwd=SOURCE, log=None):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    if log is None:
        subprocess.run(list(map(str, args)), env=env, cwd=cwd, check=True)
    else:
        with log.open('w') as output:
            result = subprocess.run(list(map(str, args)), env=env, cwd=cwd, stdout=output, stderr=subprocess.STDOUT)
        if result.returncode:
            print(log.read_text()[-4000:], flush=True)
            raise subprocess.CalledProcessError(result.returncode, args)


def main():
    # Docker --network none leaves only loopback. Verify, then make a numeric
    # outbound connection assertion independent of DNS or iCloud endpoints.
    assert set(os.listdir('/sys/class/net')) == {'lo'}
    try:
        with socket.create_connection(('192.0.2.1', 443), timeout=1):
            raise AssertionError('Outbound network unexpectedly available.')
    except OSError:
        pass
    shutil.copytree('/source', SOURCE)
    Path('/tmp/home').mkdir(exist_ok=True)
    env = dict(os.environ, HOME='/tmp/home', XDG_CACHE_HOME='/tmp/cache', PYTHONPATH='',
               PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', ICLOUD_MCP_TEST_INSTALLED='1')
    (SOURCE / '.artifacts').mkdir(mode=0o700)
    builder, tester = SOURCE / '.artifacts/build-venv', SOURCE / '.venv'
    for venv in (builder, tester):
        command([sys.executable, '-m', 'venv', venv], env)
    build_python, test_python = builder / 'bin/python', tester / 'bin/python'
    pip_options = ['-m', 'pip', 'install', '--quiet', '--no-index', '--no-cache-dir', '--require-hashes', '--find-links=/wheels']
    command([build_python, *pip_options, '-r', 'requirements-build.lock'], env)
    command([build_python, 'scripts/build_release.py'], env, log=RESULTS / 'build.log')
    wheels = list((SOURCE / 'dist').glob('*.whl'))
    assert len(wheels) == 1
    command([test_python, *pip_options, '-r', 'requirements.lock'], env)
    command([test_python, '-m', 'pip', 'install', '--quiet', '--no-index', '--no-cache-dir', '--no-deps', wheels[0]], env)
    command([test_python, '-m', 'pip', 'check'], env)
    metadata = tomllib.loads((SOURCE / 'pyproject.toml').read_text())
    check = '''import importlib.metadata,json,sysconfig,pathlib,icloud_mcp
p=pathlib.Path(icloud_mcp.__file__).resolve()
assert p.is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
print(json.dumps({'module_origin':str(p),'package_version':importlib.metadata.version('icloud-connect-mcp')}))'''
    origin = json.loads(subprocess.check_output([str(test_python), '-c', check], cwd=SOURCE, env=env, text=True))
    assert origin['package_version'] == metadata['project']['version']
    installed = Path(origin['module_origin']).parent
    modules = list((SOURCE / 'src/icloud_mcp').glob('*.py'))
    for path in modules:
        assert path.read_bytes() == (installed / path.name).read_bytes()
    command([test_python, *pip_options, '-r', 'requirements-dev.lock'], env)
    command([test_python, '-m', 'pytest', '-q', '-p', 'pytest_asyncio.plugin', '-p', 'no:cacheprovider',
             '--junitxml=/results/tests.xml'], env)
    suite = list(ET.parse(RESULTS / 'tests.xml').getroot().iter('testsuite'))
    counts = {key: sum(int(s.attrib.get(key, 0)) for s in suite) for key in ('tests', 'failures', 'errors', 'skipped')}
    assert counts['failures'] == counts['errors'] == counts['skipped'] == 0
    protocol_cases = [c.attrib['name'] for s in suite for c in s.findall('testcase')
                      if c.attrib['name'].startswith('test_real_mcp_stdio_profiles')]
    assert len(protocol_cases) == 3
    (SOURCE / '.config').mkdir(mode=0o700)
    (SOURCE / '.state').mkdir(mode=0o700)
    readme = Path('/onboarding.md').read_text()
    def recipe(name):
        return readme.split('<!-- ' + name + ' -->', 1)[1].split(".venv/bin/python - <<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
    command([test_python, '-c', recipe('local-client-setup')], env)
    example = SOURCE / 'examples/local-stdio.example.json'
    if example.exists():
        generated = json.loads((SOURCE / '.config/local-stdio.json').read_text())
        template = json.loads(example.read_text().replace('/srv/icloud-connect-mcp', str(SOURCE)))
        assert generated == template
    # Exercise precisely the documented SDK client and generated JSON config.
    client_output = subprocess.check_output([str(test_python), '-c', recipe('local-client-check')],
                                           cwd=SOURCE, env=env, text=True)
    client = json.loads(client_output)
    assert client['tool_count'] == 9 and client['connector_ping']['result']['account_access'] is False
    key = SOURCE / '.state/probe/identity.key'
    key_before = key.read_bytes()
    reconnected = json.loads(subprocess.check_output([str(test_python), '-c', recipe('local-client-check')],
                                                     cwd=SOURCE, env=env, text=True))
    assert reconnected == client and key.read_bytes() == key_before
    report = {'source_revision': os.environ['VALIDATION_SOURCE_REVISION'],
              'source_checkout_has_changes': bool(int(os.environ['VALIDATION_SOURCE_HAS_CHANGES'])),
              'validation_harness_sha256': hashlib.sha256(Path('/validator.py').read_bytes()).hexdigest(),
              'onboarding_readme_sha256': hashlib.sha256(Path('/onboarding.md').read_bytes()).hexdigest(),
              'python': platform.python_version(), 'platform': platform.platform(),
              'os_release': Path('/etc/os-release').read_text(), 'network': 'none (loopback only; outbound assertion passed)',
              'build_environment': str(builder), 'test_environment': str(tester), **origin,
              'installed_modules_byte_verified': len(modules), 'tests': counts,
              'runtime_module_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(modules)},
              'lock_sha256': {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
                              for name in ('requirements.lock', 'requirements-build.lock', 'requirements-dev.lock')},
              'local_client': client, 'profile_discovery_counts': [9, 16, 17],
              'account_free_client_disconnect_restart_reconnect': 'passed; signing key preserved',
              'profile_protocol_test_cases': protocol_cases,
              'permission_tests': 'tests/test_permissions.py and tests/test_protocol.py passed',
              'wheel_sha256': hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
              'credentials_or_live_account_calls': False}
    (RESULTS / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    summary = '# Offline installed-package validation\n\n'
    summary += f"Source revision: `{report['source_revision']}`\n\n"
    summary += f"Python {report['python']}; {report['platform']}.\n\n"
    summary += f"Tests: **{counts['tests']} passed**, no failures/errors/skips.\n\n"
    summary += 'MCP discovery: 9 read-only / 16 full-access / 17 explicit expunge opt-in; permission tests passed.\n\n'
    summary += 'Network disabled; no credentials or live account calls. Installed module bytes verified.\n\n'
    summary += '```json\n' + json.dumps(report, indent=2) + '\n```\n'
    (RESULTS / 'summary.md').write_text(summary)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
