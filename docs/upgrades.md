# Upgrading

Review the exact release checksum, changelog, dependency/source inventory and
profile changes. Do not upgrade a different application or reuse its environment.
Quiesce only your connector/tunnel session after verifying current process identity.
Back up the private configuration, credentials, signing key and ledger safely;
do not commit those backups. Retain ambiguous-operation records.

Obtain the approved source revision, audit/install its runtime and build locks,
build the project wheel locally, and install it into this installation's own venv
with `--no-deps`. No public package/index upgrade path is offered in this scope. Keep the same state_dir,
identity.key, account namespace, Sent folder and resource restrictions. Do not use
editable installs. A package upgrade does not automatically enable writes or expunge.
Start manually, verify installed module hashes, MCP initialization and tool count,
then refresh the existing client connection. Do not recreate remote registrations
or the plugin simply to update a wheel.

No database migration or unattended rollback framework is claimed. For a revert,
stop only the verified session and reinstall the preserved prior wheel/dependency
set. Preserve configuration/key/ledger, and verify compatibility before startup.
Changing schema in a future version will require explicit migration/recovery plans.
