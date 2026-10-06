# Validation evidence and limits

The private working installation baseline is source `17d23cc`, package version
0.1.0. All 13 installed module bytes matched that commit and the tested wheel.
The public candidate changes package metadata/version and the relocatable launcher,
not mail/calendar algorithms or runtime dependency versions.

## Fresh offline candidate validation

The candidate was built and installed as a regular wheel in a newly created venv
inside a read-only, network-disabled Debian 13/Linux x86_64 container with CPython
3.12.15. HOME, temporary state and caches were new; only public candidate source
and freshly downloaded, hash-verified dependency wheels were mounted. No host
home, Jarvis source, active credentials/configuration or production state were
mounted. Source tests imported the installed package. MCP subprocess tests were
explicitly configured to import that installed package rather than the source tree.
The final report contains exact artifacts/checksums and results; prior development
ran 235 offline tests and 21 targeted permission/move tests.

Coverage includes canonical quoted folders/non-INBOX UIDs, UIDVALIDITY changes,
long MIME pagination, read-flag preservation, attachments, Unicode search framing,
SMTP ambiguity and duplicate prevention, Sent trailing-CRLF exception (only one),
COPY-before-targeted-removal, interrupted moves/expunge, invalid UID/flag identities,
profile enforcement, strong ETags, recurrence exceptions, DST and all-day boundaries.
Real stdio initialize/discovery/call tests cover 9 read tools, 16 normal full tools
and 17 opt-in expunge tools. Synthetic recurrence tests are not live recurrence tests.

## Reported live development checks

The operator reported this-chat validation of email send/reply, Sent-copy
persistence, round-trip moves, recoverable deletion by moving to Trash,
operator-enabled targeted permanent deletion, and one non-recurring event's
create/read/update/delete lifecycle. Earlier bounded read checks covered keyword
search, full content/attachment retrieval, unchanged flags and discovery that
separates VEVENT calendars from VTODO collections. No private test message IDs,
subjects, addresses, event data, collection hrefs or operation IDs are included here.
These reports apply to the working development installation, not a fresh beta
installation using another account. They are not repeatable tests run during
release preparation, which makes no live account calls.

ChatGPT chat, ThorBot, the dot, mobile and Pages connectivity were reported in
prior stages. Do not infer that every write tool and every client approval flow
was exercised on every surface. The live checks did not establish equivalent
coverage for all-day writes, recurring-event mutations, invitations, cross-calendar
moves, restart/reboot resilience or arbitrary operating systems/accounts.
