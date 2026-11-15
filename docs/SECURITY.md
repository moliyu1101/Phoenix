# Security boundaries and deployment limits

Use Phoenix only for authorized CTF challenges and files you are entitled to
analyze. A challenge must declare authorization and exact HTTP(S)/TCP origins.
This is not a public multi-user attack service. The operator is trusted; the model,
challenge files, target responses and imported text are not.

## Controls implemented

The web service binds to loopback by default and requires a bearer token of at
least 24 characters. Write requests with a foreign Origin are refused. No model
API key is sent to the browser. API responses are no-store; static assets have a
restricted CSP. Generated tokens are mode 0600. The service does not enable broad
CORS. Do not expose it on an untrusted network without an authenticated TLS proxy,
host firewall and a separate authorization review.

File operations use POSIX directory descriptors and no-follow traversal. Absolute
paths, parent traversal, drive paths and symlinks are rejected. Challenge inputs
are read-only from the model's tool interface. A worker can write only inside its
own task workspace; reads can inspect other tasks' same-run outputs. The API limits
individual uploads and aggregate listed input bytes. It is not a disk quota system.

Untrusted commands run only via disposable Docker containers. There is no fallback
to executing a model command on the host when Docker is missing. The runtime drops
capabilities, disables networking, limits processes/CPU/memory, makes the root
filesystem read-only and mounts only challenge input and a task workspace. Neither
model API credentials nor the Docker socket are mounted into the worker container.
The trusted control-plane service itself must be allowed to control Docker.

Network target tools check exact normalized origins, reject userinfo/encoded
host tricks, disallow Host/proxy override headers, and do not follow redirects.
Per-origin operations are serialized. TCP payloads use explicit base64 and bounded
reads/timeouts. The model cannot choose arbitrary unlisted target origins.

## Boundaries not solved

Origin checks are not an egress firewall or DNS/IP pinning. A malicious operator-
authorized domain could resolve to a private address, and target-driven SSRF is a
separate scope consideration. Use network isolation around the control plane and
validate allowed destinations when that distinction matters.

Docker shares the host kernel. Resource limits do not enforce a total workspace
disk quota. Kernel exploits, container escape and a compromised Docker daemon are
outside this prototype's guarantees. Run hostile CTF artifacts in a disposable
machine without personal credentials or sensitive mounts. Debugging/syscall tools
may be restricted by Docker's default policy; the model cannot relax that policy.

Evidence hashes detect mismatch against the stored hash, not an administrator who
rewrites both. Exact quotes prove the text occurred, not the model's interpretation.
Reflected flag-literal rejection is a heuristic, not a proof against manufactured
outputs. Only a separate verifier or operator-provided genuine platform receipt
establishes acceptance. Receipt authenticity is not automatically checked with a
competition platform in this version.

Prompt injection in attachments, web responses and knowledge is not formally
eliminated. Retrieved text is explicitly untrusted and tool permissions remain
outside the model, but adversarial text can still waste budget or mislead reasoning.
Review imported knowledge and verify effects.

Source raw records and run exports may contain target data, outputs and secrets.
They are private local records, not automatically redacted public writeups. Heuristic
memory redaction does not guarantee safe publication. External model and embedding
endpoints receive their input context; assess their privacy terms yourself.

The implementation is POSIX-specific and uses one control-plane process with a
SQLite store. There is no multi-tenant isolation, automatic high availability,
queue-based paid job recovery, encrypted data-at-rest layer or production security
audit. An interrupted external operation may need manual inspection. Do not
interpret the unit tests as a penetration test or a verified sandbox guarantee.
