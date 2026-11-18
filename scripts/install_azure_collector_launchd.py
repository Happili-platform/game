#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Generate a per-user macOS launchd agent; no tokens embedded in plist."""
import argparse
import os
from pathlib import Path
import plistlib
import sys

LABEL = 'com.happili.game.azure-foundry-collector'


def make_plist(project, workspace, mapping, interval, lookback, lag):
    python = project / '.venv' / 'bin' / 'python'
    wrapper = project / 'scripts' / 'run_azure_foundry_scheduled.py'
    if not python.exists() or not wrapper.exists():
        raise ValueError('Expected .venv/bin/python and scheduled wrapper in project')
    logs = Path.home() / '.config' / 'game' / 'logs'
    logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    return {'Label': LABEL,
            'ProgramArguments': [str(python), str(wrapper), '--workspace', workspace,
                                 *(['--mapping', str(mapping)] if mapping else []), '--lookback-minutes', str(lookback),
                                 '--lag-minutes', str(lag)],
            'WorkingDirectory': str(project), 'StartInterval': interval,
            'RunAtLoad': False,
            'StandardOutPath': str(logs/'azure-collector.stdout.log'),
            'StandardErrorPath': str(logs/'azure-collector.stderr.log')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--mapping',help='Optional legacy manual mapping; omit for automatic discovery')
    parser.add_argument('--interval-seconds',type=int,default=900)
    parser.add_argument('--lookback-minutes',type=int,default=60)
    parser.add_argument('--lag-minutes',type=int,default=5)
    a=parser.parse_args()
    if not 300<=a.interval_seconds<=86400:
        parser.error('interval must be between 300 seconds and one day')
    if not 5<=a.lookback_minutes<=1440 or not 0<=a.lag_minutes<=60:
        parser.error('invalid lookback or lag minutes')
    from collect_azure_foundry import GUID
    if not GUID.fullmatch(a.workspace):
        parser.error('workspace must be a GUID')
    project=Path(__file__).resolve().parent.parent
    path=Path.home()/'Library'/'LaunchAgents'/f'{LABEL}.plist'
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        parser.error(f'{path} already exists; unload/backup it before replacing')
    try:
        payload=make_plist(project,a.workspace,Path(a.mapping).expanduser().resolve() if a.mapping else None,
                           a.interval_seconds,a.lookback_minutes,a.lag_minutes)
    except ValueError as exc:
        parser.error(str(exc))
    path.write_bytes(plistlib.dumps(payload))
    os.chmod(path,0o600)
    print('Created:', path)
    print('Load: launchctl bootstrap gui/$(id -u)',path)
    print('Check: launchctl print gui/$(id -u)/'+LABEL)
    print('Unload: launchctl bootout gui/$(id -u)',path)
    print('Scheduled collection requires GAME running on 127.0.0.1:8000.')


if __name__=='__main__':
    main()
