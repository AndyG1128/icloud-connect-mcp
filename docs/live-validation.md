# Optional operator-run live validation

Live checks require your own independently configured credentials and deliberate
operator approval. Release preparation does not run them. Keep a read-only profile
for initial discovery/search/full-message/attachment/calendar checks and verify
flags before/after. Use bounded date ranges and examples you choose locally.

The supplied helpers `scripts/live_readonly_check.py` and
`scripts/prepare_live_plan.py` retain discovery/sample selections only in private
state/config paths. The live-read helper refuses full-access/expunge-enabled configs.
It prints counts/assertions/error codes, not message or event text. Discovery
includes each calendar/task collection; names alone never establish identity or
why an iOS device hides a collection. Compare VEVENT/VTODO metadata and device settings.

After reads succeed, separately review full-access settings, folder/calendar
restrictions and exact write test targets. Use self-addressed synthetic test mail
and a temporary non-recurring event, unique operation IDs and approved cleanup.
Do not automatically retry an ambiguous write. Record leftovers and keep test
messages recoverable. Permanent expunge requires independent operator opt-in and
explicit immediate confirmation of unrecoverable deletion for exact fresh refs.
Disabling it again must return 16 tools and deny stale cached expunge calls.
Never change unrelated live mail/calendar data to make a test pass.
