# Contributing

This is an independent community project in initial beta preparation; no outside
contributors, maintainer team, review turnaround or support SLA is claimed.
Publisher: andyg1128. Public source destination:
https://github.com/AndyG1128/icloud-connect-mcp . Authored files are AGPL-3.0-or-later;
third-party terms are retained. Contributor acceptance policy remains pending;
do not infer it from the old private development repository.

Use synthetic mail and calendars only. Never submit credentials, account identifiers,
private fixtures, signing keys, ledgers or operational logs. Do not copy proprietary
reference code. Record provenance and license notices for new dependencies/code.
Explain necessary behavior changes before broad refactors; preserve account routing,
reference checks, read-only flags, bounded recurrence and ambiguous-write protections.

Work in your own clone, use the exact pinned runtime/build/test locks and build a
regular wheel. Run the complete offline suite against the installed package and
MCP discovery for both profiles. Tests must not need live credentials or LLMs.
Reproduce errors with synthetic protocol responses and add targeted regression
coverage. If a behavior needs live verification, describe the exact isolated targets
and obtain approval; passing fixtures do not establish live coverage.
The intended issue/PR destination is the repository above. Use public issues only
for non-sensitive questions and synthetic bug reports; follow SECURITY.md for
vulnerability reporting. Contributor acceptance and a separate contributor license
policy are not established for this initial beta.
