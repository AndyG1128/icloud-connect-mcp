# Independent beta acceptance checklist

For a new operator following only the public instructions. **No independent tester
has completed this checklist as part of the onboarding/CI pass.** Use your own
account, host and credentials; keep observations and identifiers private. Keep
`permanent_expunge = false` throughout. Each write needs deliberate operator/client
approval for its exact targets; the server profile does not replace client approval.
Tool counts below assume default tool permissions; optional granular permissions
can reduce them.

1. **Install and record the version.** Follow the README clone/checkout/venv/build
   sequence. Record `git rev-parse HEAD`, Python/platform and installed distribution
   version. Expect a regular installed wheel, successful `pip check`, no live calls.
2. **Account-free discovery.** Run the documented local Python MCP SDK recipe.
   Expect initialization, 9 tools and the documented ping (`account_access: false`).
   Close the client, rerun the check and expect the same result. This verifies that
   local session only; a remote ChatGPT connection needs separate tunnel setup.
3. **Configure read-only credentials locally.** Use the hidden setup prompt and
   point the local client at `.config/config.toml`. Verify read-only/expunge-disabled
   configuration. List folders and all calendar collections; use VEVENT/VTODO
   metadata rather than names to select a calendar. Do not assume a fixed count.
4. **Bounded reads.** Pick one folder and a small result limit. Search a known ASCII
   keyword and a known Unicode keyword (report unavailable samples as untested).
   Fetch one harmless message through all required text/header pages and optionally
   a small attachment through bounded chunks. Expect explicit completeness/bounds,
   stable folder/UIDVALIDITY/UID references and unchanged flags. Query one VEVENT
   calendar over a short explicit timezone-aware window. Record errors without
   publishing messages, event text or references.
5. **Explicitly enable writes.** Stop only your connector session, set
   `profile = "full-access"`, preserve resource restrictions/key/ledger and leave
   expunge false. Reconnect and refresh client discovery. Expect 16 tools and no
   expunge; read-only remains the installation default. Confirm client write
   approvals before calling any mutation.
6. **Approved self-addressed mail.** Verify your own iCloud recipient locally.
   Approve exactly one uniquely labelled synthetic send and one reply to your own
   received test message, with no outgoing attachments. Use distinct operation IDs.
   Confirm SMTP acceptance and separately verify exactly one matching Sent copy per
   successful send/reply; acceptance alone does not guarantee inbox delivery.
   Stop on failure/uncertainty; never blindly resend or APPEND. Replaying a successful
   identical operation must use its ledger result, creating no additional send/copy.
7. **Move/read-flag check on test mail only.** Record the original flags and fresh
   reference of one test message. Approve INBOX → an existing permitted archive →
   INBOX and changing/restoring Seen on that message. Expect verified destination
   copies, new references, preserved other flags and restored original read state.
   Moves require UIDPLUS and may remove only the verified source UID, even when the
   separate expunge tool is disabled. Never use broad mailbox EXPUNGE or another
   message to work around failure.
8. **One temporary non-recurring event.** Select an explicit VEVENT calendar and
   approve a unique synthetic title, short future time range and IANA timezone,
   with no attendees. Create, read back, change only that event's title/time, read
   again and delete it using fresh references/ETags. Expect conflict checks and no
   remaining temporary event. Do not infer recurring/all-day/invitation coverage.
9. **Disconnect/restart/reconnect.** Close the client and verify its stdio child
   exits. Restart only your test connector with the same config/key/ledger, reconnect
   and expect 16 tools and valid unchanged-resource references. Refresh references
   after moves or external changes. If using a tunnel, stop the manual launcher with
   Ctrl+C, verify process exit, start it and refresh/reconnect ChatGPT separately.
   Record outcomes; terminal closure, crashes, reboot and unattended reliability
   are not established by a graceful restart test.
10. **Recoverable cleanup and safe finish.** Approve moving only the identified test
    mail copies to Deleted Messages, never permanently expunging. List each remaining
    copy/location privately; record ambiguous leftovers for reconciliation. Confirm
    the temporary event is gone. Return to read-only, reconnect/refresh and expect
    9 tools with write calls denied. Preserve config/signing key/ledger for recovery;
    do not publish them or delete state to clear an ambiguous operation.

Run only the approved scope. Missing samples, client approval-flow differences,
permission denials, ambiguous delivery/Sent persistence, or unsupported UIDPLUS
must be recorded as limitations. Read [mail recovery](mail-recovery.md),
[process lifetime](hosting.md) and [credential handling](credentials.md) first.
