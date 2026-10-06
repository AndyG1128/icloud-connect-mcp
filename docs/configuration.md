# Configuration reference

Select a TOML file with `ICLOUD_MCP_CONFIG` or use the installation-root
`.config/config.toml` through `scripts/run-stdio.sh`. The configuration is
operator-owned (root or current service user), never group/world writable, and
must not be a symlink. Prefer mode 0600. Unknown keys reject startup.
The operator, not an MCP tool/model, changes permissions and restarts the process.

| Setting | Actual default | Meaning |
|---|---|---|
| profile | `read-only` | `full-access` explicitly permits implemented writes |
| timezone | `UTC` | Valid IANA zone for floating calendar dates/times; Chicago is only a test case |
| account_email | empty | One personal iCloud mail address, account namespace and IMAP/SMTP login |
| username | empty | Apple Account username for CalDAV; can differ from mail address |
| password_file | empty | Absolute owner-private regular file containing app-specific password |
| state_dir | `$XDG_STATE_HOME/icloud-mcp` or `$HOME/.local/state/icloud-mcp` | Private persistent signing key, ledger and workflow lock |
| permissions | omitted | All tools allowed by profile; `[]` denies every tool |
| folders | omitted | All folders; `[]` denies all folders, canonical names required |
| calendars | omitted | All discovered calendar IDs; `[]` denies all calendar resources |
| permanent_expunge | `false` | Independent destructive-tool opt-in; never overrides read-only |
| sent_folder | `Sent Messages` | Existing canonical Sent mailbox; also subject to folder restriction |
| timeout_seconds | `30` | 1–120; async and network/workflow deadlines |
| max_results | `100` | 1–1000; bounded discovery/search and expunge batch size |
| max_message_bytes | `25000000` | 1024–100000000; complete MIME bound, explicit oversized error |
| max_page_chars | `16000` | 256–100000; paginated JSON/resource text |
| max_attachment_chunk | `48000` | 1024–1000000; attachment bytes per base64 chunk |
| max_date_days | `366` | 1–3660; bounded calendar date query |
| max_calendar_resources | `2000` | 1–10000; maximum queried calendar resources |
| max_event_bytes | `2000000` | 1024–10000000; complete calendar resource limit |

The secure setup helper intentionally chooses smaller initial calendar limits
(`max_date_days=31`, `max_calendar_resources=200`) and read-only access. These
helper choices are distinct from dataclass defaults. Full-message and event
pagination offsets are capped by schema; do not assume an unbounded bulk export.
Recurrence expansion has additional fixed safety budgets (20,000 prefix events
and a capped result horizon); narrow windows rather than disabling protections.

IMAPS is fixed to `imap.mail.me.com`/TLS 993; SMTP to `smtp.mail.me.com`/verified
STARTTLS 587; CalDAV begins at `https://caldav.icloud.com/`. Hosts are not model
arguments. Calendar redirects/resource hrefs must remain validated Apple hosts
and the authenticated principal's discovered collections.

To enable writes, deliberately set `profile = "full-access"`, review optional
allowlists, preserve the signing key/ledger, then restart only your connector
session and refresh client discovery. Leave `permanent_expunge = false` unless
permanent loss is explicitly intended. Disabling it removes discovery and denies
old cached tool calls at enforcement. Moving to Deleted Messages remains normal
recoverable deletion. Sending/replying requires access to the configured Sent folder.
