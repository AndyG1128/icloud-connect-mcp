# Removal

Identify only this installation's launcher/tunnel/connector by executable, user,
cwd, parent relationship and process start time. Stop that session gracefully;
do not stop unrelated applications. No autostart service is installed by this beta.
If you independently added a supervisor, disable/remove only that named service.

Move the installation to an owner-private recoverable quarantine before deleting
it. Preserve config, signing key, operation ledger and reviewed wheels until
recovery is no longer needed. Remove a temporary no-account probe state directory
only after checking it is actually the probe, not active account storage.
Package/runtime removal does not delete live mail or calendar resources.

Apple app-specific passwords, OpenAI keys, tunnel registrations and ChatGPT
connections are separate operator-controlled items. Decide whether to retain or
revoke each; removal never automatically revokes them. They may be shared with
another authorized installation. Do not export credentials/ledgers in a public
archive or issue. Secure deletion/full-disk encryption policy is a host concern.
