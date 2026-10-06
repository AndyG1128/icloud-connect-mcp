"""Exercise real stdio initialization/discovery/calls with the official MCP client."""
from pathlib import Path
import sys
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest
from icloud_mcp.permissions import READ, WRITE


@pytest.mark.parametrize('profile,expunge,expected',[
 ('read-only',False,READ),('full-access',False,READ|(WRITE-{'expunge_messages'})),('full-access',True,READ|WRITE)])
async def test_real_mcp_stdio_profiles(tmp_path,profile,expunge,expected):
    config=tmp_path/'config.toml'
    config.write_text(f'profile = "{profile}"\nstate_dir = "{tmp_path}/state"\npermanent_expunge = {str(expunge).lower()}\n')
    config.chmod(0o600)
    params=StdioServerParameters(command=sys.executable,args=['-m','icloud_mcp.server'],
        cwd=str(Path(__file__).resolve().parents[1]),env={'ICLOUD_MCP_CONFIG':str(config),
        'PYTHONPATH': '' if os.getenv('ICLOUD_MCP_TEST_INSTALLED') else str(Path(__file__).resolve().parents[1]/'src')})
    with (tmp_path/'stderr.log').open('w+') as err:
        async with stdio_client(params,errlog=err) as (read,write):
            async with ClientSession(read,write) as session:
                initialized=await session.initialize()
                assert initialized.serverInfo.name=='independent-icloud-mcp'
                assert initialized.serverInfo.version=='0.2.0b1'
                tools=await session.list_tools();assert {t.name for t in tools.tools}==expected
                ping=await session.call_tool('connector_ping',{})
                assert not ping.isError and ping.structuredContent['result']['account_access'] is False
                assert ping.structuredContent['result']['profile']==profile
                if profile=='read-only':
                    denied=await session.call_tool('send_message',{})
                    assert denied.isError and denied.structuredContent['error']['code']=='PERMISSION_DENIED'
                if not expunge or profile=='read-only':
                    denied=await session.call_tool('expunge_messages',{})
                    assert denied.isError and denied.structuredContent['error']['code']=='PERMISSION_DENIED'
                invalid=await session.call_tool('search_messages',{'folder':'INBOX','limit':0,'secret':'DO_NOT_LOG'})
                assert invalid.isError and invalid.structuredContent['error']['code']=='INVALID_INPUT'
        err.seek(0);logs=err.read();assert 'DO_NOT_LOG' not in logs and 'INBOX' not in logs
