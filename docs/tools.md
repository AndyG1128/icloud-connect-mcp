# Tool and permission matrix

All tools have typed schemas and bounded arguments. Read tools carry read-only,
non-destructive hints; write tools carry destructive/non-idempotent hints and
require client approval. An annotation is not an authorization barrier: the
server independently enforces the operator profile and resource restrictions.

| Tool | Read-only | Full access | Effect/resource restriction |
|---|---|---|---|
| connector_ping | yes | yes | No account access; creates ordinary local server state at startup |
| get_operation_status | yes | yes | Reads private account-scoped ledger results/history |
| list_mail_folders | yes | yes | Lists selectable permitted canonical IMAP folders |
| search_messages | yes | yes | Explicit folder, literal query and bounded page |
| fetch_message | yes | yes | Signed message ref; complete headers/text/HTML/attachment metadata pages |
| fetch_attachment | yes | yes | Signed attachment ref; bounded decoded bytes as base64 |
| list_calendars | yes | yes | Enumerates authenticated principal collections with VEVENT/VTODO distinction |
| get_events | yes | yes | Explicit calendar and bounded half-open date window |
| fetch_event | yes | yes | Complete VCALENDAR resource pages and digest |
| send_message | denied | yes | SMTP plus separately checkpointed Sent persistence |
| reply_message | denied | yes | Referenced message threading; Reply-To is untrusted; may reply to self |
| move_message | denied | yes | Source/destination folder permissions; verified copy and UIDPLUS targeted source removal |
| set_message_read | denied | yes | Changes only Seen on explicit signed reference |
| create_event | denied | yes | Explicit calendar; conditional creation; optional recurring event |
| update_event | denied | yes | Signed resource ref, expected ETag, explicit occurrence/series scope |
| delete_event | denied | yes | ETag and explicit occurrence/series scope; EXDATE or resource deletion |
| expunge_messages | denied | only with independent opt-in | One folder/UIDVALIDITY, explicit validated UIDs; target marking and UID EXPUNGE |

Counts without granular restrictions: 9 read-only, 16 full-access/expunge disabled,
17 full-access/expunge enabled. Optional permissions can reduce these counts.
Read-only never exposes or permits writes even if an allowlist names them.
There is no broad EXPUNGE, arbitrary URL/account selection, general-purpose
flag-setting tool, filesystem/shell tool, or tool for changing access profile.
Opaque references are signed, not encrypted: treat them as private data. They
carry identifiers and should not be pasted into public reports.
