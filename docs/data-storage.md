# Local data, privacy and retention

On server startup, the chosen private state directory is created/validated.
`identity.key` is a random 32-byte, mode-0600 HMAC key. It signs resource references
and inputs, and generates deterministic outbound Message-IDs from operation IDs.
Refs bind account namespace and mailbox UIDVALIDITY/UID, or calendar/resource/
UID/ETag/occurrence identity. They are encoded and signed, not encrypted.
Replacing the key invalidates existing references and changes dedup identities.

`operations-<account namespace>.sqlite3` is mode 0600. SQLite uses FULL synchronous
writes and stores operation-ID/input HMACs, states, structured results and dates.
`mail_checkpoints` persists stages, envelope/header construction metadata, flags,
UIDs, folder names, MIME hashes and Sent-copy verification. `sent_reconciliations`
retains the original outcome and verified reconciliation evidence. Outgoing bodies
are not stored as checkpoint text; envelopes can contain sender/recipient/subject
and reply headers. Results can contain message/calendar identifiers and event
summaries or other personal metadata. HMACs do not encrypt stored results.
Do not describe the ledger as free of private data.

Mail-operation locks use private `operations-*.mail-lock` files and OS flock;
a crashed process releases the kernel lock. There is no default retention limit,
expiry, vacuum/rotation service or model tool to erase the ledger. History is
retained until the operator changes/removes storage. Deleting it loses dedup and
recovery protections: an old operation ID might then trigger a new write.
`get_operation_status` can reveal private results even with read-only access.

Mail/event bodies and attachment bytes are fetched/decoded in memory for bounded
responses. There is no general message cache or download-to-disk tool. Some
serialized/decoded content is normalized; paginated payloads expose source hashes
and explicit limits. Snapshot pages are not transactionally locked against other
clients. Default warnings from third-party loggers are disabled by the server;
project request logs on stderr contain only tool, fixed code and random request ID.
No built-in log-file rotation or retention is provided. Clients, shells and
supervisors may record output/results independently.

The tunnel helper suppresses upstream runtime diagnostics, and reduces doctor
output to known check codes/counts. It does not prove tunnel-client never stores
its own configured operational files. PID/health/socket files are separate from
credentials. Optional live-validation helpers store private discovery names and
sample plans under `.state`/`.config`; keep those out of public releases.
