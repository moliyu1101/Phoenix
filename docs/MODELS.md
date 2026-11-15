# Direct model profiles

The runtime supports two explicit transports: Chat Completions-compatible tool
calling and Anthropic Messages tool use. A generic base URL alone is not enough:
the endpoint must implement the selected protocol and the configured model must
support tools. Streaming generation and the OpenAI Responses API are not implemented.

The YAML `default` profile may be overridden by `PHOENIX_MODEL` and
`PHOENIX_BASE_URL`. Other profiles use their YAML fields. All credentials are looked
up by the specified environment-variable name; do not write secrets into YAML.

Example structure (replace every placeholder with real values):

```yaml
profiles:
  default:
    protocol: chat
    base_url: https://your-provider.example/v1
    model: YOUR_SOLVER_MODEL
    api_key_env: PHOENIX_API_KEY
    context_tokens: 65536
    output_tokens: 4096
    chat_token_parameter: max_tokens
  planning:
    protocol: anthropic
    base_url: https://your-messages-endpoint.example/v1
    model: YOUR_PLANNER_MODEL
    api_key_env: PHOENIX_PLANNER_KEY
    context_tokens: 65536
    output_tokens: 4096
roles:
  planner: planning
  analyst: default
  solver: default
  reviewer: planning
  distiller: planning
```

Merge this structure into `config.yaml`; keep the other deployment settings.
Set `PHOENIX_PLANNER_KEY` in `.env` in addition to any default key. No specific
commercial model, subscription, endpoint quota or current price is assumed.

## Protocol details

Chat tool IDs and arguments are persisted, and supported response extensions such
as `reasoning_content` are replayed with the assistant turn. Anthropic tool-use and
signed content blocks are kept for replay; consecutive tool results are combined
into a compatible user-content message. Malformed arguments fail explicitly.

Requests do not follow redirects or blindly retry. Provider response errors are
reported by status rather than dumping arbitrary secret-bearing debug payloads.
Protocol shape tests use mocked HTTP responses, not paid live provider calls.
Provider-specific authentication extras, prompt caches, reasoning controls and
structured-output negotiation may need additional adapters.

## Token and money accounting

Set the actual input/output prices in USD per million tokens for every role you
plan to run before enabling a USD cap. The ledger is based on these configuration
values and the provider's usage report; it is not an invoice guarantee. Caching,
reasoning-token billing and endpoint-specific price tiers may differ. An absent
usage report holds a conservative reservation and marks the call uncertain.

Before each call, a conservative UTF-8-byte estimate includes messages and tool
schemas, plus the requested output budget. This can reject a call earlier than a
vendor tokenizer would. Increase the configured window only to a window the model
actually supports; do not defeat the check by setting an imaginary context size.

## Diagnostics

`python -m phoenix doctor` prints Python/SQLite versions, Docker CLI presence and
redacted profiles. It deliberately does not claim model connectivity or container
readiness. Starting a real challenge is a chargeable operation. Begin with a small
authorized local exercise and inspect native events and errors before a contest.

## Native settings UI

The settings page can persist model profiles, role routing, Worker profiles and
Phoenix model credentials. It does not make model calls when saving. Overrides
are stored in data_dir/operator-config.json and applied after YAML/environment
model overrides on restart. Credentials live in data_dir/model-credentials.json
(mode 0600) and are never returned by the API. A blank password field keeps the
existing key. Existing live runs must finish before shared configuration changes.
To return to YAML-owned configuration, stop the API, back up and remove the
operator override files, and restart. Keep the original model environment values
consistent with the UI overrides. Web tokens and network settings are not editable
through this endpoint.
