#!/usr/bin/env python3
"""Create an authorized challenge through the native API; no model request unless --start."""
import argparse
import base64
import json
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18750')
    parser.add_argument('--token-file', type=Path, default=Path('data/.web-token'))
    parser.add_argument('--title', required=True)
    parser.add_argument('--description', required=True)
    parser.add_argument('--category', choices=['web','crypto','pwn','reverse','forensics','misc'], default='misc')
    parser.add_argument('--file', type=Path, action='append', default=[])
    parser.add_argument('--target', action='append', default=[])
    parser.add_argument('--authorized', action='store_true')
    parser.add_argument('--start', action='store_true', help='Authorize real model calls using the server profiles')
    args = parser.parse_args()
    if not args.authorized:
        parser.error('Pass --authorized only for files and targets you are authorized to test')
    token = os.environ.get('PHOENIX_WEB_TOKEN', '')
    if not token and args.token_file.exists():
        token = args.token_file.read_text().strip()
    if not token:
        parser.error('Provide PHOENIX_WEB_TOKEN or the generated local token file')
    for path in args.file:
        if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            parser.error(f'Not a regular attachment of at most 32 MiB: {path.name}')
    if sum(p.stat().st_size for p in args.file) > 128 * 1024 * 1024:
        parser.error('Total attachments must not exceed 128 MiB')
    with httpx.Client(base_url=args.url.rstrip('/'), headers={'Authorization':'Bearer '+token},
                      timeout=90, follow_redirects=False, trust_env=False) as client:
        def post(path, body):
            result = client.post('/api'+path, json=body)
            if result.is_error:
                raise SystemExit(f'API HTTP {result.status_code}: {result.text[:1200]}')
            return result.json()
        challenge = post('/challenges', {'title':args.title, 'description':args.description,
                         'category':args.category, 'targets':args.target, 'authorized':True})
        for path in args.file:
            post('/challenges/'+challenge['id']+'/files', {'name':path.name,
                 'data_base64':base64.b64encode(path.read_bytes()).decode()})
        result = {'challenge_id':challenge['id'], 'started':False}
        if args.start:
            run = post('/challenges/'+challenge['id']+'/runs', {'concurrency':2,'auto_distill':True})
            result.update(started=True,run_id=run['id'])
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
