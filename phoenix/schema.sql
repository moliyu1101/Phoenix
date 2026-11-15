PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS engine_sessions(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), task_id TEXT NOT NULL REFERENCES tasks(id),
 engine TEXT NOT NULL, state TEXT NOT NULL, remote_session TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_links(
 id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, challenge_key TEXT NOT NULL,
 challenge_id TEXT NOT NULL REFERENCES challenges(id), competition_id TEXT, snapshot TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_submissions(
 id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, candidate_id TEXT NOT NULL REFERENCES candidates(id),
 state TEXT NOT NULL, result TEXT NOT NULL, created REAL NOT NULL, UNIQUE(connection_id,candidate_id)
);
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), kind TEXT NOT NULL, value TEXT NOT NULL,
 parent_id TEXT REFERENCES assets(id), source TEXT NOT NULL, metadata TEXT NOT NULL, tested INTEGER NOT NULL DEFAULT 0,
 created REAL NOT NULL, updated REAL NOT NULL, UNIQUE(run_id,kind,value)
);
CREATE TABLE IF NOT EXISTS traffic(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), task_id TEXT REFERENCES tasks(id),
 request TEXT NOT NULL, response TEXT NOT NULL, evidence_id TEXT, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS request_approvals(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), task_id TEXT REFERENCES tasks(id),
 request TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS integration_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_sandboxes(
 run_id TEXT PRIMARY KEY REFERENCES runs(id), container_name TEXT NOT NULL UNIQUE,
 category TEXT NOT NULL, image TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS terminal_sessions(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), state TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS terminal_output(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES terminal_sessions(id),
 content TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS challenges(
 id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL,
 targets TEXT NOT NULL, authorized INTEGER NOT NULL, flag_prefix TEXT NOT NULL, created REAL NOT NULL,
 input_hash TEXT NOT NULL DEFAULT '', frozen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS verifiers(challenge_id TEXT PRIMARY KEY REFERENCES challenges(id), expected_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL REFERENCES challenges(id), state TEXT NOT NULL,
 config TEXT NOT NULL, skills TEXT NOT NULL, knowledge_snapshot TEXT NOT NULL, created REAL NOT NULL,
 updated REAL NOT NULL, round INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
 mode TEXT NOT NULL DEFAULT 'live', owner TEXT NOT NULL DEFAULT '',
 billed_tokens INTEGER NOT NULL DEFAULT 0, held_tokens INTEGER NOT NULL DEFAULT 0,
 billed_usd REAL NOT NULL DEFAULT 0, held_usd REAL NOT NULL DEFAULT 0,
 calls INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tasks(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), key TEXT NOT NULL, goal TEXT NOT NULL,
 role TEXT NOT NULL, dependencies TEXT NOT NULL, priority INTEGER NOT NULL, state TEXT NOT NULL,
 fingerprint TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '', started REAL, ended REAL,
 summary TEXT NOT NULL DEFAULT '', attempt INTEGER NOT NULL DEFAULT 0,
 UNIQUE(run_id,key), UNIQUE(run_id,fingerprint)
);
CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id), task_id TEXT,
 kind TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id,seq);
CREATE TABLE IF NOT EXISTS messages(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id), payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), task_id TEXT REFERENCES tasks(id),
 tool TEXT NOT NULL, arguments TEXT NOT NULL, sha256 TEXT NOT NULL, content TEXT NOT NULL,
 origin TEXT NOT NULL, truncated INTEGER NOT NULL, ok INTEGER NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS facts(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), task_id TEXT REFERENCES tasks(id),
 statement TEXT NOT NULL, stance TEXT NOT NULL, citations TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), evidence_id TEXT NOT NULL REFERENCES evidence(id),
 value TEXT NOT NULL, status TEXT NOT NULL, verification TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
 UNIQUE(run_id,value)
);
CREATE TABLE IF NOT EXISTS model_calls(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), role TEXT NOT NULL, profile TEXT NOT NULL,
 status TEXT NOT NULL, reserved_tokens INTEGER NOT NULL, reserved_usd REAL NOT NULL,
 input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, created REAL NOT NULL, ended REAL
);
CREATE TABLE IF NOT EXISTS executions(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), task_id TEXT NOT NULL REFERENCES tasks(id),
 container_name TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS documents(
 id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL, body TEXT NOT NULL,
 source TEXT NOT NULL, sha256 TEXT NOT NULL, trust TEXT NOT NULL, created REAL NOT NULL,
 UNIQUE(sha256,source)
);
CREATE TABLE IF NOT EXISTS chunks(
 id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(id), ordinal INTEGER NOT NULL,
 body TEXT NOT NULL, terms TEXT NOT NULL, embedding TEXT, embedding_space TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id UNINDEXED, terms);
CREATE TABLE IF NOT EXISTS episodes(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id), outcome TEXT NOT NULL,
 trace TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS memories(
 id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, title TEXT NOT NULL, category TEXT NOT NULL,
 kind TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
 doc_id TEXT REFERENCES documents(id), reviewed_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS memory_sources(
 memory_id TEXT NOT NULL REFERENCES memories(id), run_id TEXT NOT NULL REFERENCES runs(id),
 input_hash TEXT NOT NULL, success INTEGER NOT NULL, citations TEXT NOT NULL,
 PRIMARY KEY(memory_id,run_id)
);
CREATE TABLE IF NOT EXISTS skills(
 id TEXT PRIMARY KEY, key TEXT NOT NULL, version INTEGER NOT NULL, spec TEXT NOT NULL,
 sha256 TEXT NOT NULL, parent_id TEXT REFERENCES skills(id), state TEXT NOT NULL,
 created REAL NOT NULL, UNIQUE(key,version)
);
CREATE UNIQUE INDEX IF NOT EXISTS skill_active ON skills(key) WHERE state='active';
CREATE TABLE IF NOT EXISTS evaluations(
 id TEXT PRIMARY KEY, skill_id TEXT NOT NULL REFERENCES skills(id), baseline_id TEXT,
 state TEXT NOT NULL, suite_hash TEXT NOT NULL, mode TEXT NOT NULL, report TEXT NOT NULL,
 created REAL NOT NULL, ended REAL
);
CREATE TABLE IF NOT EXISTS audit(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_cycles(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), state TEXT NOT NULL,
 config TEXT NOT NULL, memory_ids TEXT NOT NULL, skill_ids TEXT NOT NULL,
 evaluation_ids TEXT NOT NULL, report TEXT NOT NULL, created REAL NOT NULL, ended REAL
);
-- Phoenix 0.2 workbench metadata: additive migration, core evidence schema unchanged.
CREATE TABLE IF NOT EXISTS workbench_folders(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workbench_runs(
 run_id TEXT PRIMARY KEY REFERENCES runs(id), name TEXT,
 pinned INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
 folder_id TEXT REFERENCES workbench_folders(id) ON DELETE SET NULL,
 sort_order INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0
);

-- Native swarm snapshots and ownership. Secrets are never persisted in these records.
CREATE TABLE IF NOT EXISTS swarm_workers(
 run_id TEXT NOT NULL REFERENCES runs(id), worker_id TEXT NOT NULL,
 spec TEXT NOT NULL, profiles TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 created REAL NOT NULL, PRIMARY KEY(run_id,worker_id)
);
CREATE TABLE IF NOT EXISTS swarm_assignments(
 task_id TEXT NOT NULL REFERENCES tasks(id), attempt INTEGER NOT NULL,
 run_id TEXT NOT NULL REFERENCES runs(id), worker_id TEXT NOT NULL,
 PRIMARY KEY(task_id,attempt),
 FOREIGN KEY(run_id,worker_id) REFERENCES swarm_workers(run_id,worker_id)
);
CREATE TABLE IF NOT EXISTS swarm_calls(
 call_id TEXT PRIMARY KEY REFERENCES model_calls(id), run_id TEXT NOT NULL REFERENCES runs(id),
 worker_id TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(id),
 FOREIGN KEY(run_id,worker_id) REFERENCES swarm_workers(run_id,worker_id)
);
-- Coordinator (planner/distiller) profiles freeze at run creation so shared
-- configuration can be hot-updated without switching an active run's protocol.
CREATE TABLE IF NOT EXISTS run_profiles(
 run_id TEXT NOT NULL REFERENCES runs(id), role TEXT NOT NULL,
 profile TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(run_id,role)
);
-- Operator-requested Chinese writeups. Generated on demand after a run; usage is
-- audited separately so the settled run's autonomous budget stays intact.
CREATE TABLE IF NOT EXISTS writeups(
 run_id TEXT PRIMARY KEY REFERENCES runs(id), title TEXT NOT NULL, body TEXT NOT NULL,
 doc TEXT NOT NULL, citations TEXT NOT NULL, model TEXT NOT NULL,
 input_tokens INTEGER, output_tokens INTEGER, verified_outcome INTEGER NOT NULL,
 created REAL NOT NULL, updated REAL NOT NULL
);
