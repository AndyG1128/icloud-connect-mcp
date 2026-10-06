"""Strict Sent-only exception and evidence-based, read-only reconciliation."""
import hashlib
import json
import imaplib
import sqlite3
import pytest
from icloud_mcp.errors import ConnectorError
from .test_smtp import send_args
from .conftest import message_ref
from .test_mail_recovery import reopen, calls


def variant(raw, difference):
    if difference == 'exact': return raw
    if difference == 'one_crlf': return raw+b'\r\n'
    if difference == 'two_crlfs': return raw+b'\r\n\r\n'
    if difference == 'missing_byte': return raw[:-1]
    if difference == 'header': return raw.replace(b'Subject: Synthetic subject',b'Subject: Synthetic altered')
    if difference == 'body': return raw.replace(b'Synthetic body',b'Synthetic changed body')
    if difference == 'line_endings': return raw.replace(b'\r\n',b'\n')
    if difference == 'space': return raw+b' '
    if difference == 'leading_crlf': return b'\r\n'+raw
    raise AssertionError(difference)


@pytest.mark.parametrize('difference', ['exact','one_crlf','two_crlfs','missing_byte','header','body','line_endings','space','leading_crlf'])
async def test_only_exact_or_precisely_one_extra_trailing_crlf_passes(make_connector, monkeypatch, difference):
    c=make_connector(); append=c.fake_imap.append
    def transformed(folder,raw,**kw):return append(folder,variant(raw,difference),**kw)
    monkeypatch.setattr(c.fake_imap,'append',transformed)
    result=await c.execute('send_message',send_args())
    allowed=difference in ('exact','one_crlf')
    assert result['ok']==allowed
    assert c.fake_smtp.attempts==1 and len(calls(c,'append'))==1
    if allowed:
        copy=result['result']['sent_copy']
        assert copy['mime_verified'] and copy['exact_mime_verified']==(difference=='exact')
        assert copy['trailing_crlf_exception_used']==(difference=='one_crlf')
        assert copy['submitted_sha256']==hashlib.sha256(c.fake_smtp.raw).hexdigest()
        assert copy['stored_sha256']==hashlib.sha256(variant(c.fake_smtp.raw,difference)).hexdigest()
        cp=c.ledger.checkpoint('send-1')
        assert cp['raw_hash']==copy['submitted_sha256'] and cp['sent_verification']['stored_sha256']==copy['stored_sha256']
        replay=await c.execute('send_message',send_args())
        assert replay['replayed_local_result'] and len(calls(c,'append'))==1 and c.fake_smtp.attempts==1
    else:
        assert result['error']['code']=='MAIL_UNCERTAIN'
        assert not (await c.execute('send_message',send_args()))['ok']
        assert c.fake_smtp.attempts==1 and len(calls(c,'append'))==1


async def original_failed_copy(c,monkeypatch):
    append=c.fake_imap.append
    def wrong(folder,raw,**kw):return append(folder,raw+b'\r\n\r\n',**kw)
    monkeypatch.setattr(c.fake_imap,'append',wrong)
    args=send_args();r=await c.execute('send_message',args)
    assert r['error']['code']=='MAIL_UNCERTAIN'
    previous=c.ledger.status('send-1');assert previous['state']=='ambiguous'
    return args,previous


async def test_readonly_reconciliation_retains_original_failure_and_dual_hashes(make_connector,monkeypatch):
    c=make_connector();args,previous=await original_failed_copy(c,monkeypatch)
    c.fake_imap.boxes['Sent Messages'][1]=c.fake_smtp.raw+b'\r\n'
    def forbidden(*a,**k):raise AssertionError('No SMTP or APPEND is allowed in reconciliation')
    monkeypatch.setattr(c.fake_imap,'append',forbidden)
    monkeypatch.setattr(c.smtp,'transmit',forbidden)
    result=await c.blocking(c.mail_operations.reconcile_sent,tool='send_message',arguments=args)
    assert result['smtp_accepted'] and result['sent_copy']['trailing_crlf_exception_used']
    status=c.ledger.status('send-1')
    assert status['state']=='succeeded' and status['sent_reconciliation_history_total']==1
    entry=status['sent_reconciliation_history'][0]
    assert entry['previous_state']=='ambiguous' and entry['previous_result']==previous['result']
    assert entry['evidence']['matching_copies']==1 and entry['evidence']['smtp_sends']==entry['evidence']['appends']==0
    assert entry['evidence']['submitted_sha256']==previous['mail_checkpoint']['raw_hash']
    assert entry['evidence']['stored_sha256']==hashlib.sha256(c.fake_smtp.raw+b'\r\n').hexdigest()
    other=reopen(make_connector,c)
    replay=await other.execute('send_message',args)
    assert replay['replayed_local_result'] and c.fake_smtp.attempts==1 and len(calls(c,'append'))==1


@pytest.mark.parametrize('problem',['missing','conflicting','two_copies','stale','changed_inputs'])
async def test_missing_or_conflicting_reconciliation_evidence_never_changes_ledger(make_connector,monkeypatch,problem):
    c=make_connector();args,previous=await original_failed_copy(c,monkeypatch)
    before_cp=c.ledger.checkpoint('send-1')
    if problem=='missing':c.fake_imap.boxes['Sent Messages'].clear()
    if problem=='conflicting':c.fake_imap.boxes['Sent Messages'][1]=variant(c.fake_smtp.raw,'body')
    if problem=='two_copies':
        c.fake_imap.boxes['Sent Messages']={1:c.fake_smtp.raw,2:c.fake_smtp.raw+b'\r\n'}
        c.fake_imap.flagsets['Sent Messages'][2]=set()
    if problem=='stale':c.fake_imap.uv['Sent Messages']+=1
    if problem=='changed_inputs':args=dict(args,text='changed')
    with pytest.raises(ConnectorError):
        await c.blocking(c.mail_operations.reconcile_sent,tool='send_message',arguments=args)
    assert c.ledger.status('send-1')==previous and c.ledger.checkpoint('send-1')==before_cp
    assert c.fake_smtp.attempts==1 and len(calls(c,'append'))==1


async def test_reconciliation_checkpoint_history_and_result_commit_atomically(make_connector,monkeypatch):
    c=make_connector();args,previous=await original_failed_copy(c,monkeypatch)
    before_cp=c.ledger.checkpoint('send-1');c.fake_imap.boxes['Sent Messages'][1]=c.fake_smtp.raw
    def deny_update(action,arg1,arg2,*rest):
        return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_UPDATE and arg1=='operations' else sqlite3.SQLITE_OK
    c.ledger.db.set_authorizer(deny_update)
    with pytest.raises(ConnectorError,match='LEDGER_FAILURE'):
        await c.blocking(c.mail_operations.reconcile_sent,tool='send_message',arguments=args)
    c.ledger.db.set_authorizer(None)
    assert c.ledger.status('send-1')==previous and c.ledger.checkpoint('send-1')==before_cp
    assert c.fake_smtp.attempts==1 and len(calls(c,'append'))==1


@pytest.mark.parametrize('completed',[True,False])
async def test_lost_append_response_with_extra_crlf_is_never_repeated(make_connector,monkeypatch,completed):
    c=make_connector();append=c.fake_imap.append;attempts=[]
    def uncertain(folder,raw,**kw):
        attempts.append(1)
        if completed:append(folder,raw+b'\r\n',**kw)
        raise imaplib.IMAP4.abort('synthetic lost APPEND response')
    monkeypatch.setattr(c.fake_imap,'append',uncertain)
    first=await c.execute('send_message',send_args());assert first['error']['code']=='MAIL_UNCERTAIN'
    recovered=await reopen(make_connector,c).execute('send_message',send_args())
    assert recovered['ok']==completed
    if completed:assert recovered['result']['sent_copy']['trailing_crlf_exception_used']
    assert len(attempts)==1 and c.fake_smtp.attempts==1


async def test_sent_exception_does_not_relax_move_copy_bytes(make_connector,monkeypatch):
    c=make_connector();copy=c.fake_imap.copy
    def altered(uids,destination):
        response=copy(uids,destination)
        uid=max(c.fake_imap.boxes[destination]);c.fake_imap.boxes[destination][uid]+=b'\r\n'
        return response
    monkeypatch.setattr(c.fake_imap,'copy',altered)
    r=await c.execute('move_message',dict(operation_id='strict-move',message_ref=await message_ref(c),destination_folder='INBOX'))
    assert r['error']['code']=='MAIL_UNCERTAIN' and 42 in c.fake_imap.boxes['Archive/Quoted "Folder"']
    assert not calls(c,'add_flags') and not calls(c,'uid_expunge')
