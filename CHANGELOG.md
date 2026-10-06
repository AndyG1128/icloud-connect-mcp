# Changelog

## 0.2.0b1 — proposed initial public self-hosted beta

Not tagged, uploaded or published. Based on the independently deployed `17d23cc`
source revision, preserving its working mail/calendar algorithms and dependency pins.
Distribution name: `icloud-connect-mcp`; existing import and stdio command retained.
MCP version metadata updated to distinguish the beta from previous 0.1.0 wheels.
Stdio launcher resolves its own installation root and honors explicit config selection.
Public documentation, hash-locked clean-package validation, dependency/source inventory,
sanitized file manifest and artifact-specific license review are prepared separately.
The first publication scope is source Git only under AGPL-3.0-or-later for authored
files. Native/dependency bundles, public packages and images are deferred; container
recipes are excluded from the selected tree. No mail/calendar behavior changed.

The baseline includes Sent persistence separate from SMTP acceptance, strict
exact-or-one-trailing-CRLF Sent verification, UIDPLUS verified moves, checkpointed
targeted expunge and corrected IMAPClient UID-key validation. Read-only and
expunge-disabled installation defaults are retained. Outgoing attachments and
THISANDFUTURE writes remain unsupported. No hosted service or directory listing.
