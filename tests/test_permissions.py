import pytest
from icloud_mcp.permissions import READ, WRITE
from .conftest import message_ref, calendar_ref


@pytest.mark.parametrize('tool', sorted(WRITE))
async def test_readonly_hides_and_denies_every_write(make_connector,tool):
    c=make_connector(profile='read-only',permissions=tuple(READ|WRITE),permanent_expunge=True)
    assert tool not in {t.name for t in c.tools()}
    result=await c.execute(tool,{})
    assert result['error']['code']=='PERMISSION_DENIED'
    assert not c.fake_imap.calls and not c.fake_dav.calls and c.fake_smtp.attempts==0


def test_full_profile_and_expunge_are_operator_only(make_connector):
    c=make_connector()
    assert {t.name for t in c.tools()}==READ|(WRITE-{'expunge_messages'})
    assert {t.name for t in make_connector(permanent_expunge=True).tools()}==READ|WRITE
    for t in c.tools():
        assert t.annotations.readOnlyHint==(t.name in READ)
        assert t.annotations.destructiveHint==(t.name in WRITE)
        assert 'profile' not in t.inputSchema['properties']


async def test_granular_permission_and_resource_restrictions(make_connector):
    c=make_connector(permissions=('connector_ping','list_mail_folders','search_messages'),folders=('INBOX',))
    assert {t.name for t in c.tools()}=={'connector_ping','list_mail_folders','search_messages'}
    assert (await c.execute('search_messages',{'folder':'Archive/Quoted "Folder"'}))['error']['code']=='RESOURCE_DENIED'
    assert not c.fake_imap.calls
    result=await c.execute('list_mail_folders',{})
    assert [x['folder'] for x in result['result']['folders']]==['INBOX']


async def test_signed_references_do_not_bypass_current_acl(make_connector):
    c=make_connector();ref=await message_ref(c)
    c.mail.permissions.config=type('Restricted',(),{'folders':('INBOX',)})()
    assert (await c.execute('fetch_message',{'message_ref':ref}))['error']['code']=='RESOURCE_DENIED'


async def test_calendar_allowlist_checked_on_discovery_and_reference(make_connector):
    c=make_connector();ref=await calendar_ref(c)
    c.calendars.permissions.config=type('Restricted',(),{'calendars':()})()
    result=await c.execute('get_events',{'calendar_ref':ref,'start':'2026-03-07','end':'2026-03-12'})
    assert result['error']['code']=='RESOURCE_DENIED'


@pytest.mark.parametrize('args',[{'folder':'INBOX','limit':0},{'folder':'INBOX','limit':1001},
                                {'folder':'INBOX','offset':-1},{'folder':'INBOX','profile':'full-access'}])
async def test_bounded_schema_rejects_invalid_arguments(make_connector,args):
    c=make_connector()
    assert (await c.execute('search_messages',args))['error']['code']=='INVALID_INPUT'
    assert not c.fake_imap.calls
