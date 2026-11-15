#!/usr/bin/env python3
"""Report native runtime imports and subprocess sites. This is not a security proof."""
import ast
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
imports, sites, violations = set(), [], []
for path in sorted((root / 'phoenix').rglob('*.py')):
    rel = str(path.relative_to(root))
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for x in node.names:
                imports.add(x.name)
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            imports.add(node.module or '')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ('create_subprocess_exec', 'create_subprocess_shell', 'Popen', 'system', 'execv', 'execve'):
                sites.append({'file': rel, 'line': node.lineno, 'call': node.func.attr})
                if rel != 'phoenix/sandbox.py' or node.func.attr != 'create_subprocess_exec':
                    violations.append({'file': rel, 'line': node.lineno, 'unexpected_process_site': node.func.attr})
report = {'application': 'Phoenix', 'external_imports': sorted(imports), 'subprocess_sites': sites, 'violations': violations,
          'qualification': 'Source inspection check, not a dynamic sandbox or security certification.'}
print(json.dumps(report, indent=2))
raise SystemExit(bool(violations))