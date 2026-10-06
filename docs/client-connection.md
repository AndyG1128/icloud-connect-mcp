# Client connection

## Verified local stdio path

A local MCP client can launch the reviewed installation's `scripts/run-stdio.sh`
with its own private config and persistent state. The existing executable remains
`icloud-mcp` after installing the `icloud-connect-mcp` distribution. Test initialize,
list_tools and connector_ping first. The concretely tested local client is the
official Python MCP SDK; see the complete [README recipe](../README.md#test-an-account-free-local-mcp-client)
and [JSON template](../examples/local-stdio.example.json). No other local client
compatibility is claimed. Local success does not establish remote access.
This service exposes no HTTP port and provides no generic Internet authentication layer.

## Secure MCP Tunnel: separate prerequisites

The [official Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
supports local stdio or HTTP MCP. This connector uses the tested stdio path only.
Each operator must use their own Platform organization, suitable OpenAI account/
ChatGPT workspace access, tunnel association and runtime key. Creating/managing a
tunnel requires Tunnels Read + Manage; running/selecting it requires Read + Use.
Platform organization permissions and ChatGPT custom-MCP workspace permissions
are separate. Availability of a Tunnel connection option in another account or
plan is not established by this project's successful personal installation.
Check with the target workspace/organization administrator and current guide.

Download the official tunnel-client for your OS from the guide, verify the
published checksum and its own license/terms, and install it locally as
`.bin/tunnel-client`. It is not bundled or relicensed by this release. Use the
client's documented configuration/doctor flags for that exact version. Create or
select your authorized tunnel independently; no registration is created by these
project scripts. The tunnel ID is an identifier, not sufficient authentication.

Copy `examples/tunnel-profile.example.yaml` into ignored `.config/tunnel.yaml`
mode 0600. Replace the tunnel-ID placeholder and every `/srv/icloud-connect-mcp`
path with your installation root; keep the stdio `main` channel. This template is
not an active configuration. Use a dedicated OpenAI runtime key selected explicitly
through the secure helper/file/environment mechanism described in credentials.md.

```sh
.venv/bin/python scripts/setup_tunnel_key.py
.venv/bin/python scripts/run_tunnel.py --key-file .config/tunnel_runtime_key --doctor-only
.venv/bin/python scripts/run_tunnel.py --key-file .config/tunnel_runtime_key
```

Startup is manual; see [process lifetime](hosting.md). For the configured Unix
health socket, a local readiness check does not expose an HTTP port:

```sh
curl --silent --output /dev/null --write-out '%{http_code}\n' \
  --unix-socket /srv/icloud-connect-mcp/.state/tunnel-health.sock http://localhost/readyz
```

Substitute your installation path. HTTP 200 verifies tunnel readiness, not a
ChatGPT invocation or approval-flow behavior. No autostart/reboot reliability is claimed.

Where supported, current official ChatGPT setup is Plugins → Add custom MCP server
→ Connection: Tunnel. Select your associated tunnel, review authentication/risk
settings and create your private connection. Workspace/account restrictions may
prevent this path. For an existing connection, deploy/start the reviewed server,
open ChatGPT Plugins, select that existing connection, choose Refresh, inspect tool
metadata, then start a new conversation. [Official refresh procedure](https://developers.openai.com/plugins/deploy/connect-chatgpt).
Counts are 9 read-only, 16 full/expunge-disabled or 17 with independent expunge opt-in,
unless granular permissions reduce them. Test connector_ping through the target
client and confirm read/write approvals before live work.

Prior reports established connectivity in ChatGPT chats, mobile chats and Pages
in one development installation. They do not establish universal availability,
all tool behaviors, or write approvals on every surface for another user/account.
Codex/Responses tunnel paths described by OpenAI are not independently validated
by this beta. A ChatGPT directory submission, public HTTPS hosting, OAuth server,
public app registration and new remote permissions are outside this release.
For a modified/covered remote combination, complete source-access.md and offer
the reviewed running version's source visibly to every user. Authored-source
destination is https://github.com/AndyG1128/icloud-connect-mcp ; select the exact
public revision and verify all required operator network-source materials separately.
