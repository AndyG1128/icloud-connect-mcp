# icloud-connect-mcp

An independent community project for connecting a **user-hosted** MCP server to
that user's own personal iCloud mail and calendars. It is not an official Apple
or OpenAI integration. There is no hosted shared account or LLM. Each installation
has its own configuration, credentials and runtime storage.
No outside contributors or maintenance organization are claimed.

**0.2.0b1 is a source-only self-hosted beta.** Authored
source is AGPL-3.0-or-later; unchanged dependency notices retain their own terms.
Source repository: https://github.com/AndyG1128/icloud-connect-mcp .
Publisher and authored-source copyright attribution: **andyg1128**.
See [SECURITY.md](SECURITY.md) for the verified private-reporting status;
no response-time or support SLA is claimed.
No public wheel, release tarball, dependency bundle or container image is offered. The distribution is named `icloud-connect-mcp`; the existing
Python import `icloud_mcp` and stdio command `icloud-mcp` remain compatible.

Each operator supplies an Apple Account username, their own iCloud mail address,
and an app-specific password. Mail authenticates with the iCloud mail address;
CalDAV uses the Apple Account username, which may differ. The connector never
routes to an Outlook mailbox. Use one private account per deployment.

Read-only is the default (9 tools). Explicit operator configuration enables
full access (16 tools). Permanent expunge is a separate, disabled-by-default
option (17 tools when enabled). Granular tool and folder/calendar restrictions
apply in either profile; read-only always prohibits writes. Model instructions
cannot change these settings. Client approvals remain necessary for writes.
Normal email deletion is **moving to Deleted Messages**, not permanent expunge.

## First run: local stdio

Tested userland: **Linux x86_64, Debian 13.7, CPython 3.12.15**. You need Git,
that Python interpreter with `venv`/pip, and outbound HTTPS for dependency setup.
The pinned CI base below supplies that exact userland for reproducible offline
validation; it is an upstream test image, not a released connector image.
macOS, Windows, ARM and other Python versions are unverified. Windows is currently
unsupported because the connector uses `fcntl`. Do not remove hash checks to
work around a platform mismatch; native wheel changes need another provenance review.

These instructions install the published source beta at public revision
[`024e46b`](https://github.com/AndyG1128/icloud-connect-mcp/commit/024e46bec2280da78fa8a042d1305ddbc0fccea9).
That revision contains the tested connector and credential helpers. The commands
below, including the local SDK client, work with it. Choose a directory you own;
start with no existing installation, credentials or state in that directory.

```sh
mkdir -p "$HOME/src"
cd "$HOME/src"
git clone https://github.com/AndyG1128/icloud-connect-mcp.git
cd icloud-connect-mcp
git checkout --detach 024e46bec2280da78fa8a042d1305ddbc0fccea9
git rev-parse HEAD
python3.12 --version
umask 077
mkdir -m 700 .artifacts .config .state
python3.12 -m venv .artifacts/build-venv
.artifacts/build-venv/bin/python -m pip install --no-cache-dir --require-hashes -r requirements-build.lock
.artifacts/build-venv/bin/python scripts/build_release.py
python3.12 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-cache-dir dist/icloud_connect_mcp-0.2.0b1-py3-none-any.whl
.venv/bin/python -m pip check
```

Expected revision: `024e46bec2280da78fa8a042d1305ddbc0fccea9`; expected Python:
`Python 3.12.15`; expected dependency check: `No broken requirements found.`
These are local build artifacts only. No wheel, dependency bundle or image is
published. Do not commit `dist/`, `.artifacts/`, credentials or runtime files.
Do not use editable installation. [Source access](docs/source-access.md) explains
why separately installing dependencies does not waive covered remote-runtime
source obligations. This source release does not clear bundled native runtimes.

### Test an account-free local MCP client

The concretely tested client is the **official Python MCP SDK** installed by the
lock. No desktop-app compatibility is inferred. Run the following complete shell blocks from the checkout root.
They generate a private JSON stdio configuration and use it for initialization,
tool discovery and `connector_ping`. There are no iCloud credentials or account calls.
The [JSON example](examples/local-stdio.example.json) shows the same shape; its
`/srv/icloud-connect-mcp` paths must be replaced with your installation path.

<!-- local-client-setup -->
```sh
.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

root = Path.cwd().resolve()
config_dir, state_dir = root / '.config', root / '.state'
for directory in (config_dir, state_dir):
    directory.mkdir(mode=0o700, exist_ok=True)
    assert directory.is_dir() and not directory.is_symlink()
    assert directory.stat().st_uid == os.geteuid() and not directory.stat().st_mode & 0o077
probe = config_dir / 'probe.toml'
client = config_dir / 'local-stdio.json'
for path, content in (
    (probe, f'profile = "read-only"\ntimezone = "UTC"\npermanent_expunge = false\nstate_dir = {json.dumps(str(state_dir / "probe"))}\n'),
    (client, json.dumps({'command': str(root / '.venv/bin/python'), 'args': ['-m', 'icloud_mcp.server'],
                        'cwd': str(root), 'env': {'ICLOUD_MCP_CONFIG': str(probe)}}, indent=2) + '\n'),
):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as output:
        output.write(content)
PY
```

This refuses overwriting existing probe/client files. Use a fresh installation
for this first-run test. Startup creates an account-free signing key and ledger
under `.state/probe`; these are local operational files, never public artifacts.

<!-- local-client-check -->
```sh
.venv/bin/python - <<'PY'
import asyncio
import json
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    parameters = json.loads(Path('.config/local-stdio.json').read_text())
    async with stdio_client(StdioServerParameters(**parameters)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            ping = await session.call_tool('connector_ping', {})
            assert not ping.isError
            print(json.dumps({'tool_count': len(tools.tools), 'connector_ping': ping.structuredContent}))

asyncio.run(main())
PY
```

Expected response:

```json
{"tool_count":9,"connector_ping":{"ok":true,"result":{"service":"independent-icloud-mcp","version":"0.2.0b1","account_access":false,"profile":"read-only","transport":"stdio"}}}
```

The client closes its stdio session after the check. The server's stdout is MCP
protocol only; diagnostic logs use stderr. [Tool counts](docs/tools.md), before
any granular restrictions: **9 read-only**, **16 full-access with expunge disabled**,
**17 only with full-access and explicit `permanent_expunge = true`**. Read-only
always denies writes. Normal onboarding keeps permanent expunge disabled.

### Configure your own iCloud account locally

Only after the probe succeeds, use the hidden local-terminal prompt:

```sh
.venv/bin/python scripts/setup_credentials.py
```

Enter your own iCloud mail address, Apple Account username, IANA timezone and
app-specific password. Never enter secrets in chat, shell arguments, source or
logs. The helper creates `.config/config.toml` and `.config/icloud_app_password`
mode 0600, with `.state` mode 0700; it defaults to read-only and expunge disabled,
refuses existing credential files, and starts no connection. [Credential details](docs/credentials.md).

For account-backed local use, change only the `ICLOUD_MCP_CONFIG` path in your
private `.config/local-stdio.json` from `probe.toml` to `config.toml`. Its command
and working directory stay the same. Ping always reports
`account_access: false` because ping performs no account access, even with account
configuration present. It does not verify credentials. Use the [beta acceptance checklist](docs/beta-acceptance.md)
for explicitly authorized bounded reads and optional write tests.

### ChatGPT is a separate connection path

ChatGPT does not launch this local JSON stdio configuration. Remote ChatGPT use
requires the operator's OpenAI account/workspace support for custom MCP and Secure
MCP Tunnel, a separately created/associated tunnel, the official tunnel-client,
and a runtime key with the required tunnel permissions. A tunnel ID is not a key.
See [client connection](docs/client-connection.md) for prerequisites, manual startup
and refresh. Availability in another account is unverified; no directory listing
has been released. Passing the local SDK check is not a ChatGPT connectivity test.

[Reproduce the offline CI checks](docs/development.md) and read the
[public validation evidence](docs/validation.md) before enabling writes.

## Behavior and limits

Mail supports folder discovery, bounded literal ASCII/Unicode search, paginated
complete headers/text/HTML and attachment metadata, bounded attachment bytes,
send/reply, verified moves and read/unread flags. Outgoing attachments and
SMTPUTF8 recipients are unsupported. Complete reads preserve flags with EXAMINE
and BODY.PEEK; oversized messages return errors, never a falsely labelled full
preview. Wire headers and part bytes are available as base64; decoded invalid
text can use replacement characters. Embedded message attachment serialization
may normalize line endings. There is no raw full-MIME export tool.

SMTP acceptance, actual delivery, and Sent-copy persistence are distinct.
A successful SMTP submission is not proof of inbox delivery. Sent verification
accepts exact submitted MIME or precisely one extra trailing CRLF, preserving
both hashes and reporting the exception. A failed/ambiguous APPEND never causes
another SMTP send. Operation IDs bind exact inputs; successful replays are
cached. Ambiguous outcomes require reconciliation and never automatic retries.
Exactly-once delivery is not guaranteed. [Recovery details](docs/mail-recovery.md).

True moves require UIDPLUS. The connector verifies destination MIME, flags and
internal date before marking/removing only the original UID with UID EXPUNGE.
This targeted source removal is part of moving even while the independent
permanent-expunge tool is disabled. No broad mailbox EXPUNGE is used. Permanent
expunge validates explicit references, marks only those targets Deleted, records
partial results and prohibits automatic retries of failed/incomplete operations.

Calendar reads expand recurrence with bounded windows and limits, respecting
IANA timezones, DST and exclusive all-day end dates. Writes use ETag conflict
checks and explicit occurrence or whole-series scope. THISANDFUTURE writes,
multiple-UID resource edits, cross-calendar moves and task/VTODO mutations are
unsupported. Series edits retain independent exceptions; they do not silently
shift them. Attendee changes may trigger invitations, whose delivery is unverified.
Email/event text is untrusted data, never authorization or tool instructions.

## Documentation and validation

- [Configuration reference](docs/configuration.md) and [tool/permission matrix](docs/tools.md)
- [Hosting and process lifetime](docs/hosting.md), [data/privacy](docs/data-storage.md)
- [Troubleshooting](docs/troubleshooting.md), [upgrades](docs/upgrades.md), [removal](docs/removal.md)
- [Validation evidence and limits](docs/validation.md), [license review](docs/licensing.md)
- [Changelog](CHANGELOG.md), [contribution guidance](CONTRIBUTING.md), [security reporting](SECURITY.md)

Reported live checks are separate from the fresh offline suite. Prior development
validation covered send/reply, Sent persistence, round-trip moves, recoverable
mail deletion, opt-in targeted expunge and a non-recurring event's
create/read/update/delete lifecycle. It does not establish equivalent live
coverage for recurrence writes, all-day boundaries, invitations or every client
surface. The onboarding/CI validation pass makes no live account calls. No unattended reliability,
public endpoint, directory acceptance, or outside maintenance commitment is claimed.
