"""Harmless MCP transport check. Optional Docker image; never calls account tools."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(image=None,config=None):
    root=Path(__file__).resolve().parents[1]
    if image:
        command_args=['run','--rm','-i','--network','none',
            '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
            '--tmpfs','/tmp:uid=1000,gid=1000,mode=0700',
            '--tmpfs','/var/lib/icloud-mcp:uid=1000,gid=1000,mode=0700']
        if config:
            command_args+=['--mount',f'type=bind,src={Path(config).resolve()},dst=/run/config.toml,readonly',
                           '-e','ICLOUD_MCP_CONFIG=/run/config.toml']
        params=StdioServerParameters(command='docker',args=command_args+[image])
    else:
        if not config:
            raise ValueError('A private no-account config is required for host testing.')
        params=StdioServerParameters(command=sys.executable,args=['-m','icloud_mcp.server'],cwd=str(root),
                                     env={'ICLOUD_MCP_CONFIG':str(Path(config).resolve())})
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            init=await session.initialize();tools=await session.list_tools()
            ping=await session.call_tool('connector_ping',{})
            assert not ping.isError and not ping.structuredContent['result']['account_access']
            print(json.dumps({'initialized':True,'server':init.serverInfo.name,'tool_count':len(tools.tools),
                              'tools':[t.name for t in tools.tools], 'connector_ping':ping.structuredContent}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image');parser.add_argument('--config')
    args=parser.parse_args();asyncio.run(check(args.image,args.config))
