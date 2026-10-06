from pathlib import Path
import pytest
from icloud_mcp.config import Config
from icloud_mcp.server import Connector
from .fakes import FakeIMAP, FakeSMTP, FakeDAV


@pytest.fixture
def make_connector(tmp_path):
    created=[]
    def make(**overrides):
        imap,smtp=FakeIMAP(),FakeSMTP()
        dav=FakeDAV((Path(__file__).parent/'fixtures/recurring.ics').read_text())
        options=dict(profile="full-access", timezone="America/Chicago",account_email="owner@example.invalid",username="owner@example.invalid",
                     state_dir=str(tmp_path/f"state-{len(created)}"))
        options.update(overrides)
        c=Connector(Config(**options),imap_factory=lambda:imap,smtp_factory=lambda:smtp,caldav_factory=lambda:dav)
        c.fake_imap,c.fake_smtp,c.fake_dav=imap,smtp,dav;created.append(c);return c
    yield make
    for c in created:c.close()


async def message_ref(c,folder='Archive/Quoted "Folder"'):
    result=await c.execute("search_messages",{"folder":folder,"query":"needle"})
    assert result['ok'],result
    return result['result']['messages'][0]['message_ref']


async def calendar_ref(c,index=0):
    result=await c.execute("list_calendars",{})
    assert result['ok'],result
    target=c.fake_dav.collections[index].url
    return next(x['calendar_ref'] for x in result['result']['calendars'] if x['resource_href']==target)


async def event_ref(c):
    cal=await calendar_ref(c)
    result=await c.execute("get_events",dict(calendar_ref=cal,start="2026-03-07",end="2026-03-12"))
    assert result['ok'],result
    return result['result']['events'][0]['event_ref']
