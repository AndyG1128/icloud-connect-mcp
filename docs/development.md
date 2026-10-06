# Reproducible installed-package validation

Use the [first-run instructions](../README.md#first-run-local-stdio) to build and
install the pinned public beta. Runtime, build and test dependencies have separate
hash locks for CPython 3.12/Linux x86_64. No editable install or other application's
environment is used. Native artifacts on other platforms need their own review.

## Run the same isolation pipeline as CI

Prerequisites: Git, host Python 3.12 and Docker usable by your operator account.
This pass used Ubuntu 24.04, host Python 3.12.3 and Docker 29.7.2; the connector
itself runs in the separately pinned Debian/Python userland. The pipeline is
designed for Linux x86_64. It pulls an upstream test base
and downloads dependencies during setup, so that phase needs network access.
This helper is introduced by the onboarding/CI update; run it from a checkout
that contains `scripts/offline_ci.py`, not the older pinned first-run baseline.

```sh
git rev-parse HEAD
python3 scripts/offline_ci.py --output .artifacts/offline-ci
```

Use a different output directory for every repeat; existing output is refused.
To test an older public checkout with this version of the harness, use:

```sh
python3 scripts/offline_ci.py --source-dir /path/to/public-checkout --output .artifacts/offline-other-revision
```

Only selected public source files are copied. Git metadata, host HOME, ignored
credentials, active configuration, signing keys, ledgers, dependency caches and
the Docker socket are not mounted. Setup downloads fresh wheels with
`--only-binary=:all: --require-hashes --no-cache-dir` using requirements-dev.lock.
No package credentials or secret environment variables are forwarded.

The offline phase uses the pinned upstream image
`python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d`,
with `--network none`, a read-only root, dropped capabilities and fresh writable
temporary directories. It asserts that only loopback exists and a numeric outbound
connection is unavailable. Loopback remains available for local protocol tests.
This is test infrastructure, not a released connector container recipe or image.

Inside that network-disabled environment it:

1. Installs the build lock in a fresh build venv and builds a regular wheel.
2. Installs runtime pins and the actual wheel in a separate fresh test venv,
   checks dependencies, and verifies all 13 installed Python modules byte-for-byte.
3. Installs test pins from the downloaded wheelhouse and runs:

   ```sh
   ICLOUD_MCP_TEST_INSTALLED=1 PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
     .venv/bin/python -m pytest -q -p pytest_asyncio.plugin -p no:cacheprovider \
     --junitxml=/results/tests.xml
   ```

4. Exercises the README's exact local SDK configuration and ping recipe. Tests
   also cover real stdio initialization/discovery at 9/16/17 tools, write denials,
   granular restrictions and synthetic mail/calendar behavior.

`ICLOUD_MCP_TEST_INSTALLED=1` also makes MCP subprocesses import the installed wheel.
The runner verifies module origin inside the test venv's site-packages, not `src`.
No iCloud credentials or live account calls are needed. Tests must not be pointed
at your account configuration. Do not publish the local wheelhouse or state.

Local evidence is under the chosen output directory's `results/`: sanitized JSON,
JUnit, source-file hashes, build log and summary. They record the source SHA, dirty
checkout status, harness/README hashes, module/lock hashes and actual outcomes.
A dirty checkout is explicitly distinguished from the named immutable revision.

## GitHub Actions

[The workflow](../.github/workflows/offline.yml) uses a GitHub-hosted Ubuntu 24.04
runner to execute the same pipeline. The tested Python/Debian userland is in the
container; hosted-runner behavior is verified only by an actual successful run.
It uses `contents: read`, pins actions/checkout v6 to an immutable SHA, and disables
persisted checkout credentials. There are no secrets, self-hosted runners,
deployment/repository-write steps, artifact uploads or package publication.

Results appear in the job logs and job summary on the
[workflow run page](https://github.com/AndyG1128/icloud-connect-mcp/actions/workflows/offline.yml).
The summary records the exact CI commit (`GITHUB_SHA`), including a PR merge SHA
when appropriate. Until the first approved push/run, this new workflow has no
GitHub-hosted result; local validation is reported separately in
[validation.md](validation.md).

GitHub's [workflow permission reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions)
explains the token permissions. The pinned [checkout action](https://github.com/actions/checkout/tree/d23441a48e516b6c34aea4fa41551a30e30af803)
and upstream Docker test image are fetched tools, not bundled project artifacts.

## Packaging boundaries

SOURCE_DATE_EPOCH remains fixed by release-baseline.json. The existing build helper
normalizes source tarball ordering, ownership and tar/gzip timestamps. Local wheels
and tarballs are validation artifacts only; source Git is the published format.
No script uploads, tags, pushes or publishes anything. License/source/relink and
remote-runtime caveats in [licensing.md](licensing.md) still apply.
