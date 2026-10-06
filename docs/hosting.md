# Hosting, startup and process lifetime

Tested release platform: CPython 3.12.15, Linux x86_64, Debian 13 container userland.
The pure connector wheel contains Python source, but its locked dependencies
include platform-specific native wheels. Untested OS/Python/architectures are not
advertised as supported; Windows cannot use current `fcntl` workflow locking.
Outbound connectivity needs TLS trust roots/timezone data, IMAPS 993, SMTP
STARTTLS 587 and CalDAV HTTPS 443. There is no inbound HTTP listener in this server.

## Manual operation

A local stdio client launches `scripts/run-stdio.sh` from the installation root.
`ICLOUD_MCP_CONFIG` explicitly selects another private config if needed.
The script removes tunnel API-key environment variables before starting the
installed `icloud-mcp` command. It does not import a different application's source.

For remote use, after your platform/account/tunnel setup, run:

```sh
.venv/bin/python scripts/run_tunnel.py --key-file .config/tunnel_runtime_key
```

The launcher runs doctor and starts the existing configured tunnel manually.
Ctrl+C is handled: it requests termination of the tunnel's separate process group,
waits ten seconds, then may force-kill that group. A recorded PID alone is not safe
for future shutdown; verify executable/owner/cwd/start time before sending signals.
The tunnel may own a Codex companion process in addition to the MCP child.

**Terminal closure is not a tested clean shutdown mechanism.** The launcher has
no SIGHUP/normal-exit cleanup handler; its tunnel child starts a new session. A
closed/lost terminal can leave an orphaned tunnel, or session/host policy can kill
it. Confirm process state/readiness locally instead of assuming it stopped.
Tunnel failure ends the manual launcher; the helper has no automatic restart loop.
Connector-child restart after failure is tunnel-client/version-dependent and
was not characterized. Host reboot stops processes; no service or autostart hook
is installed. These lifecycles have not been tested for unattended reliability.

## Supervised operation

No systemd unit or persistent service is installed or tested by this release.
An operator may independently design one with a dedicated service user, protected
credential source, persistent signing key/ledger, process-group cleanup, readiness
monitoring and careful restart policy. Do not automatically replay ambiguous
writes after restart. A supervisor restarting a process does not reconcile SMTP,
APPEND, COPY or calendar operations. Validate failure/reboot behavior before
claiming availability. No container recipe or image is in the selected public
source set; image distribution remains deferred for provenance/source compliance.
For a covered remote combination, complete the source-offer checks in source-access.md;
this source release is not a pre-cleared hosted-service offer.

Protect `.state` mode 0700, retain identity.key and the complete ledger across
upgrades, and keep only one intended account deployment. Mail workflow flock
serializes this connector's mail writes; it does not lock other clients or
coordinate calendar writes. Preserve SQLite backups only while safely quiesced,
or use an appropriate online backup method. Do not publish runtime volumes.
