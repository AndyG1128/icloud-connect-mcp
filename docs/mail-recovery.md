# Sent persistence, verified moves and targeted permanent deletion

Both send and reply build one MIME message and transmit those exact bytes over
SMTP. After confirmed SMTP acceptance is durably recorded, the connector checks
the operator-configured `sent_folder` and APPENDs those same bytes with Seen.
The copy is fetched using EXAMINE/BODY.PEEK and byte-verified; no Bcc header is
added. SMTP acceptance does not establish recipient delivery.

Sent verification accepts only `stored == submitted` or precisely
`stored == submitted + b"\r\n"`. The latter records
`trailing_crlf_exception_used: true` and `exact_mime_verified: false`.
Both submitted and stored SHA-256 hashes are retained. There is no whitespace
stripping, global line-ending conversion, or ignored header/body difference.
Move-copy verification remains strictly byte-for-byte and never uses this rule.

Operator-only Sent reconciliation requires the original operation arguments,
durable SMTP acceptance, stable mailbox identity and exactly one verified copy
with its recorded Message-ID. It performs only remote reads, then atomically
updates the local checkpoint/result while retaining the previous state, failure
and verified evidence in the ledger's Sent reconciliation history. No MCP tool
for this operator action is exposed; the existing status tool reports its history.

An exact existing Message-ID/MIME match is reused without APPEND. Multiple
matches or a same-ID/different-MIME message cause uncertainty rather than a
duplicate. A failed persistence operation returns `smtp_accepted: true` separately
from `sent_copy.status`. Clients must inspect that result even on tool error.
`sent_folder_copy_created` indicates a confirmed connector APPEND response.
`connector_append_attempted` and `append_outcome` separately preserve lost-response
uncertainty about who created a verified existing copy. An existing copy found
before APPEND has `connector_append_attempted: false`.

The ledger freezes Date, multipart boundary, reply routing/thread headers and
the MIME digest. Bodies are not stored; explicit identical-input recovery
reconstructs the original bytes and checks their digest. There are no spool files.
SMTP started without a durable acceptance checkpoint is never resent. A checked
tagged negative APPEND can be explicitly retried after searching for a copy;
interrupted or accepted-but-unverified APPEND is never repeated. An empty search
cannot disprove an earlier uncertain write, so recovery reports uncertainty.

Moving requires UIDPLUS. It inspects capability, source identity/content/flags/
INTERNALDATE and destination UIDVALIDITY/UIDNEXT before COPY. COPYUID supplies a
new identity; absent/lost COPYUID uses a bounded search among new destination
UIDs and verifies bytes, persistent flags and date. Pre-existing identical mail
cannot be mistaken for the new copy. Multiple candidates stop the workflow.

Only after destination verification does it revalidate source UIDVALIDITY,
bytes and flags, mark the single source UID Deleted and UID EXPUNGE that UID.
This removes the original source record to provide true move semantics. The
verified destination remains recoverable. It is independent of the separately
operator-enabled permanent-expunge tool, which remains disabled by default.
Unrelated Deleted messages are never expunged. MOVE-only servers are rejected
because this workflow must verify the copy before source removal.

Success requires source absence and a final verified destination reference.
Interrupted copy/removal can leave both records, sometimes with Deleted on the
source. Errors report incomplete/uncertain outcomes; they never claim a true
move for duplicates. Explicit same-ID recovery avoids another COPY and recognizes
completed removal. An uncertain expunge with the source still present is not
repeated. Missing UIDPLUS is rejected before COPY, without modifying either folder.

An account-specific private file lock serializes these workflows across local
processes. The worker retains it after an async timeout until it actually exits.
Deadlines are checked before each next write, preventing late COPY completion
from continuing into source removal after the deadline. SQLite checkpoints use
FULL synchronous commits. Changed inputs under the same operation ID are rejected;
old operations without mail checkpoints remain non-replayable unless successful.

This is not a distributed transaction or an exactly-once delivery guarantee.
IMAP provides no atomic transaction covering COPY, verification and removal.
Other clients can concurrently alter or move records; observed conflicts stop
the workflow, but external clients cannot be locked by this service. Provider
replication delay, changed MIME, UIDVALIDITY changes, missing mappings and
interrupted responses can require manual reconciliation. No timeout or error
triggers automatic resend, broad expunge, another copy, or artifact cleanup.

Synthetic tests establish protocol/recovery behavior. Each deployment still
requires separately approved provider tests using exact disposable messages,
no concurrent edits to those messages, and no deliberate live fault injection.

## Targeted permanent deletion

`expunge_messages` is separately disabled by default. An operator must enable it;
the client must obtain explicit permanent-delete approval before invocation.
All references must bind the configured account and one canonical folder with
the same current UIDVALIDITY and distinct, existing UIDs. Folder/tool permissions
and UIDPLUS are checked before mutation. No general-purpose flag-setting tool
is exposed. After validating the whole batch, the workflow adds Deleted only
to targets not already marked, verifies all other persistent flags, revalidates
the mailbox and targets, then issues UID EXPUNGE for the exact same UID batch.
No broad EXPUNGE or CLOSE is used; unrelated Deleted messages survive.

The existing private operation ledger records initial/observed flags, marking
and expunge phases, attempted targets and read-back absent/remaining UIDs. A
lost response can mean deletion happened even if the tool reports an error.
Read-back absence is evidence, not a reason to repeat an uncertain command.
When read-back is unavailable, the last durable phase remains uncertain. A
checkpoint/result persistence failure leaves the durable operation blocked.

Failure after marking can leave targets with Deleted added but not expunged.
There is no automatic flag restoration: an external client may expunge marked
mail, so do not describe those records as safely recoverable without checking.
Failed/incomplete same-ID attempts never resume or repeat marking/expunge.
Successful same-ID replay uses the cached result; changed inputs are rejected.
Use read-only searches/status to reconcile outcomes before any separately
approved new operation. The account lock serializes local mail workflows, but
other clients cannot be locked and may concurrently change flags or locations.
