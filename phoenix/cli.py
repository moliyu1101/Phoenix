from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
from pathlib import Path

from .config import load_settings
from .domain import dump
from .service import Components


def main():
    parser = argparse.ArgumentParser(description='Phoenix native CTF agent runtime')
    parser.add_argument('--config', default='config.yaml')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('serve', help='Start the authenticated native workbench')
    sub.add_parser('demo', help='Run a SCRIPTED model fixture through real native tools; not a capability benchmark')
    sub.add_parser('swarm-demo', help='Run the SCRIPTED parallel swarm and evidence-handoff fixture')
    sub.add_parser('doctor', help='Inspect local dependencies and model configuration without sending requests')
    sub.add_parser('seed', help='Install original baseline skills and starter knowledge')
    imp = sub.add_parser('ingest', help='Import local text/Markdown knowledge; no automatic API calls')
    imp.add_argument('path', type=Path)
    imp.add_argument('--category', default='general')
    imp.add_argument('--trusted', action='store_true', help='Explicitly approve this document for retrieval')
    evaluation = sub.add_parser('evaluate', help='Execute a paid paired held-out benchmark')
    evaluation.add_argument('skill_id')
    evaluation.add_argument('suite', type=Path)
    evaluation.add_argument('--confirm-model-charges', action='store_true')
    learning = sub.add_parser('learn', help='Distill -> propose -> held-out evaluation -> optional automatic promotion')
    learning.add_argument('run_id')
    learning.add_argument('suite', type=Path)
    learning.add_argument('--confirm-model-charges', action='store_true')
    learning.add_argument('--promote', action='store_true')
    args = parser.parse_args()
    settings = load_settings(args.config)
    c = Components(settings)
    if args.command == 'serve':
        import uvicorn
        from .api import create_app
        if not settings.web_token:
            key_path = settings.data_dir / '.web-token'
            if key_path.exists():
                token = key_path.read_text().strip()
            else:
                token = secrets.token_urlsafe(32)
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    stream.write(token)
            os.environ[settings.token_env] = token
            print(f'Local workbench token: {token}', flush=True)
            print('Keep this token private. The browser will ask for it.', flush=True)
        uvicorn.run(create_app(settings, c), host=settings.host, port=settings.port, workers=1)
    elif args.command == 'demo':
        from .demo import create_demo
        result = asyncio.run(create_demo(c))
        print(json.dumps({'mode': 'SCRIPTED DEMONSTRATION - NO REAL MODEL', 'run': result}, indent=2))
    elif args.command == 'swarm-demo':
        from .swarm_demo import create_swarm_demo
        print(dump(asyncio.run(create_swarm_demo(c))))
    elif args.command == 'doctor':
        import shutil
        import sqlite3
        import sys
        print(json.dumps({'python': sys.version, 'platform': sys.platform, 'sqlite': sqlite3.sqlite_version,
                          'docker_client': shutil.which('docker'), 'native_runtime': True,
                          'old_project_dependencies': [], 'model_configuration': settings.public()['profiles'],
                          'note': 'No network request or Docker container was executed by this diagnostic.'}, indent=2))
    elif args.command == 'ingest':
        if args.path.suffix.lower() not in ('.md', '.txt', '.json', '.py', '.log', '.csv'):
            parser.error('Import text files only; convert PDFs or proprietary formats separately')
        if args.path.stat().st_size > 2_000_000:
            parser.error('The per-document limit is 2 MiB')
        did = c.knowledge.ingest(args.path.name, args.path.read_text(), args.category,
                                 f'operator:{args.path.name}', args.trusted)
        print(dump({'document_id': did, 'trusted': args.trusted}))
    elif args.command == 'learn':
        if not args.confirm_model_charges:
            parser.error('Pass --confirm-model-charges to authorize the complete learning cycle')
        from .domain import RunInput
        from .evolution import BenchmarkSuite
        suite = BenchmarkSuite.model_validate_json(args.suite.read_text())
        print(dump(asyncio.run(c.learning.execute(args.run_id, suite, RunInput(auto_distill=False), args.promote))))
    elif args.command == 'evaluate':
        if not args.confirm_model_charges:
            parser.error('Pass --confirm-model-charges to authorize the paired evaluation')
        from .domain import RunInput
        from .evolution import BenchmarkSuite
        suite = BenchmarkSuite.model_validate_json(args.suite.read_text())
        print(dump(asyncio.run(c.evaluator.evaluate(args.skill_id, suite, RunInput(auto_distill=False)))))
    else:
        print('Original baseline skills and starter knowledge are installed.')


if __name__ == '__main__':
    main()
