from email import policy
from email.parser import BytesParser
import pytest
from .conftest import message_ref


def send_args(op='send-1'):
    return dict(operation_id=op,to=['recipient@example.invalid'],subject='Synthetic subject',text='Synthetic body',html='<p>Synthetic</p>',bcc=['hidden@example.invalid'])


async def test_smtp_authenticates_mail_address_separately_from_apple_account(make_connector, monkeypatch):
    from unittest.mock import AsyncMock
    c = make_connector(account_email='synthetic@icloud.com', username='apple-account@outlook.com')
    login = AsyncMock()
    monkeypatch.setattr(c.fake_smtp, 'login', login)
    result = await c.execute('send_message', send_args('synthetic-mail-identity'))
    assert result['ok']
    login.assert_awaited_once_with('synthetic@icloud.com', 'synthetic')


async def test_smtp_acceptance_and_identical_replay_without_resend(make_connector):
    c=make_connector();args=send_args()
    result=await c.execute('send_message',args);assert result['ok'],result
    assert result['result']['smtp_accepted'] and not result['result']['delivery_confirmed']
    msg=BytesParser(policy=policy.default).parsebytes(c.fake_smtp.raw)
    assert msg['From']=='owner@example.invalid' and not msg['Bcc'] and msg.is_multipart()
    assert 'hidden@example.invalid' in c.fake_smtp.recipients
    again=await c.execute('send_message',args)
    assert again['replayed_local_result'] and c.fake_smtp.attempts==1
    changed=await c.execute('send_message',dict(args,text='different'))
    assert changed['error']['code']=='OPERATION_ID_CONFLICT' and c.fake_smtp.attempts==1


async def test_ambiguous_data_outcome_persisted_never_resent(make_connector):
    c=make_connector();c.fake_smtp.mode='ambiguous';args=send_args()
    result=await c.execute('send_message',args);assert result['error']['code']=='SMTP_AMBIGUOUS'
    state=await c.execute('get_operation_status',{'operation_id':'send-1'})
    assert state['result']['state']=='ambiguous' and state['result']['result']['message_id']
    assert (await c.execute('send_message',args))['error']['code']=='OPERATION_NOT_REPLAYABLE'
    assert c.fake_smtp.attempts==1
    from icloud_mcp.operation_store import OperationStore
    reopened=OperationStore(c.config.state_dir,c.ids.key,c.ids.account)
    assert reopened.status('send-1')['state']=='ambiguous';reopened.db.close()


@pytest.mark.parametrize('mode,code',[('connect_failure','SMTP_NOT_SENT'),('rejected','SMTP_REJECTED')])
async def test_known_failure_not_ambiguous_and_not_automatically_retried(make_connector,mode,code):
    c=make_connector();c.fake_smtp.mode=mode
    r=await c.execute('send_message',send_args());assert r['error']['code']==code
    assert c.ledger.status('send-1')['state']=='failed'
    assert (await c.execute('send_message',send_args()))['error']['code']=='OPERATION_NOT_REPLAYABLE'


async def test_partial_acceptance_not_resubmitted(make_connector):
    c=make_connector();c.fake_smtp.mode='partial'
    r=await c.execute('send_message',send_args());assert r['ok']
    assert r['result']['accepted_recipient_count']==1 and r['result']['rejected_recipient_count']==1


async def test_reply_preserves_thread_and_uses_reply_to(make_connector):
    c=make_connector();ref=await message_ref(c)
    r=await c.execute('reply_message',dict(operation_id='reply-1',message_ref=ref,text='Synthetic reply'))
    assert r['ok'],r
    msg=BytesParser(policy=policy.default).parsebytes(c.fake_smtp.raw)
    assert msg['To']=='reply@example.invalid'
    assert msg['In-Reply-To']=='<source@example.invalid>' and '<source@example.invalid>' in msg['References']
    assert not c.fake_imap.flagsets['Archive/Quoted "Folder"'][42]


@pytest.mark.parametrize('change',[{'subject':'header\r\nBcc: injected@example.invalid'}, {'to':['invalid\n@example.invalid']}])
async def test_header_injection_rejected_before_smtp(make_connector,change):
    c=make_connector();r=await c.execute('send_message',dict(send_args(),**change))
    assert not r['ok'] and c.fake_smtp.attempts==0


async def test_ledger_stores_no_body_or_credentials(make_connector):
    c=make_connector();await c.execute('send_message',send_args())
    from pathlib import Path
    data=c.ledger.path.read_bytes()
    assert b'Synthetic body' not in data and b'password' not in data


async def test_ledger_failure_after_acceptance_cannot_trigger_resend(make_connector):
    c=make_connector()
    def failure(*args):raise OSError('PRIVATE filesystem context')
    c.ledger.finish=failure
    result=await c.execute('send_message',send_args())
    assert result['error']['code']=='LEDGER_FAILURE' and c.fake_smtp.attempts==1
    assert c.ledger.status('send-1')['state']=='in_progress'
    # Reconcile confirmed acceptance/copy without repeating either transport.
    assert (await c.execute('send_message',send_args()))['error']['code']=='LEDGER_FAILURE'
    assert c.fake_smtp.attempts == 1
    assert len([call for call in c.fake_imap.calls if call[0]=='append']) == 1


@pytest.mark.parametrize('reply_all', [False, True])
async def test_reply_to_self_keeps_primary_recipient_and_threading(make_connector, reply_all):
    c = make_connector()
    _, _, raw = c.smtp.build('synthetic-self-source', [c.config.account_email],
                            'Synthetic self test', 'Synthetic self message')
    c.fake_imap.boxes['INBOX'][1] = raw
    ref = c.ids.issue('message', folder='INBOX', uidvalidity=100, uid=1)
    result = await c.execute('reply_message', dict(operation_id='synthetic-self-reply',
        message_ref=ref, text='Synthetic self reply', reply_all=reply_all))
    assert result['ok'], result
    sent = BytesParser(policy=policy.default).parsebytes(c.fake_smtp.raw)
    source = BytesParser(policy=policy.default).parsebytes(raw)
    assert sent['To'] == c.config.account_email
    assert c.fake_smtp.recipients == [c.config.account_email]
    assert sent['In-Reply-To'] == source['Message-ID']
    assert source['Message-ID'] in sent['References']
    assert not c.fake_imap.flagsets['INBOX'][1]
