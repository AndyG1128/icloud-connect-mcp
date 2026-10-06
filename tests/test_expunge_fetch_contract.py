"""Pinned IMAPClient FETCH contract, using synthetic wire responses only."""
from types import SimpleNamespace

import pytest
from imapclient import IMAPClient

from .test_expunge_workflow import FOLDER, batch, blocked_replay, writes


def sdk_fetch(wire, uids):
    commands = []
    client = object.__new__(IMAPClient)
    client.use_uid = True
    client.normalise_times = True
    client._imap = SimpleNamespace(
        _command=lambda *args: commands.append(args) or "synthetic-tag",
        _command_complete=lambda *args: ("OK", [b"FETCH completed"]),
        _untagged_response=lambda *args: ("OK", wire),
    )
    rows = client.fetch(uids, ["UID", "FLAGS"])
    assert commands[0][:2] == ("UID", "FETCH")
    return rows


def test_pinned_sdk_consumes_wire_uid_as_mapping_key():
    # Response order and sequence numbers must never determine target identity.
    rows = sdk_fetch([
        b"41 (UID 42 FLAGS (\\Seen))",
        b"42 (UID 41 FLAGS ())",
    ], [41, 42])
    assert rows == {
        41: {b"SEQ": 42, b"FLAGS": ()},
        42: {b"SEQ": 41, b"FLAGS": (b"\\Seen",)},
    }
    assert all(b"UID" not in row for row in rows.values())


async def test_multi_uid_sdk_response_completes_targeted_fixture_workflow(make_connector, monkeypatch):
    c = make_connector(permanent_expunge=True)
    c.fake_imap.flagsets[FOLDER][42] = {b"\\Seen"}
    c.fake_imap.boxes[FOLDER][43] = c.fake_imap.boxes[FOLDER][41]
    c.fake_imap.flagsets[FOLDER][43] = {b"\\Deleted"}
    fetch = c.fake_imap.fetch

    def real_parser(uids, fields):
        rows = fetch(uids, fields)
        wire = [str(100 + i).encode() + b" (UID " + str(uid).encode()
                + b" FLAGS (" + b" ".join(row[b"FLAGS"]) + b"))"
                for i, (uid, row) in enumerate(reversed(list(rows.items())))]
        return sdk_fetch(wire, uids)

    monkeypatch.setattr(c.fake_imap, "fetch", real_parser)
    mark = c.fake_imap.add_flags

    def checked_mark(uids, flags, silent=True):
        assert c.fake_imap.flagsets[FOLDER][41] == set()
        assert c.fake_imap.flagsets[FOLDER][42] == {b"\\Seen"}
        mark(uids, flags, silent)

    monkeypatch.setattr(c.fake_imap, "add_flags", checked_mark)
    args = batch(c)
    result = await c.execute("expunge_messages", args)
    assert result["ok"], result
    assert result["result"]["permanently_expunged"] == 2
    assert set(c.fake_imap.boxes[FOLDER]) == {43}
    assert c.fake_imap.flagsets[FOLDER][43] == {b"\\Deleted"}
    assert [x[1] for x in writes(c) if x[0] == "uid_expunge"] == [[41, 42]]
    before = list(c.fake_imap.calls)
    replay = await c.execute("expunge_messages", args)
    assert replay["ok"] and replay["replayed_local_result"]
    assert c.fake_imap.calls == before


async def test_wire_uid_mismatch_cannot_use_sequence_as_target(make_connector, monkeypatch):
    c = make_connector(permanent_expunge=True)
    args = batch(c)
    rows = sdk_fetch([
        b"41 (UID 900 FLAGS ())",
        b"42 (UID 42 FLAGS (\\Seen))",
    ], [41, 42])
    assert set(rows) == {42}  # The SDK filters out the unsolicited UID 900.
    monkeypatch.setattr(c.fake_imap, "fetch", lambda *args: rows)
    result = await c.execute("expunge_messages", args)
    assert result["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert result["result"]["expunge_progress"] == {}
    assert not writes(c)
    await blocked_replay(c, args)


@pytest.mark.parametrize("case", [
    "sequence_mode", "unknown_mode", "unexpected_uid", "string_uid", "bool_uid",
    "conflicting_nested_uid", "noninteger_nested_uid", "missing_flags",
    "list_flags", "string_flags", "nonbytes_flag", "empty_flag", "nonascii_flag",
    "nondict_rows", "nondict_row",
])
async def test_invalid_identity_or_flags_blocks_mutation_and_replay(make_connector, monkeypatch, case):
    c = make_connector(permanent_expunge=True)
    args = batch(c)
    rows = {41: {b"SEQ": 7, b"FLAGS": ()}, 42: {b"SEQ": 8, b"FLAGS": (b"\\Seen",)}}
    if case == "sequence_mode": c.fake_imap.use_uid = False
    elif case == "unknown_mode": del c.fake_imap.use_uid
    elif case == "unexpected_uid": rows[43] = rows.pop(42)
    elif case == "string_uid": rows["42"] = rows.pop(42)
    elif case == "bool_uid": rows[True] = rows.pop(42)
    elif case == "conflicting_nested_uid": rows[42][b"UID"] = 41
    elif case == "noninteger_nested_uid": rows[42][b"UID"] = "42"
    elif case == "missing_flags": del rows[42][b"FLAGS"]
    elif case == "list_flags": rows[42][b"FLAGS"] = [b"\\Seen"]
    elif case == "string_flags": rows[42][b"FLAGS"] = "\\Seen"
    elif case == "nonbytes_flag": rows[42][b"FLAGS"] = (42,)
    elif case == "empty_flag": rows[42][b"FLAGS"] = (b"",)
    elif case == "nonascii_flag": rows[42][b"FLAGS"] = (b"\xff",)
    elif case == "nondict_rows": rows = []
    elif case == "nondict_row": rows[42] = None
    monkeypatch.setattr(c.fake_imap, "fetch", lambda *args: rows)
    result = await c.execute("expunge_messages", args)
    assert result["error"]["code"] == "IMAP_PROTOCOL", result
    assert result["result"]["expunge_progress"] == {}
    assert result["result"]["automatic_retry"] is False
    assert not writes(c)
    assert c.fake_imap.flagsets[FOLDER][41] == c.fake_imap.flagsets[FOLDER][42] == set()
    await blocked_replay(c, args)


async def test_consistent_optional_nested_uid_is_checked(make_connector, monkeypatch):
    c = make_connector(permanent_expunge=True)
    fetch = c.fake_imap.fetch

    def redundant_uid(uids, fields):
        rows = fetch(uids, fields)
        for uid, row in rows.items(): row[b"UID"] = uid
        return rows

    monkeypatch.setattr(c.fake_imap, "fetch", redundant_uid)
    assert (await c.execute("expunge_messages", batch(c)))["ok"]
