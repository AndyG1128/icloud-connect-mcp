"""Synthetic fault injection; never uses live configuration or credentials."""
import asyncio
import imaplib
import threading
from email.parser import BytesParser
import pytest
from icloud_mcp.mail import NegativeIMAPResponse
from icloud_mcp.errors import ConnectorError
from .conftest import message_ref
from .test_smtp import send_args


def calls(c, name):
    return [x for x in c.fake_imap.calls if x[0] == name]


def reopen(make_connector, c):
    other = make_connector(state_dir=c.config.state_dir)
    other.mail.factory = lambda: c.fake_imap
    other.smtp.factory = lambda: c.fake_smtp
    other.fake_imap, other.fake_smtp = c.fake_imap, c.fake_smtp
    return other


def checkpoint_failure(c, monkeypatch, field, value):
    original = c.ledger.checkpoint
    def interrupted(op, checkpoint=None):
        if checkpoint and checkpoint.get(field) == value:
            raise ConnectorError('LEDGER_FAILURE', 'Synthetic interruption before checkpoint commit.')
        return original(op, checkpoint)
    monkeypatch.setattr(c.ledger, 'checkpoint', interrupted)


@pytest.mark.parametrize('tool', ['send_message', 'reply_message'])
async def test_send_and_reply_append_exact_mime_and_replay_without_duplicates(make_connector, tool):
    c = make_connector()
    args = send_args('exact-mime') if tool == 'send_message' else dict(
        operation_id='exact-mime', message_ref=await message_ref(c), text='Synthetic reply', html='<p>Synthetic</p>')
    result = await c.execute(tool, args)
    assert result['ok'] and result['result']['sent_copy']['exact_mime_verified']
    ref = c.ids.decode(result['result']['sent_copy']['message_ref'], 'message')
    assert c.fake_imap.boxes[ref['folder']][ref['uid']] == c.fake_smtp.raw
    assert not BytesParser().parsebytes(c.fake_smtp.raw)['Bcc']
    again = await c.execute(tool, args)
    assert again['replayed_local_result'] and c.fake_smtp.attempts == 1
    assert len(calls(c, 'append')) == 1


async def test_definitive_append_failure_can_recover_same_exact_mime_without_resending(make_connector, monkeypatch):
    c = make_connector(); args = send_args()
    append = c.fake_imap.append
    def rejected(*a, **k): raise NegativeIMAPResponse()
    monkeypatch.setattr(c.fake_imap, 'append', rejected)
    result = await c.execute('send_message', args)
    assert result['error']['code'] == 'SENT_COPY_FAILED'
    assert result['result']['smtp_accepted'] and result['result']['sent_copy']['status'] == 'failed'
    original = c.fake_smtp.raw
    monkeypatch.setattr(c.fake_imap, 'append', append)
    monkeypatch.setattr('icloud_mcp.smtp.formatdate', lambda **kw: 'Wed, 07 Oct 2026 01:02:03 GMT')
    other = reopen(make_connector, c)
    recovered = await other.execute('send_message', args)
    assert recovered['ok'] and c.fake_smtp.attempts == 1
    assert list(c.fake_imap.boxes['Sent Messages'].values()) == [original]


@pytest.mark.parametrize('completed', [True, False])
async def test_ambiguous_append_reconciles_only_and_never_blindly_reappends(make_connector, monkeypatch, completed):
    c = make_connector(); args = send_args(); append = c.fake_imap.append
    attempts = []
    def disconnected(*a, **k):
        attempts.append(1)
        if completed: append(*a, **k)
        raise imaplib.IMAP4.abort('PRIVATE connection ended')
    monkeypatch.setattr(c.fake_imap, 'append', disconnected)
    first = await c.execute('send_message', args)
    assert first['error']['code'] == 'MAIL_UNCERTAIN' and first['result']['smtp_accepted']
    other = reopen(make_connector, c)
    retry = await other.execute('send_message', args)
    assert retry['ok'] == completed
    if completed:
        assert retry['result']['sent_copy']['append_outcome'] == 'uncertain'
        assert not retry['result']['sent_folder_copy_created']
    if not completed: assert retry['error']['code'] == 'MAIL_UNCERTAIN'
    assert c.fake_smtp.attempts == 1 and len(attempts) == 1


@pytest.mark.parametrize('altered,duplicate', [(False, False), (True, False), (False, True)])
async def test_existing_provider_sent_copy_prevents_append(make_connector, monkeypatch, altered, duplicate):
    c = make_connector(); transmit = c.fake_smtp.sendmail
    async def automatic(sender, recipients, raw):
        reply = await transmit(sender, recipients, raw)
        c.fake_imap.boxes['Sent Messages'][1] = (b'X-Provider: synthetic\r\n'+raw) if altered else raw
        c.fake_imap.flagsets['Sent Messages'][1] = {b'\\Seen'}
        if duplicate:
            c.fake_imap.boxes['Sent Messages'][2] = raw
            c.fake_imap.flagsets['Sent Messages'][2] = set()
        return reply
    monkeypatch.setattr(c.fake_smtp, 'sendmail', automatic)
    r = await c.execute('send_message', send_args())
    assert r['ok'] == (not altered and not duplicate)
    if r['ok']: assert not r['result']['sent_folder_copy_created']
    else: assert r['error']['code'] == 'MAIL_UNCERTAIN' and r['result']['smtp_accepted']
    assert not calls(c, 'append') and c.fake_smtp.attempts == 1


@pytest.mark.parametrize('phase', ['smtp_started', 'smtp_accepted', 'append_accepted', 'sent_saved'])
async def test_send_checkpoint_interruptions_survive_reopen_without_second_transport(make_connector, monkeypatch, phase):
    c = make_connector(); args = send_args()
    field, value = {'smtp_started': ('smtp_status', 'started'), 'smtp_accepted': ('smtp_status', 'accepted'),
                    'append_accepted': ('sent_status', 'accepted'), 'sent_saved': ('sent_status', 'saved')}[phase]
    checkpoint_failure(c, monkeypatch, field, value)
    result = await c.execute('send_message', args)
    assert result['error']['code'] == 'LEDGER_FAILURE'
    before_smtp = c.fake_smtp.attempts; before_append = len(calls(c, 'append'))
    other = reopen(make_connector, c)
    recovered = await other.execute('send_message', args)
    if phase == 'smtp_accepted':
        assert recovered['error']['code'] == 'OPERATION_NOT_REPLAYABLE'
        assert before_smtp == c.fake_smtp.attempts == 1
    else:
        assert recovered['ok'], recovered
        assert c.fake_smtp.attempts == 1
    if before_append: assert len(calls(c, 'append')) == before_append


async def test_sent_uidvalidity_change_prohibits_append_after_accepted_smtp(make_connector, monkeypatch):
    c = make_connector(); transmit = c.fake_smtp.sendmail
    async def changed(*a):
        result = await transmit(*a); c.fake_imap.uv['Sent Messages'] += 1; return result
    monkeypatch.setattr(c.fake_smtp, 'sendmail', changed)
    r = await c.execute('send_message', send_args())
    assert r['error']['code'] == 'MAIL_UNCERTAIN' and r['result']['smtp_accepted']
    assert not calls(c, 'append')


async def test_sent_restriction_checked_before_smtp_and_custom_canonical_folder_used(make_connector):
    c = make_connector(folders=('INBOX',))
    r = await c.execute('send_message', send_args())
    assert r['error']['code'] == 'RESOURCE_DENIED' and c.fake_smtp.attempts == 0
    other = make_connector(sent_folder='Archive/Quoted "Folder"')
    r = await other.execute('send_message', send_args())
    assert r['ok'] and r['result']['sent_copy']['folder'] == 'Archive/Quoted "Folder"'


async def move_args(c, op='move-recovery'):
    return dict(operation_id=op, message_ref=await message_ref(c), destination_folder='INBOX')


async def test_uidplus_only_true_move_returns_new_ref_preserves_flags_and_unrelated_deleted(make_connector):
    c = make_connector(); c.fake_imap.capabilities = {'UIDPLUS'}; args = await move_args(c)
    c.fake_imap.flagsets['Archive/Quoted "Folder"'][42] = {b'\\Seen', b'\\Flagged', b'custom'}
    c.fake_imap.flagsets['Archive/Quoted "Folder"'][41] = {b'\\Deleted'}
    r = await c.execute('move_message', args)
    assert r['ok'] and r['result']['flags_preserved'] and r['result']['source_removed']
    new = c.ids.decode(r['result']['message_ref'], 'message')
    assert new['folder'] == 'INBOX' and new['uid'] != 42 and new['uidvalidity'] == 100
    assert c.fake_imap.flagsets['INBOX'][new['uid']] == {b'\\Seen', b'\\Flagged', b'custom'}
    assert 41 in c.fake_imap.boxes['Archive/Quoted "Folder"']
    assert calls(c, 'uid_expunge') == [('uid_expunge', [42])]
    assert not c.config.permanent_expunge and 'expunge_messages' not in {t.name for t in c.tools()}
    assert (await c.execute('fetch_message', {'message_ref':args['message_ref']}))['error']['code'] == 'MESSAGE_NOT_FOUND'
    replay = await c.execute('move_message', args)
    assert replay['replayed_local_result'] and len(calls(c, 'copy')) == 1


@pytest.mark.parametrize('capabilities', [set(), {'MOVE'}])
async def test_no_uidplus_rejected_before_any_copy_or_source_changes(make_connector, capabilities):
    c = make_connector(); c.fake_imap.capabilities = capabilities; args = await move_args(c)
    r = await c.execute('move_message', args)
    assert r['error']['code'] == 'UNSUPPORTED'
    assert not calls(c, 'copy') and not calls(c, 'add_flags') and not calls(c, 'uid_expunge')


@pytest.mark.parametrize('corruption', ['bytes', 'flags', 'destination_uv', 'source_uv'])
async def test_bad_destination_or_stale_mailbox_never_removes_source(make_connector, monkeypatch, corruption):
    c = make_connector(); args = await move_args(c); copy = c.fake_imap.copy
    def corrupt(uids, destination):
        response = copy(uids, destination)
        if corruption == 'bytes': c.fake_imap.boxes[destination][2] += b'corruption'
        if corruption == 'flags': c.fake_imap.flagsets[destination][2].add(b'\\Seen')
        if corruption == 'destination_uv': c.fake_imap.uv[destination] += 1
        if corruption == 'source_uv': c.fake_imap.uv['Archive/Quoted "Folder"'] += 1
        return response
    monkeypatch.setattr(c.fake_imap, 'copy', corrupt)
    r = await c.execute('move_message', args)
    assert r['error']['code'] == 'MAIL_UNCERTAIN'
    assert 42 in c.fake_imap.boxes['Archive/Quoted "Folder"']
    assert not calls(c, 'add_flags') and not calls(c, 'uid_expunge')


@pytest.mark.parametrize('completed', [True, False])
async def test_ambiguous_copy_recovers_without_duplicate_only_if_exact_new_copy_found(make_connector, monkeypatch, completed):
    c = make_connector(); args = await move_args(c); copy = c.fake_imap.copy; attempts = []
    def disconnected(*a):
        attempts.append(1)
        if completed: copy(*a)
        raise imaplib.IMAP4.abort('PRIVATE COPY disconnect')
    monkeypatch.setattr(c.fake_imap, 'copy', disconnected)
    first = await c.execute('move_message', args)
    assert first['error']['code'] == 'MAIL_UNCERTAIN' and 42 in c.fake_imap.boxes['Archive/Quoted "Folder"']
    other = reopen(make_connector, c)
    recovered = await other.execute('move_message', args)
    assert recovered['ok'] == completed
    assert len(attempts) == 1
    if not completed: assert not calls(c, 'uid_expunge')


@pytest.mark.parametrize('phase', ['copy_accepted', 'copy_verified', 'source_marked', 'source_removed'])
async def test_move_checkpoint_crash_recovery_preserves_copy_and_never_duplicates(make_connector, monkeypatch, phase):
    c = make_connector(); args = await move_args(c)
    field, value = {'copy_accepted': ('copy_status', 'accepted'), 'copy_verified': ('copy_status', 'verified'),
                    'source_marked': ('source_status', 'marked'), 'source_removed': ('source_status', 'removed')}[phase]
    checkpoint_failure(c, monkeypatch, field, value)
    first = await c.execute('move_message', args)
    assert first['error']['code'] == 'LEDGER_FAILURE'
    other = reopen(make_connector, c)
    recovered = await other.execute('move_message', args)
    assert recovered['ok'], recovered
    assert len(calls(c, 'copy')) == 1 and len(calls(c, 'uid_expunge')) == 1


@pytest.mark.parametrize('completed', [True, False])
async def test_ambiguous_targeted_expunge_is_never_repeated(make_connector, monkeypatch, completed):
    c = make_connector(); args = await move_args(c); expunge = c.fake_imap.uid_expunge; attempts = []
    def disconnected(*a):
        attempts.append(1)
        if completed: expunge(*a)
        raise imaplib.IMAP4.abort('PRIVATE expunge disconnect')
    monkeypatch.setattr(c.fake_imap, 'uid_expunge', disconnected)
    first = await c.execute('move_message', args)
    assert first['error']['code'] == 'MAIL_UNCERTAIN'
    other = reopen(make_connector, c)
    recovered = await other.execute('move_message', args)
    assert recovered['ok'] == completed and len(attempts) == 1 and len(calls(c, 'copy')) == 1


async def test_missing_copyuid_can_recover_by_bounded_new_uid_search_without_message_id(make_connector, monkeypatch):
    c = make_connector(); args = await move_args(c); copy = c.fake_imap.copy
    raw = c.fake_imap.boxes['Archive/Quoted "Folder"'][42]
    raw = raw.replace(b'Message-ID: <source@example.invalid>\n', b'')
    c.fake_imap.boxes['Archive/Quoted "Folder"'][42] = raw
    def no_mapping(*a): copy(*a); return b'COPY completed'
    monkeypatch.setattr(c.fake_imap, 'copy', no_mapping)
    assert (await c.execute('move_message', args))['ok']


async def test_account_workflow_lock_prevents_duplicate_concurrent_send_even_after_timeout(make_connector, monkeypatch):
    c = make_connector(timeout_seconds=1); other = reopen(make_connector, c); other.config = c.config
    release = threading.Event(); entered = threading.Event(); append = c.fake_imap.append
    def blocked(*a, **k): entered.set(); release.wait(3); return append(*a, **k)
    monkeypatch.setattr(c.fake_imap, 'append', blocked)
    args = send_args('concurrent')
    task = asyncio.create_task(c.execute('send_message', args))
    while not entered.is_set(): await asyncio.sleep(.01)
    concurrent = await other.execute('send_message', args)
    assert concurrent['error']['code'] == 'BUSY'
    timed_out = await task
    assert timed_out['error']['code'] == 'TIMEOUT'
    again = await other.execute('send_message', args)
    assert again['error']['code'] == 'BUSY'
    release.set(); await asyncio.sleep(.1)
    assert c.fake_smtp.attempts == 1 and len(calls(c, 'append')) == 1


async def test_recovery_id_conflicts_and_logs_omit_private_protocol_data(make_connector, monkeypatch, capsys):
    c = make_connector(); args = send_args()
    def failed(*a, **k): raise imaplib.IMAP4.abort('PRIVATE recipient and MIME')
    monkeypatch.setattr(c.fake_imap, 'append', failed)
    assert not (await c.execute('send_message', args))['ok']
    changed = await c.execute('send_message', dict(args, text='different'))
    assert changed['error']['code'] == 'OPERATION_ID_CONFLICT'
    assert c.fake_smtp.attempts == 1
    output = capsys.readouterr()
    assert not output.out and 'PRIVATE' not in output.err and 'Synthetic body' not in output.err
    status = c.ledger.status(args['operation_id'])
    assert 'recipe' not in status['mail_checkpoint'] and 'envelope' not in status['mail_checkpoint']


@pytest.mark.parametrize('command', ['copy', 'add_flags', 'uid_expunge'])
async def test_definitive_move_failures_recover_without_duplicate_copy(make_connector, monkeypatch, command):
    c = make_connector(); args = await move_args(c); original = getattr(c.fake_imap, command)
    def rejected(*a, **k): raise NegativeIMAPResponse()
    monkeypatch.setattr(c.fake_imap, command, rejected)
    first = await c.execute('move_message', args)
    assert first['error']['code'] == 'MOVE_INCOMPLETE'
    assert 42 in c.fake_imap.boxes['Archive/Quoted "Folder"']
    monkeypatch.setattr(c.fake_imap, command, original)
    other = reopen(make_connector, c)
    recovered = await other.execute('move_message', args)
    assert recovered['ok'] and len(calls(c, 'copy')) == 1 and len(calls(c, 'uid_expunge')) == 1


async def test_unknown_imap_parser_error_is_uncertain_not_an_append_retry(make_connector, monkeypatch):
    c = make_connector(); attempts = []
    def unknown(*a, **k):
        attempts.append(1)
        raise imaplib.IMAP4.error('PRIVATE parser failure')
    monkeypatch.setattr(c.fake_imap, 'append', unknown)
    first = await c.execute('send_message', send_args())
    assert first['error']['code'] == 'MAIL_UNCERTAIN'
    assert not (await c.execute('send_message', send_args()))['ok']
    assert len(attempts) == 1 and c.fake_smtp.attempts == 1


async def test_interrupted_copy_with_multiple_new_exact_matches_stops_before_source_removal(make_connector, monkeypatch):
    c = make_connector(); args = await move_args(c); copy = c.fake_imap.copy
    def duplicate(*a):
        copy(*a); copy(*a)
        raise imaplib.IMAP4.abort('PRIVATE lost response')
    monkeypatch.setattr(c.fake_imap, 'copy', duplicate)
    assert not (await c.execute('move_message', args))['ok']
    result = await reopen(make_connector, c).execute('move_message', args)
    assert result['error']['code'] == 'MAIL_UNCERTAIN'
    assert not calls(c, 'add_flags') and not calls(c, 'uid_expunge')


async def test_destination_verified_before_deleted_flag_and_expunge(make_connector, monkeypatch):
    c = make_connector(); args = await move_args(c); add = c.fake_imap.add_flags
    def assert_verified(uids, flags, **kw):
        assert c.ledger.checkpoint(args['operation_id'])['copy_status'] == 'verified'
        assert c.fake_imap.boxes['INBOX'][2] == c.fake_imap.boxes['Archive/Quoted "Folder"'][42]
        assert any(x[0]=='fetch' and x[2]==['BODY.PEEK[]'] for x in c.fake_imap.calls)
        return add(uids, flags, **kw)
    monkeypatch.setattr(c.fake_imap, 'add_flags', assert_verified)
    assert (await c.execute('move_message', args))['ok']


async def test_source_concurrent_flag_change_stops_without_mutating_or_claiming_success(make_connector, monkeypatch):
    c = make_connector(); args = await move_args(c); copy = c.fake_imap.copy
    def concurrent(*a):
        result = copy(*a)
        c.fake_imap.flagsets['Archive/Quoted "Folder"'][42].add(b'\\Flagged')
        return result
    monkeypatch.setattr(c.fake_imap, 'copy', concurrent)
    result = await c.execute('move_message', args)
    assert result['error']['code'] == 'MAIL_CONFLICT'
    assert not calls(c, 'add_flags') and not calls(c, 'uid_expunge')
    assert 42 in c.fake_imap.boxes['Archive/Quoted "Folder"'] and 2 in c.fake_imap.boxes['INBOX']


async def test_copy_finishing_after_timeout_does_not_continue_into_source_removal(make_connector, monkeypatch):
    c = make_connector(timeout_seconds=1); args = await move_args(c)
    copy = c.fake_imap.copy; release = threading.Event(); entered = threading.Event()
    def blocked(*a): entered.set(); release.wait(3); return copy(*a)
    monkeypatch.setattr(c.fake_imap, 'copy', blocked)
    task = asyncio.create_task(c.execute('move_message', args))
    while not entered.is_set(): await asyncio.sleep(.01)
    assert (await task)['error']['code'] == 'TIMEOUT'
    release.set(); await asyncio.sleep(.1)
    assert not calls(c, 'add_flags') and not calls(c, 'uid_expunge')
    assert c.ledger.status(args['operation_id'])['state'] == 'ambiguous'
    assert 42 in c.fake_imap.boxes['Archive/Quoted "Folder"']


async def test_round_trip_move_uses_new_uid_references_and_preserves_flags(make_connector):
    c = make_connector(); c.fake_imap.capabilities = {'UIDPLUS'}; args = await move_args(c)
    c.fake_imap.flagsets['Archive/Quoted "Folder"'][42] = {b'\\Seen', b'\\Answered'}
    original = c.fake_imap.boxes['Archive/Quoted "Folder"'][42]
    first = await c.execute('move_message', args)
    back = await c.execute('move_message', dict(operation_id='move-back',
        message_ref=first['result']['message_ref'], destination_folder='Archive/Quoted "Folder"'))
    assert back['ok']
    restored = c.ids.decode(back['result']['message_ref'], 'message')
    assert restored['uid'] != 42
    assert c.fake_imap.boxes[restored['folder']][restored['uid']] == original
    assert c.fake_imap.flagsets[restored['folder']][restored['uid']] == {b'\\Seen', b'\\Answered'}


async def test_smtp_cleanup_failure_does_not_lose_acceptance_or_trigger_resend(make_connector, monkeypatch):
    c = make_connector()
    def close_failed(): raise OSError('PRIVATE socket cleanup')
    monkeypatch.setattr(c.fake_smtp, 'close', close_failed)
    result = await c.execute('send_message', send_args())
    assert result['ok'] and result['result']['smtp_accepted'] and result['result']['sent_copy']['status'] == 'saved'
    assert c.fake_smtp.attempts == 1 and len(calls(c, 'append')) == 1
