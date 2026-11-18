#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Read Azure Cost Management ActualCost at a deliberately explicit scope.

No claim of invoice verification, agent attribution, or cost-center allocation.
Read-only Azure ARM API plus local GAME collector API.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit

import httpx

API_VERSION = '2026-06-01'
SCOPE = re.compile(r'^/subscriptions/[0-9a-fA-F-]{36}(?:/resourceGroups/[A-Za-z0-9._()\-]{1,90})?$')


def arm_token():
    # Explicit Azure CLI account. No customer secrets sent to GAME.
    result = subprocess.run(['az', 'account', 'get-access-token', '--resource',
                             'https://management.azure.com/', '--query', 'accessToken',
                             '-o', 'tsv'], text=True, capture_output=True, timeout=30)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError('Azure CLI authentication unavailable. Run az login and check Cost Management Reader permission.')
    return result.stdout.strip()


def parse_cost_response(data):
    props = data.get('properties') or {}
    names = [c['name'] for c in props.get('columns', [])]
    # Fail closed: don't guess column positions or currency.
    required = {'PreTaxCost', 'ResourceId', 'UsageDate', 'Currency'}
    if not required.issubset(names):
        raise ValueError('Azure response missing required ActualCost columns: ' + ', '.join(sorted(required-set(names))))
    seen = set()
    rows = []
    for values in props.get('rows', []):
        row = dict(zip(names, values))
        raw_date = str(row['UsageDate'])
        if not re.fullmatch(r'\d{8}', raw_date):
            raise ValueError('Invalid Azure UsageDate')
        day = date.fromisoformat(raw_date[:4]+'-'+raw_date[4:6]+'-'+raw_date[6:])
        amount = Decimal(str(row['PreTaxCost']))
        if not amount.is_finite():
            raise ValueError('Non-finite Azure cost')
        currency = str(row['Currency'])
        resource = (str(row['ResourceId']).strip().lower()
                    if row['ResourceId'] is not None else '')
        key = (resource, day.isoformat(), currency)
        if key in seen:
            raise ValueError('Duplicated resource/date/currency row returned; review Azure pagination/grouping')
        seen.add(key)
        rows.append({'resource_id':resource,'usage_day':day.isoformat(),
                     'currency':currency,'amount':str(amount)})
    if props.get('nextLink'):
        raise ValueError('Azure result was paginated; query narrower date range before importing (no partial import)')
    return rows


def query_costs(scope, token, start, end):
    url = 'https://management.azure.com'+scope+'/providers/Microsoft.CostManagement/query?api-version='+API_VERSION
    body = {'type':'ActualCost','timeframe':'Custom','timePeriod':
             {'from':start.isoformat()+'T00:00:00Z','to':end.isoformat()+'T23:59:59Z'},
            'dataset':{'granularity':'Daily',
               'aggregation':{'totalCost':{'name':'PreTaxCost','function':'Sum'}},
               'grouping':[{'type':'Dimension','name':'ResourceId'}]}}
    with httpx.Client(timeout=90) as client:
        response=client.post(url,headers={'Authorization':'Bearer '+token},json=body)
        response.raise_for_status()
        if response.status_code==204: return []
        return parse_cost_response(response.json())


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',required=True,help='Azure subscription or resource group ARM scope')
    parser.add_argument('--days',type=int,default=7,help='Inclusive lookback in days; max 31')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--game-url',default='http://127.0.0.1:8000')
    args=parser.parse_args(argv)
    if not SCOPE.fullmatch(args.scope): parser.error('Scope must be a subscription or resource group ARM path')
    if not 1 <= args.days <= 31: parser.error('Days must be 1..31')
    if args.game_url not in ('http://127.0.0.1:8000','http://localhost:8000'):
        parser.error('Collector import is restricted to localhost:8000')
    today=datetime.now(timezone.utc).date()
    start=today-timedelta(days=args.days-1)
    try:
        rows=query_costs(args.scope,arm_token(),start,today)
        print(f'Azure ActualCost: {len(rows)} resource/day/currency records, {start} to {today}')
        totals={}
        for row in rows:
            currency=row['currency']
            totals[currency]=totals.get(currency,Decimal(0))+Decimal(row['amount'])
        for currency,amount in sorted(totals.items()):
            print(f'  {currency} {amount} (Azure resource-scope actual cost; NOT per-agent or invoice-verified)')
        if args.dry_run:
            print('Dry run: no cost records imported.')
            return 0
        token=os.environ.get('GAME_RUNTIME_INGEST_TOKEN','')
        if len(token)<32:
            print('Collector token missing; load from ~/.config/game/runtime-ingest-token',file=sys.stderr)
            return 1
        with httpx.Client(timeout=60) as client:
            response=client.post(args.game_url+'/api/finops/azure-costs/ingest',
               headers={'X-GAME-Ingest-Token':token},
               json={'scope':args.scope,'rows':rows})
            if response.status_code == 422:
                try:
                    detail=response.json().get('detail', [])
                    if isinstance(detail,list):
                        for issue in detail[:8]:
                            print('VALIDATION ERROR:',
                                  '.'.join(str(i) for i in issue.get('loc',[])),
                                  '-',str(issue.get('msg',''))[:200],file=sys.stderr)
                    else:
                        print('VALIDATION ERROR:',str(detail)[:250],file=sys.stderr)
                except (ValueError,TypeError):
                    print('VALIDATION ERROR: Azure cost payload rejected',file=sys.stderr)
            response.raise_for_status()
            print('Imported:',response.json()['accepted'],'(unallocated Azure resource costs)')
        return 0
    except (httpx.HTTPError,ValueError,RuntimeError) as e:
        print('ERROR: Azure cost collection failed:',str(e)[:350],file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
