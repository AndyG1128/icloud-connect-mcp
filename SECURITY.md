# Security reporting

Publisher: andyg1128. Repository:
https://github.com/AndyG1128/icloud-connect-mcp .

GitHub private vulnerability reporting is **enabled**, verified through the
repository API after owner-approved activation on 2026-10-05.
Report a suspected vulnerability privately using:
https://github.com/AndyG1128/icloud-connect-mcp/security/advisories/new

Alternatively, open the repository's Security tab and select **Report a
vulnerability**. Submit sensitive reproduction details through that private form,
not a public issue or pull request. If the private form becomes unavailable,
retain sensitive details locally until a private route is verified again; do not
send them to a guessed email address. No response-time or support SLA is claimed.

Do not open a public issue containing passwords, keys, account addresses, message
content, event data, resource references or ledgers. Do not use public issues for
sensitive vulnerability reports. A private report should identify version/artifact hash, platform,
a synthetic reproduction, affected permissions and observed impact.

The service is one private account per operator, not a multi-user hosted service.
Client approvals, TLS, file permissions, resource allowlists and server profiles
are separate controls. Email/event text is untrusted. There is no encrypted local
ledger, credential manager daemon, general HTTP authentication layer or unattended
restart service supplied. Source scanners and offline tests are not a security
audit guarantee. Only the reviewed candidate platform is validated; no maintained
version matrix or long-term security support promise is established yet.
