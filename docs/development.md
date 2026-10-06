# Rebuilding and testing the reviewed package

The exact build backend is locked in requirements-build.lock; the complete test
set is in requirements-dev.lock. They select specific audited wheel hashes for
CPython 3.12/Linux x86_64. For another platform, resolve and audit a new lock instead
of removing hash verification. No existing application's environment is used.

Create a fresh venv, empty HOME/state/cache directories and freshly retrieve the
locked wheels. Install with --require-hashes and --no-cache-dir. Build with:

```sh
.venv/bin/python scripts/build_release.py
.venv/bin/python -m pip install --no-deps --force-reinstall dist/icloud_connect_mcp-0.2.0b1-py3-none-any.whl
ICLOUD_MCP_TEST_INSTALLED=1 PYTHONPATH= .venv/bin/python -m pytest -q
```

The installed-test mode makes MCP subprocesses use the installed package as well
as the fixture-backed tests. Verify `icloud_mcp.__file__` is in that venv's
site-packages, not src. For an isolated repeat, use a network-disabled container
with only the sanitized public source and fresh wheels mounted, a new /tmp venv
and HOME, and no account configuration. The release report records that actual
procedure, base-image digest and installed origin.

SOURCE_DATE_EPOCH is fixed by release-baseline.json. The build helper normalizes
source tarball ordering, ownership, modes and tar/gzip timestamps without changing
file contents. Compare wheel and tarball hashes from two independent clean builds;
the release report records the results for the reviewed platform and backend.
The review directory's private evidence, wheelhouse and dependency source archives
are not part of the public Git tree. No build script uploads, tags or publishes. Wheel/tar outputs are local review
artifacts; the selected public format is source Git only.
