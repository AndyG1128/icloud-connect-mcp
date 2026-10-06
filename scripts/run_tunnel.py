"""Future operator-run manual session; requires separate tunnel/key approval.

The operator explicitly selects a protected file or environment variable, or
uses a hidden terminal prompt. No other application's credentials are inspected.
The key is passed only to the tunnel child; the connector launcher removes it.
"""
import argparse
import getpass
import json
import os
import re
import stat
from pathlib import Path
import subprocess
import sys
import warnings


def validate_key(key):
    key = key.strip()
    if not key or len(key) > 4096 or not key.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key):
        raise ValueError('Invalid runtime key; value suppressed.')
    return key


def read_key_file(path):
    # NONBLOCK prevents a malicious FIFO from hanging before the regular-file check.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'r', encoding='ascii') as file:
        info = os.fstat(file.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > 4097):
            raise ValueError('Runtime key file must be private, regular and operator-owned.')
        return validate_key(file.read(4098))


def runtime_key(args):
    if args.key_file:
        return read_key_file(args.key_file)
    if args.key_env:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', args.key_env):
            raise ValueError('Invalid runtime-key environment variable name.')
        return validate_key(os.environ.get(args.key_env, ''))
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError('Select --key-file or --key-env explicitly, or use a local terminal prompt.')
    warnings.simplefilter('error', getpass.GetPassWarning)
    return validate_key(getpass.getpass('Tunnel runtime key (Tunnels Read + Use; hidden): '))


def doctor_summary(output, returncode):
    """Never forward arbitrary client/server diagnostics to the terminal or logs."""
    summary={'doctor_exit_code':returncode, 'doctor_passed':returncode==0}
    try:
        data=json.loads(output)
        # Only enum counts survive. Names/messages/URLs/config/credential values do not.
        counts={}
        def visit(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in ('status','severity') and isinstance(item,str) and item.lower() in ('ok','pass','passed','fail','failed','warn','warning','error','skip'):
                        counts[item.lower()]=counts.get(item.lower(),0)+1
                    elif isinstance(item,(dict,list)):visit(item)
            elif isinstance(value,list):
                for item in value:visit(item)
        visit(data)
        summary['check_status_counts']=counts
        known={'codex_plugin','config_source','config_validation','control_plane_api_key','control_plane_base_url',
               'health_listener','mcp_command_executable','mcp_server_reachable','mcp_target','oauth_metadata',
               'profile_load','tunnel_id','ui'}
        failures=data.get('failed_checks',[]) if isinstance(data,dict) else []
        if isinstance(failures,list):
            summary['failed_checks']=[x for x in failures if isinstance(x,str) and x in known]
    except Exception:
        summary['detail']='Diagnostics suppressed; output was not structured JSON.'
    return summary


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser();parser.add_argument('--client',default=str(root/'.bin/tunnel-client'))
    parser.add_argument('--config',default=str(root/'.config/tunnel.yaml'));parser.add_argument('--doctor-only',action='store_true')
    sources=parser.add_mutually_exclusive_group()
    sources.add_argument('--key-file', help='Explicit operator-owned mode-0600 runtime-key file; never stored by this launcher.')
    sources.add_argument('--key-env', help='Explicit environment-variable name holding the runtime key; inherited keys are otherwise ignored.')
    args=parser.parse_args()
    client=Path(args.client).resolve();config=Path(args.config).resolve()
    if not client.is_file() or not config.is_file():parser.error('Prepare the dedicated client binary and private tunnel config first.')
    try:
        key=runtime_key(args)
    except Exception:
        parser.error('Runtime key unavailable or unsafe; check the selected source locally. No key values logged.')
    env={k:os.environ[k] for k in ('PATH','HOME','USER','LANG','SSL_CERT_FILE','SSL_CERT_DIR') if k in os.environ}
    env['CONTROL_PLANE_API_KEY']=key
    # --config is supported by the inspected official tunnel-client. No init/manage API calls.
    try:
        doctor=subprocess.run([str(client),'doctor','--config',str(config),'--explain','--json'],env=env,
                              capture_output=True,text=True,timeout=60)
    except subprocess.TimeoutExpired:
        print('{"doctor_passed":false,"error":"DOCTOR_TIMEOUT"}',file=sys.stderr)
        return 1
    print(json.dumps(doctor_summary(doctor.stdout,doctor.returncode)),file=sys.stderr)
    if doctor.returncode or args.doctor_only:return doctor.returncode
    # Upstream diagnostics are suppressed rather than trusting arbitrary private values.
    # Use the project's Unix health socket for readiness; never enable raw HTTP logs.
    child=subprocess.Popen([str(client),'run','--config',str(config)],env=env,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    key=None
    env.pop('CONTROL_PLANE_API_KEY',None)
    print('Manual tunnel session running. Press Ctrl+C in this terminal to stop.',file=sys.stderr)
    try:
        code=child.wait()
        print(json.dumps({'tunnel_exit_code':code}),file=sys.stderr)
        return code
    except KeyboardInterrupt:
        import signal
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:return 0
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        return 0


if __name__=='__main__':sys.exit(main())
