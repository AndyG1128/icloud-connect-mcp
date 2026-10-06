# icloud-connect-mcp

An independent community project for connecting a **user-hosted** MCP server to
that user's own personal iCloud mail and calendars. It is not an official Apple
or OpenAI integration. There is no hosted shared account, LLM, Jarvis runtime
import, database dependency, or credential discovery from another application.
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

## Quick start

The tested clean platform is Linux x86_64, Debian 13, CPython 3.12.15. The locks
select exact CPython 3.12/Linux x86_64 wheels. macOS, Windows, ARM and other Python
versions have not been validated. `fcntl` mail locking makes Windows unsupported
without code changes. Native wheel differences require a new provenance audit.

Obtain the reviewed source from the repository's exact public commit and record
that revision. Build your own package locally. The
commands below install in that source checkout's own environment, not another
application's environment. Dependencies are acquired separately from upstream:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-cache-dir --require-hashes -r requirements-build.lock
.venv/bin/python scripts/build_release.py
.venv/bin/python -m pip install --no-deps --no-cache-dir dist/icloud_connect_mcp-0.2.0b1-py3-none-any.whl
mkdir -m 700 .config .state
```

The build helper creates operator-local review packages only; it uploads nothing.
Do not commit dist/, credentials or runtime files. Do not use editable deployment.
[Source access](docs/source-access.md) identifies upstream sources and explains
why separate installation does not waive AGPL obligations for a covered remote
combination. A bundled runtime/image/network source offer is not cleared by this
source-only publication. Native/unused-resource questions remain as documented.
For a no-account initialization/discovery/ping test, use private temporary state:

```sh
.venv/bin/python scripts/protocol_check.py --config examples/probe.toml
```

This calls only `connector_ping`. It still creates a local signing key and empty
operation ledger in the probe state directory; it does not log in to iCloud.

When ready to configure your own account, run the local secure prompt:

```sh
.venv/bin/python scripts/setup_credentials.py
scripts/run-stdio.sh
```

Enter the app-specific password **only in the local hidden terminal prompt**,
never chat, shell arguments, source files, logs, or issue reports. The helper
creates operator-owned mode-0600 configuration/password files and a mode-0700
state directory. It starts no server or tunnel and refuses overwriting prior
setup. Read [credentials](docs/credentials.md) before use.

A raw stdio server is normally launched by an MCP client, not used as an
interactive chat in a terminal. stdout is protocol-only. The server exposes no
HTTP listener. See [client connection](docs/client-connection.md) for local stdio
and the verified Secure MCP Tunnel path, including account prerequisites.

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
surface. This candidate has made no live account calls. No unattended reliability,
public endpoint, directory acceptance, or outside maintenance commitment is claimed.
