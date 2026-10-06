import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from icloud_mcp.calendars import guarded
from icloud_mcp.config import Config
from icloud_mcp.errors import ConnectorError
from icloud_mcp.operation_store import OperationStore
from .conftest import message_ref,calendar_ref,event_ref
from .test_smtp import send_args


async def test_blocking_imap_does_not_block_event_loop(make_connector):
    c=make_connector()
    original=c.fake_imap.list_folders
    def slow():time.sleep(.08);return original()
    c.fake_imap.list_folders=slow
    task=asyncio.create_task(c.execute('list_mail_folders',{}))
    ticks=0
    while not task.done():await asyncio.sleep(.01);ticks+=1
    assert (await task)['ok'] and ticks>=4


async def test_timeout_retains_slots_and_ambiguous_write(make_connector):
    c=make_connector(timeout_seconds=1);ref=await message_ref(c)
    release=threading.Event();original=c.fake_imap.add_flags
    def blocked(*args,**kwargs):release.wait(2);return original(*args,**kwargs)
    c.fake_imap.add_flags=blocked
    args=dict(operation_id='timeout-write',message_ref=ref,read=True)
    result=await c.execute('set_message_read',args)
    assert result['error']['code']=='TIMEOUT'
    assert c.ledger.status('timeout-write')['state']=='ambiguous'
    assert c.semaphore._value==1
    release.set();await asyncio.sleep(.05)
    assert c.semaphore._value==2
    assert (await c.execute('set_message_read',args))['error']['code']=='OPERATION_NOT_REPLAYABLE'


def test_crashed_in_progress_operation_not_replayed(tmp_path):
    key=b'a'*32;store=OperationStore(str(tmp_path/'ledger'),key)
    assert store.begin('crash','send_message',{'text':'synthetic'}) is None
    store.db.close();store=OperationStore(str(tmp_path/'ledger'),key)
    assert store.status('crash')['state']=='in_progress'
    with pytest.raises(ConnectorError,match='OPERATION_NOT_REPLAYABLE'):store.begin('crash','send_message',{'text':'synthetic'})
    with pytest.raises(ConnectorError,match='OPERATION_ID_CONFLICT'):store.begin('crash','send_message',{'text':'different'})
    store.db.close()


async def test_ledger_separates_accounts_even_when_state_is_shared(make_connector):
    c=make_connector();await c.execute('send_message',send_args())
    other=make_connector(state_dir=c.config.state_dir,account_email='second@example.invalid')
    r=await other.execute('get_operation_status',{'operation_id':'send-1'})
    assert r['error']['code']=='OPERATION_NOT_FOUND'


async def test_logs_and_errors_do_not_expose_upstream_text(make_connector,capsys):
    c=make_connector();c.fake_smtp.mode='ambiguous'
    r=await c.execute('send_message',send_args())
    assert 'PRIVATE' not in str(r)
    captured=capsys.readouterr();assert captured.out=='' and 'PRIVATE' not in captured.err
    assert 'Synthetic body' not in captured.err and 'recipient@example.invalid' not in captured.err


def test_private_credentials_and_symlinks(tmp_path):
    password=tmp_path/'password';password.write_text('synthetic-app-password');password.chmod(0o600)
    c=Config(account_email='owner@example.invalid',username='owner@example.invalid',password_file=str(password))
    assert c.password()=='synthetic-app-password'
    password.chmod(0o644)
    with pytest.raises(ConnectorError,match='CREDENTIALS'):c.password()
    password.chmod(0o600);link=tmp_path/'link';link.symlink_to(password)
    with pytest.raises(ConnectorError,match='CREDENTIALS'):Config(account_email=c.account_email,username=c.username,password_file=str(link)).password()


def test_operator_profile_config_not_writable_by_other_users(tmp_path):
    from icloud_mcp.config import load_config
    config=tmp_path/'config.toml';config.write_text('profile="read-only"\n');config.chmod(0o664)
    with pytest.raises(ConnectorError,match='CONFIG'):load_config(str(config))
    config.chmod(0o600);assert load_config(str(config)).profile=='read-only'


def test_guarded_caldav_redirects_do_not_leak_credentials():
    calls=[]
    def raw(method,url,**kwargs):
        calls.append((method,url,kwargs))
        return SimpleNamespace(status_code=302,headers={'Location':'https://attacker.example.invalid/steal'})
    client=SimpleNamespace(session=SimpleNamespace(request=raw),timeout=10)
    guarded(client,time.monotonic()+10)
    with pytest.raises(ConnectorError,match='INVALID_RESOURCE'):client.session.request('GET','https://caldav.icloud.com/')
    assert len(calls)==1 and calls[0][2]['allow_redirects'] is False
    with pytest.raises(ConnectorError,match='WRITE_REDIRECT'):client.session.request('PUT','https://caldav.icloud.com/event.ics')


async def test_unconfigured_account_never_falls_back(make_connector,monkeypatch):
    c=make_connector(account_email='',username='')
    c.mail.factory=None
    # Validate before opening a socket, not after logging into an unintended account.
    def forbidden(*args,**kwargs):raise AssertionError('Network connection was attempted')
    monkeypatch.setattr('icloud_mcp.mail.IMAPClient',forbidden)
    assert (await c.execute('list_mail_folders',{}))['error']['code']=='NOT_CONFIGURED'
