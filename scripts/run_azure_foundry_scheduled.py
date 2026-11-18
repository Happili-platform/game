#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""launchd wrapper; loads local token and prevents overlapping collection processes."""
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--mapping',help='Optional legacy override')
    parser.add_argument('--lookback-minutes',type=int,default=60)
    parser.add_argument('--lag-minutes',type=int,default=5)
    args=parser.parse_args()
    cfg=Path.home()/'.config'/'game'
    keyfile=cfg/'runtime-ingest-token'
    if not keyfile.is_file() or keyfile.stat().st_mode & 0o077:
        print('Collector credential absent or insecure permissions (chmod 600)',file=sys.stderr)
        return 1
    token=keyfile.read_text().strip()
    if len(token)<32:
        print('Collector credential too short',file=sys.stderr)
        return 1
    lockfile=cfg/'azure-collector.lock'
    lockfile.touch(mode=0o600,exist_ok=True)
    with lockfile.open('r+') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Previous collection still running; skipped')
            return 0
        env=dict(os.environ)
        # launchd starts with a minimal PATH; accommodate standard Homebrew installs.
        env['PATH'] = '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')
        env['GAME_RUNTIME_INGEST_TOKEN']=token
        cmd=[sys.executable,str(Path(__file__).resolve().with_name('collect_azure_foundry.py')),
             '--workspace',args.workspace, *(['--mapping',args.mapping] if args.mapping else []),
             '--lookback-minutes',str(args.lookback_minutes),
             '--lag-minutes',str(args.lag_minutes)]
        # User Azure CLI credentials must already be available unattended;
        # service-principal/workload identity is preferred for durable operation.
        return subprocess.call(cmd,env=env)


if __name__=='__main__':
    raise SystemExit(main())
