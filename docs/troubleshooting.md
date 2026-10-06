# Troubleshooting

Start with a no-account MCP initialize/list_tools/connector_ping test. Inspect
fixed error codes, configured profile and ownership, not private message bodies.
Keep stdout exclusively MCP; diagnostics go to stderr. Raw third-party exception
strings and tunnel logs can be sensitive and are suppressed by normal launchers.

| Code/symptom | Action |
|---|---|
| STARTUP_FAILED / CONFIG | Check IANA timezone, unknown keys, owner/mode, state path and installed dependency lock |
| CREDENTIALS / login failure | Verify app-specific password locally; mail uses account_email, calendar uses username; never substitute Outlook mailbox |
| PERMISSION_DENIED | Check operator profile/allowlist; permanent expunge has separate opt-in; refresh cached discovery |
| RESOURCE_DENIED | Check canonical source/destination/Sent folder or discovered calendar ID restrictions |
| STALE_REFERENCE | Rediscover/re-search; folder UIDVALIDITY or signed resource identity changed |
| CONFLICT / MAIL_CONFLICT | Another client changed flags/resource; fetch fresh evidence before a newly approved action |
| SEARCH_ENCODING_UNSUPPORTED | Server rejected Unicode literal search; do not assume preview filtering found everything |
| MESSAGE_TOO_LARGE / LIMIT_EXCEEDED / EXPANSION_LIMIT | Narrow window/page/query or intentionally review bounds; no full-preview substitution |
| SMTP_AMBIGUOUS / MAIL_UNCERTAIN / TIMEOUT | Stop; inspect operation status. The server worker may finish after a client timeout. Never automatically resend/retry |
| OPERATION_ID_CONFLICT | Same operation ID was supplied with different inputs; correct inputs instead of resetting the ledger |
| OPERATION_NOT_REPLAYABLE | Failed/incomplete outcome is blocked. Reconcile exact evidence, not a blind new-ID retry |
| SENT_COPY_FAILED | SMTP may be accepted while APPEND failed; distinguish persistence from send/delivery |
| UNSUPPORTED / UNSUPPORTED_RANGE | UIDPLUS or requested calendar semantics are unavailable; do not weaken checks |

For a tunnel, run the manual helper with `--doctor-only` and check its configured
Unix readiness socket. Readiness is not a ChatGPT tool invocation. Check current
process identities before stopping an orphaned session. Never reset the signing
key/ledger to get around an uncertainty error. Consult [recovery](mail-recovery.md)
and inspect logs locally; redact account names, subjects, hrefs, references and
credentials before a report. Public bug reports should use synthetic data.
