# Native swarm contract

## Identity and routing

Worker ID, role and model are distinct. Config roles route planner, analyst,
solver, reviewer and distiller; named WorkerProfile entries optionally override
the role model. Per-run workers snapshot role-appropriate ModelProfile objects,
including endpoint and credential environment-variable NAME, never secret values.
Credentials are resolved server-side on a call. Key rotation is therefore possible.

Default roster: scout, solver-a, solver-b, reviewer. One active task per worker.
Run concurrency 1-16; roster cap 32; DAG cap 64 tasks inherited from the core.
Planner is a control-plane role, not one of the worker slots; its requests may
overlap workers. There is one durable control-plane process per data directory.

## Scheduling and recovery

SQLite transactions claim dependency-ready tasks and record worker/attempt
assignment together. Roles must match. Worker calls use the frozen profile.
Shared cited observations are refreshed each turn, with original evidence retrievable
by ID. The runtime can replan on completed work/new evidence.

On interruption, prior worker affinity is preserved: an old conversation is not
silently sent through another worker's protocol/model. An unavailable owner or
unsupported role is marked blocked for replanning rather than spinning forever.
Recovery does not guarantee an uncertain external operation is safe to repeat.

Disable means drain (finish in-flight task, claim no new tasks). Lower concurrency
means drain existing work before reaching the new cap. Whole-run pause cancels
the runtime according to the native sandbox reconciliation policy. New workers
can be added while created/running/paused/interrupted, using configured models.
Terminal run rosters are immutable. Dynamic additions do not mutate the global YAML.

## API

- GET /api/swarm/catalog
- GET /api/runs/{rid}/swarm
- POST /api/runs/{rid}/swarm/workers
- PATCH /api/runs/{rid}/swarm/workers/{wid}: {"enabled":false}
- PATCH /api/runs/{rid}/swarm: {"concurrency":4}

All protected endpoints require the workbench token. Usage is recorded per model
call/worker/task and shared with the original run budget. Unknown prices are
unpriced, not free. No distributed multi-host swarm or cluster-wide billing cap
is implemented. Multiple workers share one challenge workspace; DAG ownership
reduces duplicate tasks but does not guarantee collision-free arbitrary filenames.

## Learning

Cited facts are live within the run; approved knowledge/skills use frozen run
snapshots. Distilled experience enters draft, then review/candidate evaluation.
A new trusted document or promoted skill normally affects NEW runs, not the
immutable snapshot of an existing run. No automatic cross-task secret sharing.

## Fixture

`python -m phoenix swarm-demo` uses scripted model replies but real native tool
operations. Analyst/solver overlap, reviewer waits for both dependencies and reads
original evidence. No network model or Docker process is needed. The fixture is
clearly mode=demo and cannot authorize strategy promotion. Its result is plumbing
evidence, not a CTF solve-rate benchmark.
