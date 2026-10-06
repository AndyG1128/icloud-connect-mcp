# Validation evidence and limits

## Public source and tests rerun for onboarding/CI

The immutable public baseline is
[`024e46bec2280da78fa8a042d1305ddbc0fccea9`](https://github.com/AndyG1128/icloud-connect-mcp/commit/024e46bec2280da78fa8a042d1305ddbc0fccea9),
package **0.2.0b1**. This pass changes documentation/CI and packaging of examples,
not connector algorithms, dependencies or safety defaults. All 13 connector
modules and all three dependency locks are unchanged from that public revision.

[Sanitized machine-readable evidence](offline-validation.json) records the actual
local commands, Python/platform, public revision, installed-module/lock hashes,
MCP results and offline outcomes for this pass. It preserves the distinction between
the clean public baseline and the documentation/CI working copy tested before
publication, and records the subsequent GitHub-hosted result separately. These
checks do not establish that an independent user completed beta acceptance.

| Local run | Source | Result |
|---|---|---|
| Clean published baseline | `024e46b`, unmodified | **235 passed**, 0 failures/errors/skips |
| Proposed onboarding/CI checkout | Same connector modules/locks; documentation/CI changes | **239 passed**, 0 failures/errors/skips |

The four additional tests check CI snapshot isolation, source-SHA validation,
reused-output refusal and symlink rejection. Both runs passed the README SDK
recipe and account-free disconnect/restart/reconnect. Workflow YAML checks and
actionlint passed; these static checks do not replace a GitHub-hosted execution.

The tested userland is CPython **3.12.15**, Linux **x86_64**, Debian **13.7**, using
an immutable upstream test-base digest. Fresh dependencies are downloaded and
hash-checked during setup. The build and installed-wheel tests then run inside a
read-only, network-disabled container with fresh build/test venvs, HOME and state,
with only public source and downloaded wheels mounted. Git metadata, host home,
credentials, active configuration, production state and Docker socket are excluded.
Only loopback is available; the runner asserts external connectivity is blocked.

The complete fixture suite runs against installed site-packages, including MCP
subprocesses; installed origin and all module bytes are verified. It exercises
real initialize/discovery/ping, **9 read-only / 16 full-access / 17 opt-in expunge**
and permission enforcement. It includes quoted/non-INBOX folders, stale UIDVALIDITY,
long MIME pagination, flag preservation, attachment bytes, Unicode search, SMTP/Sent
ambiguity and recovery, verified UIDPLUS moves, targeted expunge progress, ETags,
recurrence exceptions, DST and all-day boundaries. These are synthetic account tests.

The README's exact account-free SDK/JSON configuration is executed independently
of the fixture suite, including disconnect/restart/reconnect with the same local
signing key. Its expected ping has `account_access: false`. This does not test
account login, remote ChatGPT connectivity, tunnel crash/reboot recovery or writes
through a real client approval flow.

[Reproduction instructions](development.md) give the same pipeline and commands.
[The hosted workflow](../.github/workflows/offline.yml) passed on **2026-10-06** for
published commit
[`79c9ad5e4c3aff569aea481451777a4e0aa61912`](https://github.com/AndyG1128/icloud-connect-mcp/commit/79c9ad5e4c3aff569aea481451777a4e0aa61912).
[The successful run and job summary](https://github.com/AndyG1128/icloud-connect-mcp/actions/runs/37471257283)
record **239 passed**, 0 failures/errors/skips, installed-wheel validation, permission
enforcement and **9 / 16 / 17** tool discovery. The network-disabled tests used
CPython **3.12.15** on Linux x86_64 with Debian **13.7** userland. The README SDK
recipe and account-free disconnect/restart/reconnect also passed. No live account
calls, package uploads or image uploads were performed. This result applies to
the linked commit; later revisions require their own successful run.

## Reported live development checks

The operator reported this-chat validation of email send/reply, Sent-copy
persistence, round-trip moves, recoverable deletion by moving to Trash,
operator-enabled targeted permanent deletion, and one non-recurring event's
create/read/update/delete lifecycle. Earlier bounded read checks covered keyword
search, full content/attachment retrieval, unchanged flags and discovery that
separates VEVENT calendars from VTODO collections. No private test message IDs,
subjects, addresses, event data, collection hrefs or operation IDs are included here.
These reports apply to the working development installation, not a fresh beta
installation using another account. They are historical reports, not live tests rerun in this documentation/CI pass.
This pass uses no live credentials or mail/calendar data.

ChatGPT chats, mobile chats and Pages connectivity were reported in
prior stages. Do not infer that every write tool and every client approval flow
was exercised on every surface. The live checks did not establish equivalent
coverage for all-day writes, recurring-event mutations, invitations, cross-calendar
moves, restart/reboot resilience or arbitrary operating systems/accounts.
