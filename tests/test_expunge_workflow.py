"""Synthetic permanent-delete workflows; never contact an account."""
import imaplib
import pytest
from icloud_mcp.errors import ConnectorError
from icloud_mcp.identities import Identities
from icloud_mcp.mail import NegativeIMAPResponse


FOLDER = 'Archive/Quoted "Folder"'


def batch(c):
    return dict(operation_id="synthetic-delete", message_refs=[
        c.ids.issue("message", folder=FOLDER, uidvalidity=c.fake_imap.uv[FOLDER], uid=uid)
        for uid in (41, 42)])


def writes(c):
    return [x for x in c.fake_imap.calls if x[0] in ("add_flags", "uid_expunge", "move", "copy", "append")]


async def blocked_replay(c, args):
    before = list(c.fake_imap.calls)
    result = await c.execute("expunge_messages", args)
    assert result["error"]["code"] == "OPERATION_NOT_REPLAYABLE"
    assert c.fake_imap.calls == before


@pytest.mark.parametrize("initial", [
    (set(), {b"\\Seen", b"\\Answered", b"custom"}),
    ({b"\\Deleted"}, {b"\\Seen"}),
    ({b"\\Seen", b"\\Deleted"}, {b"\\Answered", b"\\Deleted"}),
    ({b"\\Recent"}, {b"\\Seen", b"\\Flagged"}),
])
async def test_marks_only_validated_targets_preserving_mixed_flags(make_connector, monkeypatch, initial):
    c = make_connector(permanent_expunge=True)
    c.fake_imap.capabilities.discard("MOVE")
    for uid, flags in zip((41, 42), initial):
        c.fake_imap.flagsets[FOLDER][uid] = set(flags)
    c.fake_imap.boxes[FOLDER][43] = c.fake_imap.boxes[FOLDER][41]
    c.fake_imap.flagsets[FOLDER][43] = {b"\\Deleted", b"\\Seen"}
    before = {uid: set(flags) for uid, flags in c.fake_imap.flagsets[FOLDER].items()}
    expunge = c.fake_imap.uid_expunge
    def checked(uids):
        assert uids == [41, 42]
        assert all(c.fake_imap.flagsets[FOLDER][uid] == before[uid] | {b"\\Deleted"} for uid in uids)
        assert c.fake_imap.flagsets[FOLDER][43] == before[43]
        expunge(uids)
    monkeypatch.setattr(c.fake_imap, "uid_expunge", checked)
    args = batch(c)
    result = await c.execute("expunge_messages", args)
    assert result["ok"], result
    assert result["result"]["permanently_expunged"] == 2
    assert result["result"]["broad_expunge"] is False
    to_mark = [uid for uid in (41, 42) if b"\\Deleted" not in before[uid]]
    assert result["result"]["marked_uids"] == to_mark
    assert [x[1] for x in writes(c) if x[0] == "add_flags"] == ([to_mark] if to_mark else [])
    assert set(c.fake_imap.boxes[FOLDER]) == {43}
    assert 1 in c.fake_imap.boxes["INBOX"]
    status = c.ledger.status(args["operation_id"])
    assert status["state"] == "succeeded"
    assert status["mail_checkpoint"]["expunge_status"] == "verified"
    before_calls = list(c.fake_imap.calls)
    replay = await c.execute("expunge_messages", args)
    assert replay["ok"] and replay["replayed_local_result"]
    assert c.fake_imap.calls == before_calls
    changed = dict(args, message_refs=args["message_refs"][:1])
    assert (await c.execute("expunge_messages", changed))["error"]["code"] == "OPERATION_ID_CONFLICT"
    assert c.fake_imap.calls == before_calls


@pytest.mark.parametrize("options", [
    {"permanent_expunge": False},
    {"profile": "read-only", "permanent_expunge": True},
    {"permissions": ("connector_ping",), "permanent_expunge": True},
])
async def test_permission_denial_precedes_ledger_and_imap(make_connector, options):
    c = make_connector(**options)
    result = await c.execute("expunge_messages", batch(c))
    assert result["error"]["code"] == "PERMISSION_DENIED"
    assert not c.fake_imap.calls and not c.fake_smtp.attempts and not c.fake_dav.calls
    assert c.ledger.db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


@pytest.mark.parametrize("case,code", [
    ("stale", "STALE_REFERENCE"), ("missing_first", "MESSAGE_NOT_FOUND"),
    ("missing_second", "MESSAGE_NOT_FOUND"), ("uidplus", "UNSUPPORTED"),
    ("foreign", "INVALID_REFERENCE"), ("folder", "RESOURCE_DENIED"),
    ("mixed_folders", "INVALID_INPUT"), ("duplicate", "INVALID_INPUT"),
    ("mixed_uidvalidity", "INVALID_INPUT"),
])
async def test_every_target_validated_before_any_mutation(make_connector, case, code):
    c = make_connector(permanent_expunge=True)
    args = batch(c)
    if case == "stale": c.fake_imap.uv[FOLDER] += 1
    if case.startswith("missing"):
        del c.fake_imap.boxes[FOLDER][41 if case == "missing_first" else 42]
    if case == "uidplus": c.fake_imap.capabilities.clear()
    if case == "foreign":
        args["message_refs"][1] = Identities(c.ids.key, "other@example.invalid").issue(
            "message", folder=FOLDER, uidvalidity=c.fake_imap.uv[FOLDER], uid=42)
    if case == "folder": c.mail.permissions.config = type("Restricted", (), {"folders": ("INBOX",)})()
    if case == "mixed_folders":
        args["message_refs"][1] = c.ids.issue("message", folder="INBOX", uidvalidity=c.fake_imap.uv["INBOX"], uid=1)
    if case == "duplicate": args["message_refs"][1] = args["message_refs"][0]
    if case == "mixed_uidvalidity":
        args["message_refs"][1] = c.ids.issue("message", folder=FOLDER, uidvalidity=c.fake_imap.uv[FOLDER]+1, uid=42)
    result = await c.execute("expunge_messages", args)
    assert result["error"]["code"] == code, result
    assert not writes(c)
    assert not c.fake_imap.flagsets[FOLDER][41] and not c.fake_imap.flagsets[FOLDER][42]


@pytest.mark.parametrize("change,code", [("uv", "STALE_REFERENCE"), ("missing", "MESSAGE_NOT_FOUND"), ("flags", "MAIL_CONFLICT")])
async def test_revalidation_on_readwrite_selection(make_connector, monkeypatch, change, code):
    c = make_connector(permanent_expunge=True); args = batch(c)
    select = c.fake_imap.select_folder
    def raced(name, readonly=False):
        if not readonly:
            if change == "uv": c.fake_imap.uv[name] += 1
            if change == "missing": c.fake_imap.boxes[name].pop(42, None)
            if change == "flags": c.fake_imap.flagsets[name][42].add(b"\\Flagged")
        return select(name, readonly)
    monkeypatch.setattr(c.fake_imap, "select_folder", raced)
    result = await c.execute("expunge_messages", args)
    assert result["error"]["code"] == code
    assert not writes(c)


async def test_failure_between_marking_and_expunge_records_flags_and_blocks_retry(make_connector, monkeypatch):
    c = make_connector(permanent_expunge=True); args = batch(c); calls = 0
    def deadline(end):
        nonlocal calls
        calls += 1
        if calls == 2: raise ConnectorError("TIMEOUT", "Synthetic deadline.")
    monkeypatch.setattr(c.mail_operations, "deadline", deadline)
    result = await c.execute("expunge_messages", args)
    assert result["error"]["code"] == "TIMEOUT"
    status = c.ledger.status(args["operation_id"])
    assert status["state"] == "ambiguous"
    cp = status["mail_checkpoint"]
    assert cp["mark_status"] == "verified" and cp["expunge_status"] == "not_started"
    assert cp["remaining_uids"] == [41, 42] and cp["observed_absent_uids"] == []
    assert all(b"\\Deleted" in c.fake_imap.flagsets[FOLDER][uid] for uid in (41,42))
    assert not any(x[0] == "uid_expunge" for x in writes(c))
    assert result["result"]["expunge_progress"] == cp
    await blocked_replay(c, args)


@pytest.mark.parametrize("change", ["uv", "missing", "flags"])
async def test_postmark_identity_or_flag_conflict_prevents_expunge(make_connector, monkeypatch, change):
    c = make_connector(permanent_expunge=True); args = batch(c)
    select = c.fake_imap.select_folder; readwrite = 0
    def raced(name, readonly=False):
        nonlocal readwrite
        if not readonly:
            readwrite += 1
            if readwrite == 2:
                if change == "uv": c.fake_imap.uv[name] += 1
                if change == "missing": c.fake_imap.boxes[name].pop(42)
                if change == "flags": c.fake_imap.flagsets[name][42].add(b"\\Answered")
        return select(name, readonly)
    monkeypatch.setattr(c.fake_imap, "select_folder", raced)
    result = await c.execute("expunge_messages", args)
    assert result["error"]["code"] == "MAIL_UNCERTAIN"
    cp = c.ledger.status(args["operation_id"])["mail_checkpoint"]
    assert cp["mark_status"] == "verified" and cp["expunge_status"] == "not_started"
    assert not any(x[0] == "uid_expunge" for x in writes(c))
    if change == "missing": assert cp["observed_absent_uids"] == [42]
    if change == "flags": assert cp["observed_flags"]["42"] == ["\\Answered", "\\Deleted"]
    await blocked_replay(c, args)


async def test_failed_error_readback_retains_uncertainty_without_other_mutations(make_connector, monkeypatch):
    c = make_connector(permanent_expunge=True); args = batch(c); mark = c.fake_imap.add_flags
    def disconnected(uids, flags, silent=True):
        mark(uids, flags, silent)
        def broken(*args, **kwargs): raise imaplib.IMAP4.abort("PRIVATE disconnected read-back")
        monkeypatch.setattr(c.fake_imap, "fetch", broken)
        raise imaplib.IMAP4.abort("PRIVATE disconnected mark response")
    monkeypatch.setattr(c.fake_imap, "add_flags", disconnected)
    result = await c.execute("expunge_messages", args)
    assert result["error"]["code"] == "MAIL_UNCERTAIN" and "PRIVATE" not in str(result)
    cp = c.ledger.status(args["operation_id"])["mail_checkpoint"]
    assert cp["mark_status"] == "uncertain" and cp["expunge_status"] == "not_started"
    assert "observed_absent_uids" not in cp and "remaining_uids" not in cp
    assert not any(x[0] == "uid_expunge" for x in writes(c))
    await blocked_replay(c, args)


@pytest.mark.parametrize("case", ["partial", "negative", "changed_other_flags"])
async def test_mark_failures_never_continue_to_expunge(make_connector, monkeypatch, case):
    c = make_connector(permanent_expunge=True); args = batch(c); mark = c.fake_imap.add_flags
    def interrupted(uids, flags, silent=True):
        if case == "negative": raise NegativeIMAPResponse()
        mark(uids[:1] if case == "partial" else uids, flags, silent)
        if case == "partial": raise imaplib.IMAP4.abort("PRIVATE synthetic marking error")
        c.fake_imap.flagsets[FOLDER][42].add(b"\\Answered")
    monkeypatch.setattr(c.fake_imap, "add_flags", interrupted)
    result = await c.execute("expunge_messages", args)
    assert not result["ok"] and "PRIVATE" not in str(result)
    cp = c.ledger.status(args["operation_id"])["mail_checkpoint"]
    assert cp["expunge_status"] == "not_started" and cp["remaining_uids"] == [41,42]
    assert not any(x[0] == "uid_expunge" for x in writes(c))
    assert cp["observed_flags"]["41"] == ([] if case == "negative" else ["\\Deleted"])
    await blocked_replay(c, args)


@pytest.mark.parametrize("case", ["not_completed", "completed", "partial", "negative", "ok_but_partial"])
async def test_expunge_partial_and_ambiguous_outcomes_never_repeated(make_connector, monkeypatch, case):
    c = make_connector(permanent_expunge=True); args = batch(c); expunge = c.fake_imap.uid_expunge
    attempts = []
    def interrupted(uids):
        attempts.append(list(uids))
        if case == "negative": raise NegativeIMAPResponse()
        if case in ("completed", "partial", "ok_but_partial"):
            expunge(uids if case == "completed" else uids[:1])
        if case != "ok_but_partial": raise imaplib.IMAP4.abort("PRIVATE synthetic expunge error")
    monkeypatch.setattr(c.fake_imap, "uid_expunge", interrupted)
    result = await c.execute("expunge_messages", args)
    assert not result["ok"] and "PRIVATE" not in str(result)
    status = c.ledger.status(args["operation_id"]); cp = status["mail_checkpoint"]
    expected_absent = [41,42] if case == "completed" else [41] if case in ("partial", "ok_but_partial") else []
    assert cp["observed_absent_uids"] == expected_absent
    assert cp["remaining_uids"] == [uid for uid in (41,42) if uid not in expected_absent]
    assert cp["mark_status"] == "verified"
    assert cp["expunge_status"] == ("rejected" if case == "negative" else "accepted" if case == "ok_but_partial" else "uncertain")
    assert status["state"] == ("failed" if case == "negative" else "ambiguous")
    await blocked_replay(c, args)
    assert attempts == [[41,42]]


@pytest.mark.parametrize("phase", ["before_mark", "after_mark", "after_expunge", "final_result"])
async def test_ledger_failure_prevents_further_mutation_and_replay(make_connector, monkeypatch, phase):
    c = make_connector(permanent_expunge=True); args = batch(c)
    checkpoint = c.ledger.checkpoint
    def failing(op, value=None):
        if value is not None and ((phase == "before_mark" and value["mark_status"] == "started") or
                (phase == "after_mark" and value["mark_status"] == "accepted") or
                (phase == "after_expunge" and value["expunge_status"] == "accepted")):
            raise ConnectorError("LEDGER_FAILURE", "Synthetic checkpoint failure.")
        return checkpoint(op, value)
    monkeypatch.setattr(c.ledger, "checkpoint", failing)
    if phase == "final_result":
        def finish(*args): raise RuntimeError("PRIVATE synthetic result commit error")
        monkeypatch.setattr(c.ledger, "finish", finish)
    result = await c.execute("expunge_messages", args)
    assert result["error"]["code"] == "LEDGER_FAILURE"
    assert "PRIVATE" not in str(result)
    assert c.ledger.status(args["operation_id"])["state"] == "in_progress"
    if phase == "before_mark": assert not writes(c)
    if phase == "after_mark": assert [x[0] for x in writes(c)] == ["add_flags"]
    if phase in ("after_expunge", "final_result"): assert not c.fake_imap.boxes[FOLDER]
    await blocked_replay(c, args)
