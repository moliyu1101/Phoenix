# Changelog

## 0.1.0

Initial source release of Phoenix, a native evidence-first CTF agent runtime.

- Native FastAPI + SQLite/WAL swarm runtime with event-sourced runs, tasks, evidence and a model usage ledger.
- Heterogeneous worker rosters with role/category eligibility, per-worker model profiles, snapshotted configuration and shared per-run budgets.
- Knowledge and memory distillation from immutable evidence excerpts, with hash-verified citations.
- Strategy evolution through paired held-out evaluation, gated promotion and rollback.
- Hot-updatable model configuration (Chat Completions and Anthropic Messages); secrets stay on the control plane and are never echoed to the browser.
- Native MCP server and agent-plugin registry (stdio, streamable-http, sse) with a tool-bus bridge that records evidence and scans flags.
- Competition batch scheduler: platform queue registration/sync, admission policy, concurrency control, manual admit/skip/requeue and gated auto-submit.
- CTFd/GZCTF/rCTF platform adapters and per-run offline category sandboxes with terminal takeover, scoped Chromium, traffic capture/replay/interception and asset coverage.
- Chinese-localized Next.js command-deck frontend with conversation, runtime timeline and collaboration graph workspaces.

Validation: full backend test suite, TypeScript typecheck and production build, and real-browser acceptance. See docs/VALIDATION.md. Scripted model fixtures only; no paid-model solving or competition ranking is claimed.