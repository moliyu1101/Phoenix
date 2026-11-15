# Phoenix

**A native, evidence-first CTF agent runtime.** A FastAPI + SQLite/WAL control plane
coordinates a heterogeneous swarm of model workers; a Simplified-Chinese Next.js
command deck gives you conversation, a runtime timeline and a collaboration graph.
Phoenix is a runtime in its own right — not a broker that shells out to other agent
projects.

`version 0.1.0` · `AGPL-3.0-only` · `Python 3.11+` · `Node.js 20+` · `Linux / WSL`

[中文指南](README_ZH.md) · [Architecture](docs/ARCHITECTURE.md) · [Swarm contract](docs/SWARM.md) ·
[Models](docs/MODELS.md) · [Security](docs/SECURITY.md) · [Validation](docs/VALIDATION.md) · [Notices](NOTICE.md)

---

## Contents

- [What Phoenix is](#what-phoenix-is)
- [Design principles](#design-principles)
- [Features](#features)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [CLI reference](#cli-reference)
- [Web workspaces](#web-workspaces)
- [HTTP API](#http-api)
- [Security and boundaries](#security-and-boundaries)
- [Testing and validation](#testing-and-validation)
- [Project layout](#project-layout)
- [Documentation](#documentation)
- [License](#license)

---

## What Phoenix is

Phoenix solves authorized CTF challenges with a swarm of model workers that share one
challenge workspace, hand off **immutable evidence**, and learn reusable procedures
under a measured promotion gate. Every run, task, event, evidence record and model call
is persisted in an event-sourced SQLite/WAL ledger that is the single source of truth;
the frontend is a projection of that ledger, never a parallel state machine.

It is built for a **trusted single operator** running authorized challenges — not a
public, multi-user attack service. The operator is trusted; the model, challenge files,
target responses and imported text are not.

## Design principles

**Evidence-first.** A tool's bounded original output is *evidence*: it has an ID, a
hash, a run/task source, arguments, a success flag and a truncation marker. Re-reading
an original rechecks its stored hash. Model-generated text is **not** original evidence,
and the presence of an output is not proof of its correctness or relevance.

**Four objects, not one growing chat history.**

| Object | What it is | Trust |
| --- | --- | --- |
| **Evidence** | Bounded original tool/sandbox/target output, hash-verified | Raw record |
| **Episodes** | What a run attempted and how it terminated, with evidence refs | Not auto-trusted |
| **Memories** | Structured lessons with conditions, steps, pitfalls, exact citations | Quarantined `draft` until reviewed |
| **Skills** | Versioned conditional instructions with stop conditions | Candidate until promoted |

**Measured evolution, not self-modification.** "Evolution" means versioned procedure
selection through paired held-out evaluation, a gated promotion and rollback. There is
no weight training, LoRA, policy gradient, self-modifying runtime code or guaranteed
continual improvement.

**Keys stay on the control plane.** Model credentials are resolved server-side per call
and never enter a worker container or the browser. Workers snapshot the credential
*environment-variable name*, not the secret value, so keys can be rotated.

**Honest accounting.** Usage is recorded per model call / worker / task against a shared
per-run budget. Unknown prices are *unpriced*, not free. An absent usage report holds a
conservative reservation and marks the call uncertain.

## Features

### Swarm runtime
- Event-sourced runs, tasks, evidence and a model-usage ledger in SQLite/WAL.
- Distinct **worker ID / role / model**; roles route `planner`, `analyst`, `solver`,
  `reviewer`, `distiller`. Named worker profiles may override the role model.
- Default roster `scout · solver-a · solver-b · reviewer`; one active task per worker;
  run concurrency 1–16, roster cap 32, DAG cap 64 tasks.
- Dependency-ready tasks are claimed in a SQLite transaction together with worker/attempt
  assignment; the runtime can replan on completed work and new evidence.
- Interruption-safe recovery preserves worker affinity (an old conversation is never
  silently rerouted through another worker's protocol/model). Disable = drain; pause
  follows the native sandbox reconciliation policy.

### Evidence, knowledge and memory
- Distillation selects immutable evidence excerpts, backfills originals by ID and
  rechecks full hashes; structural and citation validation happen **outside** the model.
- Reviewed knowledge is chunked with overlap and indexed via SQLite **FTS5/BM25** with
  CJK bigrams, so Chinese technical notes are not one undifferentiated token.
- Optional real embeddings add cosine ranking fused with lexical results (reciprocal
  rank fusion); incompatible vector namespaces are never mixed, and a dense-search
  failure falls back to lexical retrieval. No pseudo-embedding hashes are sold as semantic search.
- Only approved documents in a run's **frozen** knowledge snapshot are retrieved; drafts
  and later imports do not leak into an ongoing run.

### Evaluated strategy evolution
- A complete `learn` cycle: distill → propose one conditional candidate → freeze knowledge
  and model config → run baseline/candidate on held-out cases → evaluate → optional promotion.
- Promotion gate: ≥3 distinct category-matched `heldout` cases, no baseline regression,
  solves increase (or equal nonzero solves with ≥10% token improvement), candidate cost
  ≤125% of baseline when prices are known, no uncertain billed calls, and a real production
  HTTP transport (never the scripted fixture). Previous versions remain available for rollback.

### Model providers and accounting
- Two explicit transports: **Chat Completions-compatible** tool calling and **Anthropic
  Messages** tool use. Streaming generation and the OpenAI Responses API are not implemented.
- Hot-updatable profiles, role routing, worker rosters and credentials from the settings UI;
  saving makes no model call. Overrides apply on restart; live runs must finish first.
- Conservative pre-call UTF-8 byte estimation (messages + tool schemas + output budget)
  can reject a call before a vendor tokenizer would. Per-role USD pricing drives the ledger.

### Tools, sandboxes and extensions
- Untrusted commands run **only** in disposable per-category Docker containers — there is
  no host-execution fallback when Docker is missing. Categories: `base`, `web`, `crypto`,
  `pwn`, `reverse`, `forensics`, `misc`.
- Containers drop capabilities, disable networking, limit processes/CPU/memory, mount a
  read-only root filesystem and expose only challenge input plus a task workspace. Neither
  model credentials nor the Docker socket are mounted inside.
- Real terminal takeover (PTYs stay in containers), scoped Chromium, and traffic
  capture / replay / interception over the native bus with exact-origin checks.
- Native **MCP server and agent-plugin registry** (`stdio`, `streamable-http`, `sse`)
  bridged to the tool bus, recording evidence and scanning for flags.

### Competition scheduling
- **CTFd / GZCTF / rCTF** adapters bridge to native challenges, attachments, leases and receipts.
- Batch scheduler: platform queue registration/sync, admission policy, concurrency control,
  manual admit / skip / reorder, and gated auto-submit. Uncertain remote submissions are
  never blindly retried.
- ScopeSentry imports asset references **without expanding scope**.

### Command-deck frontend
- Simplified-Chinese Next.js 15 / React 19 command deck with a persistent activity rail
  across draft, run and management routes.
- Conversation, activity console / waterfall / ledger / playback, and an agent
  collaboration canvas; knowledge, memory, evolution and settings share the same
  primitives, palette and inspectors.
- `phoenixTrace` maps persisted events/tasks/model calls to a trace scenario — only actual
  timing is shown, and missing prices/tokens stay *unknown*.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser · Next.js command deck (zh-CN) · :3001                    │
│  conversation · timeline · collaboration graph · settings          │
└───────────────┬────────────────────────────────────────────────────┘
                │  authenticated same-origin proxy (Bearer token)
┌───────────────▼────────────────────────────────────────────────────┐
│  FastAPI control plane · :18750 (loopback by default)               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  SQLite/WAL ledger — runs · tasks · events · evidence · usage  │  │
│  │  (authoritative, event-sourced)                                │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  Swarm · Providers · Knowledge/Memory · Evolution · Platforms       │
│  Competition · Extensions(MCP) · Investigation · ScopeSentry        │
└───────┬──────────────────────────────────┬─────────────────────────┘
        │ run-local UNIX socket            │ Docker API (trusted plane)
        │ task-scoped tokens               │
┌───────▼─────────────────┐      ┌─────────▼─────────────────────────┐
│  CLI engine gateway     │      │  Disposable category sandbox       │
│  model keys never inside│      │  no network · read-only rootfs     │
└─────────────────────────┘      │  PTY inside · input + workspace    │
                                 └────────────────────────────────────┘
```

The native ledger is authoritative. Each run owns an offline category container,
immutable inputs and a writable workspace. Scoped HTTP/TCP and browser traffic pass
through the native bus; the CLI engine gateway uses a run-local UNIX model/tool socket
with task-scoped tokens. Platform adapters, sandboxes, MCP extensions and the competition
scheduler are native services. SQLite tables are additive; recovery interrupts open
engine/PTY sessions and cancels pending approvals, and uncertain executions require
explicit reconciliation. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

- **Linux or WSL** — the runtime is POSIX-specific (directory descriptors, no-follow
  traversal, UNIX sockets, process groups).
- **Python 3.11+**
- **Node.js 20+** and npm (for the frontend)
- **Docker** with a reachable daemon (for full tool capabilities; the trusted control
  plane must be allowed to control Docker)

## Quick start

```bash
# 1. Create .venv, install the package + dev extras, scaffold config.yaml and .env,
#    and install frontend dependencies.
bash scripts/bootstrap.sh            # add --backend-only to skip the frontend

# 2. Build the per-category tool images (requires Docker + network access).
bash scripts/build-tools.sh

# 3. Fill in real model settings and the workbench token (see Configuration below),
#    then start the API + frontend in development mode.
bash scripts/start.sh --dev
```

- **Development:** `bash scripts/start.sh --dev` (Next.js dev server).
- **Production:** `bash scripts/build-ui.sh` then `bash scripts/start.sh` (Next standalone).
- **Backend only:** `bash scripts/start.sh --backend-only`.
- **No-cost smoke test:** `.venv/bin/python -m phoenix swarm-demo` — a scripted model
  fixture through real native tool operations; no network model or Docker process needed.

**Ports & token.** UI `3001`, native API `18750` (both loopback by default). The workbench
token is stored in the browser's `sessionStorage` and sent in headers, never in URLs.
Leave `PHOENIX_WEB_TOKEN` blank and `serve` generates a random token (mode `0600` under
`data_dir/.web-token`) and prints it once. Model credentials remain on the server.

## Configuration

### config.yaml

Copy `config.example.yaml` to `config.yaml` (bootstrap does this for you). Starting the
workbench makes **no** model request.

```yaml
data_dir: data
host: 127.0.0.1
port: 18750
token_env: PHOENIX_WEB_TOKEN
profiles:
  default:
    protocol: chat                 # chat | anthropic
    base_url: https://your-provider.example/v1
    model: ""                      # required for live runs; or set PHOENIX_MODEL
    api_key_env: PHOENIX_API_KEY    # NAME of the env var holding the key, never the key
    context_tokens: 32768
    output_tokens: 4096
    chat_token_parameter: max_completion_tokens
    input_usd_per_million: null    # set real prices before enabling a USD ceiling
    output_usd_per_million: null
roles: {planner: default, analyst: default, solver: default, reviewer: default, distiller: default}
sandbox_image: phoenix-tools:0.1.0
sandbox_memory: 1024m
sandbox_cpus: 1.0
max_output_bytes: 2097152
workers:
  - {id: scout,    name: Recon Analyst,       roles: [analyst]}
  - {id: solver-a, name: Solver Alpha,        roles: [solver]}
  - {id: solver-b, name: Solver Beta,         roles: [solver]}
  - {id: reviewer, name: Independent Reviewer, roles: [reviewer]}
```

A swarm-oriented template is also provided in `config.swarm.example.yaml`.

### Environment variables (`.env`)

Copy `.env.example` to `.env` (mode `0600`). Keep all keys private and out of challenge
prompts and source control.

| Variable | Purpose |
| --- | --- |
| `PHOENIX_MODEL` | Overrides the `default` profile model |
| `PHOENIX_BASE_URL` | Overrides the `default` profile base URL |
| `PHOENIX_API_KEY` | Default provider credential (referenced by `api_key_env`) |
| `PHOENIX_WEB_TOKEN` | Workbench bearer token (≥24 chars); blank ⇒ auto-generated |
| `PHOENIX_EMBEDDING_KEY` | Optional embedding endpoint credential |
| `PHOENIX_DATA_DIR` | Overrides the data directory |

Only the `default` profile reads `PHOENIX_MODEL` / `PHOENIX_BASE_URL`; other profiles use
their YAML fields. **Never write secret values into YAML** — reference them by env-var name.

### Operator overrides and precedence

The settings UI persists model profiles, role routing, worker rosters and credentials as
durable files in the data directory:

- `data_dir/operator-config.json` — model/role/roster overrides (never ports or data paths).
- `data_dir/model-credentials.json` — credentials, mode `0600`, **never returned by the API**.
  A blank password field keeps the existing key.

Effective precedence: **YAML → environment → operator overrides** (applied on restart).
Changes to model/roster settings are rejected while a live run is nonterminal. To return
to YAML-owned config, stop the API, back up and remove the override files, and restart.

### Model protocols and pricing

The endpoint must implement the selected protocol and the model must support tools — a
generic base URL alone is not enough. Chat tool IDs/arguments and supported extensions
(e.g. `reasoning_content`) are persisted and replayed; Anthropic tool-use and signed
content blocks are kept for replay. Requests do not follow redirects or blindly retry.
Set the actual input/output USD-per-million-token prices for every role before enabling a
USD cap; the ledger is based on those values and the provider's usage report, not an
invoice guarantee. See [docs/MODELS.md](docs/MODELS.md).

## CLI reference

After `pip install -e .` the `phoenix` console script is available; the scripts use
`.venv/bin/python -m phoenix`. All commands accept `--config <path>` (default `config.yaml`).

| Command | What it does | Cost |
| --- | --- | --- |
| `serve` | Start the authenticated native workbench (API) | — |
| `doctor` | Print Python/SQLite versions, Docker CLI presence and redacted profiles; sends no request | free |
| `demo` | Run a scripted single-run fixture through real native tools | free |
| `swarm-demo` | Run the scripted parallel swarm + evidence-handoff fixture | free |
| `seed` | Install original baseline skills and starter knowledge | free |
| `ingest <path> [--category C] [--trusted]` | Import local text/Markdown knowledge (≤2 MiB; no API calls) | free |
| `evaluate <skill_id> <suite> --confirm-model-charges` | Execute a paid paired held-out benchmark | **paid** |
| `learn <run_id> <suite> --confirm-model-charges [--promote]` | Distill → propose → evaluate → optional promotion | **paid** |

`evaluate` and `learn` refuse to run without `--confirm-model-charges`. The scripted
fixtures are clearly `mode=demo`, cannot authorize strategy promotion, and are plumbing
evidence — not a CTF solve-rate benchmark.

## Web workspaces

The command deck (UI `:3001`) exposes these routes:

| Area | Routes |
| --- | --- |
| Command deck | `/` |
| Challenges | `/ctf`, `/ctf/workers` |
| Swarm | `/swarm` |
| Learning | `/knowledge`, `/memory`, `/evolution` |
| Competition | `/competition`, `/competition/scheduler` |
| Run detail | `/run/[id]`, `/run/[id]/collaboration` |
| Settings | `/settings`, `/settings/appearance`, `/settings/extensions`, `/settings/integrations`, `/settings/shortcuts` |

## HTTP API

All protected endpoints require the workbench bearer token (`Authorization: Bearer <token>`).
The UI proxies authenticated same-origin requests to the native API. Representative routes:

- **Overview / settings:** `GET /api/overview`, `GET /api/settings`, `GET /health`
- **Challenges:** `GET/POST /api/challenges`, `GET /api/challenges/{cid}`,
  `.../files`, `.../runs`, `.../verifier`
- **Runs:** `GET /api/runs/{rid}`, `.../events`, `.../stream`, `.../pause`, `.../resume`,
  `.../reconcile`, `.../distill`, `.../learn`, `.../writeup` (+ `/evidence`, `/export`),
  `GET /api/runs/{rid}/evidence/{eid}`
- **Swarm:** `GET /api/swarm/catalog`, `GET /api/runs/{rid}/swarm`,
  `POST /api/runs/{rid}/swarm/workers`, `PATCH .../workers/{wid}`, `PATCH .../swarm`
- **Knowledge / memory / skills:** `/api/knowledge` (+ `/search`, `/{did}`, `/{did}/index`,
  `/{did}/review`), `/api/memories` (+ `/{mid}/review`, `/{mid}/strategy`),
  `/api/skills` (+ `/{sid}/evaluate`, `/{sid}/promote`, `/{sid}/rollback`)
- **Evaluation / learning:** `/api/evaluations`, `/api/learning`, `/api/candidates/{cid}/receipt`

Error mapping: `NotFound → 404`, `Conflict → 409`, `ValueError → 422`, `PhoenixError → 400`.
API responses are `no-store`; individual uploads are limited to 48 MiB and aggregate listed
input to 128 MiB (these are upload guards, not a disk-quota system).

## Security and boundaries

Use Phoenix only for authorized CTF challenges and files you are entitled to analyze.
Read [docs/SECURITY.md](docs/SECURITY.md) before deploying.

### Implemented controls
- Binds to **loopback by default**; requires a bearer token of **≥24 characters**.
- Write requests with a foreign `Origin` are refused; no broad CORS; API responses are
  `no-store`; static assets have a restricted CSP; generated tokens are mode `0600`.
- **No model API key is sent to the browser.**
- File operations use POSIX directory descriptors and no-follow traversal; absolute paths,
  parent traversal, drive paths and symlinks are rejected. Challenge inputs are read-only
  from the model's tool interface; a worker writes only inside its own task workspace.
- Untrusted commands run only in disposable Docker containers (no host fallback): dropped
  capabilities, disabled networking, resource limits, read-only rootfs, and neither model
  credentials nor the Docker socket mounted inside.
- Network target tools check exact normalized origins, reject userinfo/encoded-host tricks,
  disallow Host/proxy override headers, do not follow redirects, and serialize per-origin
  operations. The model cannot choose arbitrary unlisted target origins.

### Known limits (not solved)
- Origin checks are **not** an egress firewall or DNS/IP pinning; target-driven SSRF is a
  separate scope consideration. Isolate the control plane at the network level.
- Docker shares the host kernel; resource limits are not a total workspace disk quota.
  Kernel exploits, container escape and a compromised Docker daemon are outside the
  prototype's guarantees. Run hostile artifacts in a disposable machine.
- Evidence hashes detect mismatch against the stored hash, not an administrator who rewrites
  both. Exact quotes prove text occurred, not the model's interpretation. Reflected
  flag-literal rejection is a heuristic; only a separate verifier or a genuine platform
  receipt establishes acceptance (receipt authenticity is not auto-checked in this version).
- Prompt injection in attachments, web responses and knowledge is not formally eliminated.
  Retrieved text is explicitly untrusted and tool permissions stay outside the model, but
  adversarial text can still waste budget or mislead reasoning.
- Raw records and run exports may contain target data, outputs and secrets; they are private
  local records, not auto-redacted public writeups. Heuristic memory redaction is not a
  comprehensive secrets scanner.
- POSIX-specific, one control-plane process, one SQLite store. No multi-tenant isolation,
  automatic high availability, queue-based paid-job recovery, encrypted data-at-rest layer
  or production security audit. Unit tests are not a penetration test or a verified sandbox guarantee.

### Authorization
Authorization is **implicit**: using a project treats its challenges as authorized. There
is no "I am authorized" checkbox. Do not expose the service on an untrusted network without
an authenticated TLS proxy, host firewall and a separate authorization review.

## Testing and validation

```bash
# Backend unit/integration suite (scripted model fixtures; no paid calls).
bash scripts/test.sh                 # == .venv/bin/python -m pytest -q

# Frontend gates.
cd frontend
npm run typecheck                    # tsc --noEmit
npm run check:phoenix                # native adapter / localization checks
node scripts/check-trace.mjs         # trace projection checks
npm run build                        # production build (Next standalone)
node scripts/browser-check.mjs       # real-browser acceptance suites

# Native purity audit (source inspection, not a dynamic sandbox or security certification).
.venv/bin/python scripts/audit_native.py
```

The 0.1.0 source release was verified on an isolated target VM: backend **202 tests passed**,
frontend typecheck + production build passed across all 16 routes, and the native audit
reported `application=Phoenix`. Verification used scripted model fixtures — it does not
represent real contest-account acceptance or a model solve-capability evaluation, and it
does not establish a CTF ranking. See [docs/VALIDATION.md](docs/VALIDATION.md).

## Project layout

```
phoenix/            Native runtime: api, swarm, runtime, providers, store, evidence,
                    knowledge, memory, learning, evolution, competition, platforms,
                    extensions, investigation, scopesentry, sandbox, terminal, browser,
                    writeup, cli, vendor/engine (vendored engine implementation)
frontend/           Simplified-Chinese Next.js command deck (app/, components/, lib/, scripts/)
integrations/       phoenix/ — agents, skills and per-category sandbox images
scripts/            bootstrap, build-tools, build-sandboxes, build-ui, start, serve,
                    test, audit_native, package_source
docs/               ARCHITECTURE, SWARM, MODELS, FRONTEND, LEARNING, SECURITY, VALIDATION
tests/              Backend pytest suite
examples/           create_challenge.py, knowledge-note.md, payload.txt
benchmarks/         public-wiring-suite.json (wiring fixtures, not a capability benchmark)
licenses/           AGPL-3.0.txt
config.example.yaml · config.swarm.example.yaml · .env.example
SOURCE_MANIFEST.json · SOURCE_SHA256SUMS.txt   (source-package integrity)
```

The source distribution **excludes** dependencies, compiled UI, model credentials, user
data and built tool images. Tool images are built locally and require network access.
Regenerate the integrity manifests with `python scripts/package_source.py`.

## Documentation

| Doc | Topic |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Native services, ledger authority, run isolation |
| [docs/SWARM.md](docs/SWARM.md) | Identity/routing, scheduling, recovery, swarm API |
| [docs/MODELS.md](docs/MODELS.md) | Protocols, profiles, token/money accounting, settings UI |
| [docs/LEARNING.md](docs/LEARNING.md) | Evidence/memory/skills, distillation, promotion gate |
| [docs/FRONTEND.md](docs/FRONTEND.md) | Command-deck views, adapters, projections |
| [docs/SECURITY.md](docs/SECURITY.md) | Controls, boundaries, deployment limits |
| [docs/VALIDATION.md](docs/VALIDATION.md) | 0.1.0 verification scope and results |
| [NOTICE.md](NOTICE.md) | Source notices, licensing and boundaries |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## License

Phoenix is licensed **AGPL-3.0-only**. License texts are in [`licenses/`](licenses/) and
[`phoenix/vendor/engine/LICENSE.txt`](phoenix/vendor/engine/LICENSE.txt). Bundled third-party
components retain their own licenses; frontend third-party notices ship with the UI
dependencies. See [NOTICE.md](NOTICE.md).