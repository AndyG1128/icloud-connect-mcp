# Changelog

## 0.2.0b1 — published source-only self-hosted beta (2026-10-05)

Published as source Git, with initial public commit `65538d2` and documentation
corrections through `024e46b`. No tag, release assets, public package, dependency
bundle, container image or ChatGPT directory listing has been released. The beta
preserves its previously validated mail/calendar algorithms and dependency pins.
Distribution name: `icloud-connect-mcp`; existing import and stdio command retained.
MCP version metadata updated to distinguish the beta from previous 0.1.0 wheels.
Stdio launcher resolves its own installation root and honors explicit config selection.
Public documentation, hash-locked clean-package validation, dependency/source inventory,
and artifact-specific license/source inventories accompany the public source.
The first publication scope is source Git only under AGPL-3.0-or-later for authored
files. Native/dependency bundles, public packages and images are deferred; container
recipes are excluded from the selected tree. No mail/calendar behavior changed.

The baseline includes Sent persistence separate from SMTP acceptance, strict
exact-or-one-trailing-CRLF Sent verification, UIDPLUS verified moves, checkpointed
targeted expunge and corrected IMAPClient UID-key validation. Read-only and
expunge-disabled installation defaults are retained. Outgoing attachments and
THISANDFUTURE writes remain unsupported. No hosted service or directory listing.

## Onboarding and offline CI documentation pass

Complete first-run installation
pins public revision `024e46b` and tests an account-free local Python MCP SDK client.
The hosted CI workflow builds and installs the wheel in separate fresh environments,
then runs installed-package tests with networking disabled. Public evidence and an
independent acceptance checklist distinguish offline, historical live and unrun tests.
No connector behavior, dependency pins, licensing or access defaults change.
