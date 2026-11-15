# Phoenix architecture

The native SQLite run/task/event/evidence/model ledger is authoritative. Frontend
views consume it through an authenticated same-origin proxy. Native services include
RunSandboxes, Terminals, Browsers, Investigation, Platforms, ScopeSentry, Engines,
Extensions and the Competition scheduler.

Each run owns an offline category container, immutable inputs and a writable
workspace. Scoped HTTP/TCP and browser traffic pass through the native bus; PTYs stay
in containers. The CLI engine gateway uses a run-local UNIX model/tool socket with
task-scoped tokens; model keys never enter the container. Calls use native
accounting, and model text is not original evidence.

Platform adapters bridge to native challenges, attachments, leases and receipts.
ScopeSentry imports references without expanding scope. Other CLI engines require
independent compatible installed/account environments. SQLite tables are additive;
recovery interrupts open engine/PTY sessions and cancels pending approvals, and
uncertain executions require explicit reconciliation.