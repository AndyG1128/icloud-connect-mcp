# Credentials

Every user hosts their own server and supplies their own credentials. No shared
publisher account, implicit credential reuse, or automatic access to another
application's configuration exists. Supply your iCloud mail address as
`account_email`; the Apple Account login for CalDAV is `username`. They can differ.
Use an app-specific password generated through your Apple Account settings, not
your normal login password. Check Apple's current eligibility/account requirements.

Run `scripts/setup_credentials.py` with the installation's Python in a local TTY.
The app-password prompt is hidden; unsafe redirection, pre-existing files,
symlinks, incorrect ownership and world/group access are refused. The helper
stores `.config/config.toml` and `.config/icloud_app_password` mode 0600 under
mode-0700 `.config`. It starts nothing. Files are ordinary protected plaintext,
not encrypted at rest. Host full-disk encryption and backups are operator choices.
The runtime password file is read when account connections are created. Do not
put passwords in shell arguments, environment dumps, source control or chat.

Optional Secure MCP Tunnel authentication is separate from the iCloud password.
A tunnel ID is not an authentication credential. Use a dedicated OpenAI runtime
key with the current platform's Tunnels Read and Use permissions, selected
explicitly with `--key-file` or `--key-env`, or the launcher's hidden TTY prompt.
`scripts/setup_tunnel_key.py` creates a dedicated ignored owner-private file;
it never discovers another application's model key. A chosen environment
variable is intended for an operator-controlled secret manager. The launcher
passes the key only to tunnel-client, and the stdio child unsets the control-plane
key variables. Check file ownership, 0600 permissions and current official setup
before startup. Do not bundle either credentials or tunnel-client in a release.
