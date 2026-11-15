# Phoenix

Phoenix is a native, evidence-first CTF agent runtime. A FastAPI + SQLite/WAL
backend coordinates a heterogeneous swarm of workers; a Chinese-localized Next.js
command-deck frontend provides conversation, runtime timeline and collaboration
graph workspaces.

Read the [Chinese guide](README_ZH.md), [validation](docs/VALIDATION.md) and
[notices](NOTICE.md).

## Highlights

- Event-sourced runs, tasks, evidence and a model usage ledger in SQLite/WAL.
- Worker rosters with role/category eligibility, per-worker model profiles and shared per-run budgets.
- Knowledge and memory distillation from immutable, hash-verified evidence excerpts.
- Strategy evolution through paired held-out evaluation, gated promotion and rollback.
- Hot-updatable model configuration (Chat Completions and Anthropic Messages); model keys stay on the control plane.
- Native MCP server and agent-plugin registry (stdio, streamable-http, sse) bridged to the tool bus.
- Competition batch scheduler with admission policy, concurrency control and gated auto-submit.
- CTFd/GZCTF/rCTF adapters and per-run offline sandboxes: terminal takeover, scoped Chromium, traffic capture/replay/interception and asset coverage.

## Requirements

Linux/WSL, Python 3.11+, Node.js 20+ and Docker for full tool capabilities.

```bash
bash scripts/bootstrap.sh
bash scripts/build-tools.sh
# Fill model settings and the workbench token, then:
bash scripts/start.sh --dev
```

Production: `bash scripts/build-ui.sh` then `bash scripts/start.sh`. UI port 3001,
native API port 18750. The workbench token is stored in the browser session and sent
in headers, never in URLs. Model credentials remain on the server.

The source distribution excludes dependencies, compiled UI, model credentials, user
data and built tool images. Integration and held-out results do not establish a CTF
ranking. Authorization is implicit: using a project treats its challenges as authorized.