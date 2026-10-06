"""Operator-run bounded check after separate credential/live-read approval.

Prints counts/assertions only. Does not expose discovery names or private content.
Samples are explicitly selected by folder and calendar ID; no write tools called.
"""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from icloud_mcp.config import load_config
from icloud_mcp.permissions import READ
from live_validation import Validator, CheckError, insist, read_plan, save_inventory


async def check(args):
    config=load_config(args.config)
    insist(config.profile=='read-only' and not config.permanent_expunge, 'READ_ONLY_REQUIRED')
    plan=read_plan(args.plan) if args.plan else {}
    root=Path(__file__).resolve().parents[1]
    params=StdioServerParameters(command=sys.executable,args=['-m','icloud_mcp.server'],cwd=str(root),
                                env={'ICLOUD_MCP_CONFIG':str(Path(args.config).resolve())})
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            async def call(name,arguments):
                return (await session.call_tool(name,arguments)).structuredContent
            ping=await call('connector_ping',{})
            insist(ping['result']['profile']=='read-only', 'READ_ONLY_REQUIRED')
            tools=await session.list_tools()
            insist({t.name for t in tools.tools} <= READ and all(t.annotations.readOnlyHint and
                not t.annotations.destructiveHint for t in tools.tools), 'WRITE_PROHIBITED')
            validator=Validator(call,config,plan)
            result=await validator.run()
            save_inventory(config.state_dir,validator.inventory,getattr(validator,'folders',[]))
            result['read_only_profile_verified']=True
            print(json.dumps(result,sort_keys=True))
            return 0 if result['ok'] else 1


if __name__=='__main__':
    logging.disable(logging.CRITICAL)
    p=argparse.ArgumentParser();p.add_argument('--config',required=True)
    p.add_argument('--plan',help='Private 0600 sample/keyword JSON; omit for discovery only.')
    args=p.parse_args()
    try:sys.exit(asyncio.run(check(args)))
    except CheckError as error:print(json.dumps({'ok':False,'error':error.code}),file=sys.stderr);sys.exit(1)
    except Exception:print('{"ok":false,"error":"LIVE_CHECK_FAILED_REDACTED"}',file=sys.stderr);sys.exit(1)
