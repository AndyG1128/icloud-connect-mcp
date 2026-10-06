import base64
import json
import pytest
from .conftest import message_ref


@pytest.mark.parametrize('reject_login', [False, True])
def test_imap_uses_mail_identity_without_apple_account_fallback(tmp_path, monkeypatch, reject_login):
    from icloud_mcp.config import Config
    from icloud_mcp.mail import Mail
    from unittest.mock import Mock
    import imaplib

    secret = tmp_path / 'password'
    secret.write_text('synthetic-test-password')
    secret.chmod(0o600)
    config = Config(account_email='synthetic@icloud.com', username='apple-account@outlook.com',
                    password_file=str(secret))
    client = Mock()
    if reject_login:
        client.login.side_effect = imaplib.IMAP4.error('synthetic rejection')
    constructor = Mock(return_value=client)
    monkeypatch.setattr('icloud_mcp.mail.IMAPClient', constructor)
    mail = Mail(config, None, None)
    if reject_login:
        with pytest.raises(imaplib.IMAP4.error):
            with mail.connection():
                pytest.fail('Rejected authentication must not yield a connection.')
        client.shutdown.assert_called_once_with()
        client.logout.assert_not_called()
    else:
        with mail.connection() as actual:
            assert actual is client
        client.logout.assert_called_once_with()
    constructor.assert_called_once_with('imap.mail.me.com', ssl=True, use_uid=True,
                                        timeout=config.timeout_seconds)
    client.login.assert_called_once_with('synthetic@icloud.com', 'synthetic-test-password')


@pytest.mark.parametrize('wire_readonly', [True, False])
def test_examine_mode_checked_despite_icloud_read_write_marker(make_connector, wire_readonly):
    from types import SimpleNamespace
    from icloud_mcp.errors import ConnectorError
    c = make_connector(profile='read-only')
    client = c.fake_imap
    client._imap = SimpleNamespace(is_readonly=wire_readonly)
    select = client.select_folder
    def response(folder, readonly=False):
        result = select(folder, readonly=readonly)
        return result | {b'READ-WRITE': True}
    client.select_folder = response
    if wire_readonly:
        assert c.mail.select(client, 'INBOX') == ('INBOX', 100)
    else:
        with pytest.raises(ConnectorError, match='READ_ONLY_REQUIRED'):
            c.mail.select(client, 'INBOX')
    assert client.calls[-1] == ('select', 'INBOX', True)


async def collect(c,ref,section,limit=8000):
    offset=0;data='';digest=None
    while True:
        result=await c.execute('fetch_message',dict(message_ref=ref,section=section,offset=offset,limit=limit))
        assert result['ok'],result
        page=result['result'];assert len(page['untrusted_data'])<=limit
        assert page['source_sha256']==(digest or page['source_sha256'])
        digest=page['source_sha256'];data+=page['untrusted_data']
        if page['next_offset'] is None:break
        assert not page['section_complete_in_this_page']
        offset=page['next_offset']
    return json.loads(data)


async def test_non_inbox_identity_literal_keyword_and_peek(make_connector):
    c=make_connector(profile='read-only');ref=await message_ref(c)
    obj=c.ids.decode(ref,'message')
    assert obj['folder']=='Archive/Quoted "Folder"' and obj['uidvalidity']==101 and obj['uid']==42
    text=await collect(c,ref,'text')
    assert text[0]['content'].count('Synthetic body needle.')==3000
    assert all(call[2] is True for call in c.fake_imap.calls if call[0]=='select')
    assert all(call[2] is None for call in c.fake_imap.calls if call[0]=='search')
    assert any(call[2]==['BODY.PEEK[]'] for call in c.fake_imap.calls if call[0]=='fetch')
    assert not c.fake_imap.flagsets[obj['folder']][obj['uid']]


async def test_headers_html_and_attachment_are_complete(make_connector):
    c=make_connector();ref=await message_ref(c)
    headers=await collect(c,ref,'headers')
    assert [v for k,v in headers['headers'] if k=='X-Repeated']==['first','second']
    assert b'X-Repeated: first' in base64.b64decode(headers['wire_headers_base64'])
    html=await collect(c,ref,'html');assert html[0]['content'].count('<p>Synthetic HTML</p>')==2000
    assert base64.b64decode(html[0]['raw_content_base64']).count(b'<p>Synthetic HTML</p>')==2000
    attachments=await collect(c,ref,'attachments');assert len(attachments)==1
    offset=0;data=b''
    while True:
        r=await c.execute('fetch_attachment',dict(attachment_ref=attachments[0]['attachment_ref'],offset=offset,limit=1000))
        assert r['ok'],r
        page=r['result'];data+=base64.b64decode(page['untrusted_data_base64'])
        if page['next_offset'] is None:break
        offset=page['next_offset']
    assert data==b'synthetic attachment bytes'*100


async def test_uidvalidity_change_rejects_stale_reference(make_connector):
    c=make_connector();ref=await message_ref(c);c.fake_imap.uv['Archive/Quoted "Folder"']+=1
    assert (await c.execute('fetch_message',{'message_ref':ref}))['error']['code']=='STALE_REFERENCE'
    assert not any(x[0]=='fetch' and x[2]==['BODY.PEEK[]'] for x in c.fake_imap.calls)


async def test_foreign_account_and_tampering_rejected(make_connector):
    c=make_connector();ref=await message_ref(c)
    other=make_connector(account_email='other@example.invalid')
    for bad in (ref[:-5]+'AAAAA',ref):
        assert (await other.execute('fetch_message',{'message_ref':bad}))['error']['code']=='INVALID_REFERENCE'
    assert not other.fake_imap.calls


async def test_read_detects_concurrent_flag_change_without_mutating(make_connector):
    c=make_connector();ref=await message_ref(c);c.fake_imap.mutate_on_peek=True
    assert (await c.execute('fetch_message',{'message_ref':ref}))['error']['code']=='FLAGS_CHANGED'
    assert c.fake_imap.flagsets['Archive/Quoted "Folder"'][42]=={b'\\Seen'}


async def test_message_limit_is_error_not_full_preview(make_connector):
    c=make_connector(max_message_bytes=1024);ref=await message_ref(c)
    assert (await c.execute('fetch_message',{'message_ref':ref}))['error']['code']=='MESSAGE_TOO_LARGE'
    assert not any(x[0]=='fetch' and x[2]==['BODY.PEEK[]'] for x in c.fake_imap.calls)


async def test_move_flags_and_targeted_expunge(make_connector):
    c=make_connector(permanent_expunge=True);ref=await message_ref(c)
    r=await c.execute('set_message_read',dict(operation_id='seen',message_ref=ref,read=True));assert r['ok'],r
    assert c.fake_imap.flagsets['Archive/Quoted "Folder"'][42]=={b'\\Seen'}
    r=await c.execute('set_message_read',dict(operation_id='unseen',message_ref=ref,read=False));assert r['ok']
    r=await c.execute('move_message',dict(operation_id='move',message_ref=ref,destination_folder='INBOX'));assert r['ok'],r
    assert (await c.execute('fetch_message',{'message_ref':ref}))['error']['code']=='MESSAGE_NOT_FOUND'
    newref=await message_ref(c,'INBOX');obj=c.ids.decode(newref,'message')
    c.fake_imap.flagsets['INBOX'][obj['uid']].add(b'\\Deleted')
    c.fake_imap.flagsets['INBOX'][1].add(b'\\Deleted')
    r=await c.execute('expunge_messages',dict(operation_id='expunge',message_refs=[newref]));assert r['ok'],r
    assert 1 in c.fake_imap.boxes['INBOX']  # Unrelated Deleted message survives.


async def test_unsafe_move_and_expunge_fallbacks_prohibited(make_connector):
    c=make_connector(permanent_expunge=True);ref=await message_ref(c);c.fake_imap.capabilities.clear()
    r=await c.execute('move_message',dict(operation_id='no-move',message_ref=ref,destination_folder='INBOX'))
    assert r['error']['code']=='UNSUPPORTED'
    c.fake_imap.flagsets['Archive/Quoted "Folder"'][42].add(b'\\Deleted')
    r=await c.execute('expunge_messages',dict(operation_id='no-expunge',message_refs=[ref]))
    assert r['error']['code']=='UNSUPPORTED'
    assert not any(x[0] in ('move','uid_expunge') for x in c.fake_imap.calls)


async def test_search_and_folder_pagination(make_connector):
    c=make_connector()
    r=await c.execute('list_mail_folders',{'limit':1});assert r['result']['next_offset']==1
    r=await c.execute('search_messages',{'folder':'INBOX','query':'no-such-text'})
    assert r['result']['total']==0
    r=await c.execute('search_messages',{'folder':'Archive/Quoted "Folder"','limit':1})
    assert r['result']['next_offset']==1


async def test_embedded_message_attachment_is_discoverable_and_retrievable(make_connector):
    c=make_connector()
    from email.message import EmailMessage
    msg=EmailMessage();msg['From']='sender@example.invalid';msg.set_content('Synthetic outer')
    attached=EmailMessage();attached['Subject']='Synthetic embedded';attached.set_content('Synthetic inner')
    msg.add_attachment(attached,filename='embedded.eml')
    c.fake_imap.boxes['INBOX'][1]=msg.as_bytes()
    ref=await message_ref(c,'INBOX') if b'needle' in msg.as_bytes() else c.ids.issue('message',folder='INBOX',uidvalidity=100,uid=1)
    attachments=await collect(c,ref,'attachments')
    assert len(attachments)==1 and attachments[0]['content_type']=='message/rfc822'
    r=await c.execute('fetch_attachment',{'attachment_ref':attachments[0]['attachment_ref']})
    assert r['ok'] and b'Synthetic embedded' in base64.b64decode(r['result']['untrusted_data_base64'])
