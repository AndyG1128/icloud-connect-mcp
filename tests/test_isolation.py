from pathlib import Path
import ast
import json
import hashlib
import tomllib
import re


ROOT=Path(__file__).resolve().parents[1]


def test_runtime_has_no_jarvis_llm_shell_or_dynamic_import_dependency():
    forbidden={'jarvis','agent','subprocess','dotenv','openai','anthropic','sqlite_utils'}
    for path in (ROOT/'src').rglob('*.py'):
        tree=ast.parse(path.read_text())
        imports=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imports += [n.name for n in node.names]
            elif isinstance(node,ast.ImportFrom) and node.level==0:imports.append(node.module or '')
            elif isinstance(node,ast.Call) and isinstance(node.func,ast.Name):assert node.func.id not in {'eval','exec','__import__'}
        assert not {x.split('.')[0] for x in imports}&forbidden
        assert '/opt/jarvis' not in path.read_text() and 'docker inspect' not in path.read_text()


def test_templates_contain_no_real_account_or_tunnel_identifiers():
    for p in (ROOT/'examples').glob('*'):
        content=p.read_text()
        assert not re.search(r'tunnel_[0-9a-f]{16,}', content) and 'sk-proj-' not in content
        if p.suffix=='.toml':tomllib.loads(content)


def test_exact_license_records_and_pinned_dependencies_present():
    rows=json.loads((ROOT/'notices/manifest.json').read_text())
    assert len(rows)>=50
    for row in rows:
        assert row['license'] and len(row['wheel_sha256'])==64
        for f in row['license_files']:
            assert hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()==f['sha256']
    licenses={r['name'].lower():r['license'] for r in rows}
    assert licenses['icalendar-searcher']=='AGPL-3.0-or-later'
    assert licenses['imapclient']=='BSD-3-Clause'
    assert 'setuptools' in licenses


def test_source_only_release_contains_no_container_recipe_or_runtime_artifacts():
    assert not (ROOT/'Dockerfile').exists() and not (ROOT/'compose.yaml').exists()
    metadata=tomllib.loads((ROOT/'pyproject.toml').read_text())
    assert metadata['project']['license']=='AGPL-3.0-or-later'
    manifest=(ROOT/'MANIFEST.in').read_text()
    for name in ('.config', '.state', '.venv', '.git'):
        assert f'prune {name}' in manifest
