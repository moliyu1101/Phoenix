# Source notices and boundaries

Phoenix is licensed AGPL-3.0-only. License texts are in `licenses/` and
`phoenix/vendor/engine/LICENSE.txt`. Bundled third-party components retain their
own licenses; frontend third-party notices ship with the UI dependencies.

The native runtime is self-contained: the SQLite run/task/event/evidence/model
ledger is authoritative, and the frontend consumes it through an authenticated
same-origin proxy. Platform adapters, category sandboxes, MCP extensions and the
competition scheduler are native services. External CLI engines and platform
accounts require their own compatible installed environments; source presence alone
does not imply every engine or account is ready.

No model key, user data, dependency folder, built image or compiled UI ships in the
source distribution. Tool images are built locally and require network access.
Authorization is implicit: using a project treats its challenges as authorized, and
uncertain remote submissions are never blindly retried.