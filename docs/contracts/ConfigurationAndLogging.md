# Configuration and Logging Contract

## Configuration sources and precedence

The MVP reads only local YAML configuration. The expected version-controlled
files are:

```text
config/
├── app.yaml
├── models.yaml
├── context.yaml
├── memory.yaml
├── validation.yaml
└── logging.yaml
```

Precedence, from highest to lowest, is:

1. Explicit process environment overrides named `CONTEXT_FOR_AI__<SECTION>__<KEY>`.
2. A local `.env` file used only to populate `CONTEXT_FOR_AI_ENV` and
   `CONTEXT_FOR_AI_CONFIG_DIR` before YAML loading.
3. The six YAML files above.
4. The explicit defaults in this document.

## Bootstrap environment, configuration directory, and paths

Bootstrap uses the following deterministic sequence before QML starts:

1. Resolve the **application root**. In a source checkout, it is the nearest
   ancestor of the entry module containing `pyproject.toml`; if none exists,
   it is the resolved parent directory of the executable. This is not the
   process working directory.
2. Read at most `<application-root>/.env`. Its syntax is UTF-8 `KEY=VALUE`
   lines; blank lines and lines beginning with `#` are ignored. It may contain
   only `CONTEXT_FOR_AI_ENV` and `CONTEXT_FOR_AI_CONFIG_DIR`. An unknown,
   duplicated, or malformed bootstrap entry is a `ConfigurationError`.
3. An explicitly supplied process environment value always wins over the `.env`
   value. `.env` only fills a missing bootstrap value; it never supplies a
   `CONTEXT_FOR_AI__...` override.
4. `CONTEXT_FOR_AI_CONFIG_DIR` selects the directory containing exactly the six
   required YAML files. Its default is `<application-root>/config`. A relative
   value is resolved against the application root, normalized to an absolute
   local path, and must exist as a directory. Missing files, a non-directory,
   or a non-local/empty value is a `ConfigurationError`.
5. Parse the six YAML files, apply allowed explicit process overrides, then
   validate the resulting configuration as one object. `app.data_directory` and
   `logging.directory` resolve relative to the resolved configuration directory;
   absolute values remain absolute. No other path is resolved relative to the
   process working directory.

`CONTEXT_FOR_AI_ENV` is a bootstrap expectation, not a filename selector and
does not select a second configuration profile. Its allowed values are
`development`, `test`, and `production`; its default is `development`. After
all allowed overrides are applied, it must equal `app.environment`. A mismatch
is a `ConfigurationError`. This makes the runtime label explicit while retaining
one deterministic six-file configuration set.

An explicit process override has exactly three non-empty, uppercase components:
`CONTEXT_FOR_AI__SECTION__KEY`. `SECTION` is one of `APP`, `MODEL`, `CONTEXT`,
`VALIDATION`, or `LOGGING`; only these scalar paths are allowed:

```text
APP:        ENVIRONMENT, DATA_DIRECTORY
MODEL:      NAME, BASE_URL, CONTEXT_WINDOW_TOKENS,
            REQUEST_TIMEOUT_SECONDS, TEMPERATURE
CONTEXT:    MAXIMUM_PROMPT_TOKENS, RESERVED_RESPONSE_TOKENS,
            RECENT_MESSAGE_LIMIT, RETRIEVED_MEMORY_LIMIT,
            MINIMUM_RELEVANCE_SCORE
VALIDATION: MAX_REVISIONS
LOGGING:    LEVEL, DIRECTORY, RETENTION_DAYS
```

Rule lists/maps, fixed MVP values, all `MEMORY` keys, and unknown/malformed
override names cannot be overridden and cause `ConfigurationError`. Overrides
are parsed only as the target scalar type: base-10 integer; finite base-10
decimal; lowercase `true`/`false`; canonical enum/string; or non-empty path.
Whitespace is trimmed before parsing. Empty values, JSON/YAML collections,
`null`, `NaN`, infinities, invalid booleans, and values outside the documented
range are rejected. Path overrides use the same configuration-directory base as
their YAML counterparts. The configuration fingerprint is calculated after
coercion, path resolution, override application, and full validation.

SQLite `settings` are non-secret UI preferences only and never override model,
storage, validation, security, or logging configuration. Unknown keys, missing
required keys, invalid enum values, invalid ranges, and conflicting limits are
startup `ConfigurationError`s. The error identifies the file/key and expected
shape without revealing secrets or full message content.

The only editable SQLite settings keys in MVP are `ui.theme`
(`SYSTEM`, `LIGHT`, or `DARK`), `ui.context_panel_visible` (boolean), and
`ui.last_selected_conversation_id` (UUID or null). They affect presentation
only. Every other settings key is rejected; these settings never alter YAML
behavior or create an active-project source of truth.

## Required YAML schema

### `app.yaml`

```text
app:
  environment: development | test | production       # default development
  data_directory: relative-or-absolute-local-path    # required
  foreground_run_limit: 1                            # fixed global MVP value
```

### `models.yaml`

```text
model:
  provider: ollama                                  # fixed MVP value
  base_url: http://<numeric-loopback>:<port>        # required
  name: local-ollama-model-reference                # required
  context_window_tokens: integer >= 1024            # required
  request_timeout_seconds: integer 1..300           # default 60
  temperature: number 0.0..2.0                      # default 0.0
```

`model.base_url` is valid only when all of these are true:

- it is an absolute URL whose scheme is exactly lowercase `http`;
- its host is a numeric IPv4 or IPv6 literal that parses as loopback;
- an IPv6 literal uses the URL-required bracketed serialization;
- its port is explicit and in `1..65535`;
- its path is empty or `/`, which normalizes to the endpoint root; and
- user information, query, fragment, IPv6 zone identifier, encoded-host form,
  and every other URL component are absent.

DNS names, including `localhost`, non-loopback addresses, wildcard/listen
addresses, Unix-socket URL forms, HTTPS, and cloud URLs are rejected. Reverse
proxies and tunnels cannot be distinguished from a numeric URL by static parsing,
so they are explicitly unsupported: the configured address must identify the
Ollama daemon directly. The normalized value retains only `http`, the numeric
loopback address, and the explicit port.

`model.name` uses the narrow MVP `model[:tag]` form with optional namespace path.
It is parsed as follows:

- the string is non-empty and contains no whitespace or control character;
- splitting on `/` produces only non-empty segments;
- `:` may occur only in the final segment and may occur there at most once;
- when `:` is present, both its model portion and tag are non-empty; and
- when it is absent, normalization appends `:latest` to the final segment.

`model_tag` is the explicit or inserted suffix. No other normalization occurs.
The explicit `cloud` tag and any tag ending in `-cloud` are rejected. That
denylist comparison is ASCII case-insensitive and is defense in depth, not the
proof of locality; accepted identities otherwise remain case-sensitive and
unchanged. The loader does not resolve an alias, expand a registry/namespace,
download a model, or select a different tag.

The loader rejects provider values other than `ollama`. There is no API key,
authorization, proxy, cloud-provider, fallback-provider, or local-only bypass
field or override in MVP; the existing unknown-key rule rejects attempts to add
one. Local-only behavior is a fixed invariant, not a configurable preference.

After all configuration is validated, the loader returns one immutable normalized
model configuration containing the endpoint, model identity, and generation
settings. It performs no Ollama network I/O. Only an outer composition boundary
may pass the normalized endpoint and model identity to the Ollama adapter
constructor. Per-call generation settings remain authoritative only in the final
TASK-0011 `GenerationRequest`; the adapter constructor does not retain a second
settings copy. The adapter must not re-read YAML, `.env`, process overrides,
`OLLAMA_HOST`, proxy variables, or ambient credentials.

The separately installed Ollama daemon must use its native cloud-disable setting.
This is a runtime prerequisite rather than another application configuration
field. `OllamaAdapter.md` defines the uncached runtime attestation that verifies
the daemon before any prompt is sent; successful static validation alone never
claims that the daemon is healthy, cloud-disabled, or has the configured model.

### `context.yaml`

```text
context:
  tokenizer_estimator: conservative_utf8_v1         # fixed MVP value
  maximum_prompt_tokens: integer >= 256             # required
  reserved_response_tokens: integer >= 128          # default 512
  recent_message_limit: integer 1..100              # default 20
  retrieved_memory_limit: integer 0..50             # default 12
  minimum_relevance_score: number 0.0..1.0          # default 0.35
  topic_stack_limit: 10                             # fixed MVP value
  rule_set_version: non-empty-string                # required
  conditional_grammar_version: mvp-condition-v1     # fixed MVP value
  intent_rules:
    - id: unique-non-empty-string
      intent: canonical supported IntentType
      output_type: optional permitted OutputType override
      phrases: [non-empty-normalized-string, ...]
      priority: integer 1..100
  qualifier_rules:
    - id: unique-non-empty-string
      qualifier: canonical QualifierKind
      phrases: [non-empty-normalized-string, ...]
```

`maximum_prompt_tokens + reserved_response_tokens` must not exceed
`model.context_window_tokens`. Every shipped configuration must include at
least one intent rule for each supported intent except `UNSUPPORTED`. An intent
rule's optional `output_type` may only use the permitted override shown in
`DomainAndDecisionRules.md`; absent means that document's default mapping.
IDs are unique across each rule list, phrases are case-folded before matching,
and a duplicate normalized phrase at the same priority for different intents is
a `ConfigurationError`. A qualifier can occur in several rules only when the
phrases differ. Rule files are configuration, not user-editable SQLite settings.

## Complete-configuration validation coverage

A valid MVP configuration contains all six files, exactly the documented root
section in each file, every required field, and no unknown key at any level.
Validation covers every MVP configuration kind, not only primitive ranges:

- `app`, `model`, `context`, `memory`, `validation`, and `logging` values must
  satisfy their documented type, fixed-value, cross-field, and path rules.
- `context.intent_rules` must contain at least one valid rule for each supported
  `IntentType` other than `UNSUPPORTED`.
- `context.qualifier_rules` must contain at least one valid rule for every
  `QualifierKind` and must include these baseline normalized phrases:
  `ONLY: only`; `EXACTLY: exactly`; `APPROXIMATE: roughly, could, might`;
  `PROHIBITION: do not`; `PRESERVATION: without changing`;
  `SUBSTITUTION: instead of`; `PRIOR_REFERENCE: same as before`; and
  `SEQUENTIAL: one at a time`. Additional phrases are allowed only when they
  use the same canonical qualifier effect.
- `validation.output_shape_rules` must contain exactly one rule for every
  model-eligible `OutputType`; preserve verbs and action markers must include
  their required baseline values.
- `model.provider`, tokenizer estimator, conditional grammar, foreground-run
  limit, and manual-memory flags must equal their fixed MVP values.

The loader reports the first deterministic validation failure by file and key
without logging secret values or content.

### `memory.yaml`

```text
memory:
  allow_manual_create: true                         # fixed MVP value
  allow_manual_edit: true                           # fixed MVP value
  allow_manual_soft_delete: true                    # fixed MVP value
  automatic_mutation: false                         # fixed MVP value
```

### `validation.yaml`

```text
validation:
  max_revisions: integer 0..2                       # default 2
  rule_set_version: non-empty-string                # required
  output_shape_rules:
    - id: unique-non-empty-string
      output_type: TEXT_ANSWER | TEXT_EXPLANATION | TEXT_DESCRIPTION |
                   TEXT_PLAN | TEXT_ANALYSIS | TEXT_CODE | TEXT_COMPARISON
      shape: NON_EMPTY_TEXT | NUMBERED_LIST | FENCED_CODE | COMPARISON_LIST
  preserve_change_verb_list_id: unique-non-empty-string
  preserve_change_verbs: [normalized-lowercase-token, ...]
  action_markers: [literal-uppercase-marker, ...]
```

Exactly one output-shape rule is required for every listed model-eligible
`OutputType`; `CLARIFICATION` and `CONTROLLED_FAILURE` are application-produced
and have no model shape rule. The shipped baseline maps `TEXT_PLAN` to
`NUMBERED_LIST`, `TEXT_CODE` to `FENCED_CODE`, `TEXT_COMPARISON` to
`COMPARISON_LIST`, and the other four output types to `NON_EMPTY_TEXT`.
`preserve_change_verbs` is a non-empty unique list and must include `add`,
`remove`, `replace`, `change`, `modify`, `delete`, and `move`.
`action_markers` is a non-empty unique list and must include `TOOL_CALL:`,
`ACTION_EXECUTED:`, and `IMAGE_RESULT:`. Both lists are normalized/validated at
startup and their IDs/values are included in the configuration fingerprint.

### `logging.yaml`

```text
logging:
  level: DEBUG | INFO | WARNING | ERROR             # default INFO
  directory: relative-or-absolute-local-path        # required
  retention_days: integer 1..365                    # default 30
  include_content: false                            # fixed MVP value
```

The configuration loader produces a configuration fingerprint from normalized
non-secret settings. Packets, processing runs, and trace events record it.

## Structured trace events

Every event has:

```text
timestamp, level, event_name, stage, configuration_fingerprint,
conversation_id, user_message_id, processing_run_id, context_packet_id,
model_request_id, model_response_id, validation_result_id,
clarification_request_id, memory_id, memory_revision_id,
correction_attempt_number, error_type
```

Fields not yet known are null; correlation fields are added, never replaced.
Required event names are `run_accepted`, `context_built`, `reference_resolved`,
`constraints_resolved`, `retrieval_completed`, `packet_built`,
`model_request_started`, `model_request_finished`, `validation_completed`,
`correction_started`, `run_succeeded`, `run_clarification`, `run_failed`,
`recovery_started`, `recovery_resumed`, `recovery_completed`, `memory_created`,
`memory_edited`, and `memory_soft_deleted`.

The canonical inward port is exactly `TraceLogger.emit(TraceEvent)`. A concrete
adapter serializes that value; it does not expose a competing `.event(...)`
application contract or infer correlation from ambient state. `stage` uses
`PipelineStage`. For TASK-0014 events, `error_type` is a canonical
`FailureCode` or null, never an exception class/name or provider diagnostic.
The three memory correlation fields are required for their matching memory
events and null otherwise.

### TASK-0014 event matrix

In this matrix, `C/U/R/P/Q/S/V/L/A` mean non-null `conversation_id`,
`user_message_id`, `processing_run_id`, `context_packet_id`,
`model_request_id`, `model_response_id`, `validation_result_id`,
`clarification_request_id`, and `correction_attempt_number` respectively. Every
row also has non-null timestamp, level, stage, event name, and configuration
fingerprint. Correlation values are the durable IDs owned by that run; all
unlisted correlation fields are null unless the row explicitly permits an
already-known later ID.

`configuration_fingerprint` is the immutable current execution snapshot. It
equals the run/packet fingerprint on ordinary and resumable paths. For the
`CONFIGURATION_CHANGED` recovery branch it is the current fingerprint; the
different stored run fingerprint appears only in the redacted failure details.

| Event | Emit condition | Stage | Required correlation | `error_type` |
|---|---|---|---|---|
| `run_accepted` | Acceptance transaction committed a new message/run. | `ACCEPTANCE` | `C,U,R` | null |
| `context_built` | A joined context transaction committed its authoritative interpretation/clarification projection. | `CONTEXT` | `C,U,R`; add `P` on packet success | null |
| `reference_resolved` | The reference phase ran and its encompassing context/clarification transaction committed, including a zero-mention outcome. | `CONTEXT` | `C,U,R`; add `P` on packet success | null |
| `constraints_resolved` | The constraint phase ran and its encompassing context/clarification transaction committed. | `CONTEXT` | `C,U,R`; add `P` on packet success | null |
| `retrieval_completed` | Successful packet context transaction committed retrieval selection/exclusion evidence. | `CONTEXT` | `C,U,R,P` | null |
| `packet_built` | Successful packet context transaction committed the immutable packet and `CONTEXT_READY`. | `CONTEXT` | `C,U,R,P` | null |
| `model_request_started` | Claim transaction committed `IN_FLIGHT`, immediately before gateway entry. | `REQUEST` | `C,U,R,P,Q`; add `A` for revision | null |
| `model_request_finished` | Candidate transaction committed a completed response, or transport transaction committed a terminal gateway failure. | `TRANSPORT` | `C,U,R,P,Q`; add `S` for completed generation; add `A` for revision | null for completed generation; mapped gateway `FailureCode` otherwise |
| `validation_completed` | Candidate transaction committed the exact report. | `VALIDATION` | `C,U,R,P,Q,S,V`; add `A` for revision | null |
| `correction_started` | Revision request/correction transaction committed. `Q` is the new request; `S/V` identify the immediately failed candidate/report. | `CORRECTION` | `C,U,R,P,Q,S,V,A` | null |
| `run_succeeded` | Assistant-link terminal transaction committed. | `TERMINALIZATION` | `C,U,R,P,Q,S,V`; add `A` for a successful revision | null |
| `run_clarification` | Clarification context transaction committed. | `CONTEXT` | `C,U,R,L` | null |
| `run_failed` | Any terminal `CONTROLLED_FAILURE`, `FAILED`, or `CANCELLED` transaction committed. | exactly the persisted `SafeFailure.stage` | `C,U,R`; add every durable `P/Q/S/V/A` applicable to the failure | exactly `SafeFailure.error_code` |
| `recovery_started` | Recovery loaded/classified the one active run and validated enough lineage to identify it. | `RECOVERY` | `C,U,R`; add every durable artifact ID already known | null |
| `recovery_resumed` | Fingerprint/lineage matched a resumable matrix row, immediately before its first bounded foreground action. | `RECOVERY` | `C,U,R`; add every durable artifact ID already known | null |
| `recovery_completed` | An active-run recovery invocation is about to return, after any normal terminal event. | `RECOVERY` | `C,U,R`; add every final durable artifact ID | null for success/clarification; terminal outcome code or `PERSISTENCE_ERROR` otherwise |

`context_built`, `reference_resolved`, and `constraints_resolved` are emitted
only for phases that ran and whose enclosing transaction committed. A generic
context failure or rolled-back CAS attempt therefore emits none of those phase
events; its committed terminal transaction emits only `run_failed`. Initial
budget failure likewise emits `run_failed`; it does not claim a packet or
retrieval commit. A clarification emits the completed phase events in phase
order and then `run_clarification`, with no packet/retrieval event.

For every new submission, event order is:

```text
run_accepted
-> [context_built -> reference_resolved -> constraints_resolved]
-> [retrieval_completed -> packet_built]
-> per attempt [model_request_started -> model_request_finished
                -> validation_completed -> correction_started?]
-> run_succeeded | run_clarification | run_failed
```

Brackets contain only phases that ran and durably committed. Multiple events
after the same commit are emitted in the displayed order. A gateway failure
emits `model_request_finished` before `run_failed`; validation exhaustion emits
`validation_completed` before `run_failed`; a correction-render failure emits
`validation_completed` before `run_failed` and no `correction_started`.

Active-run recovery order is:

```text
recovery_started
-> recovery_resumed?
-> applicable normal stage/terminal events
-> recovery_completed
```

`recovery_resumed` is absent for configuration mismatch, an uncertain
`IN_FLIGHT` request, or an impossible durable state because those branches are
terminalized rather than resumed. It is present for every matrix row that
continues deterministic context, starts a not-yet-sent request, reconstructs a
correction, or repeats only an idempotent terminal transaction.

The read-only `recovery_started`/`recovery_resumed` observations are the only
events not caused by a preceding write commit. Every mutation event is emitted
after its outermost commit. `recovery_completed` describes completion of the
foreground invocation; if terminalization could not be persisted it carries
`PERSISTENCE_ERROR` but no `run_failed` event is emitted.

No TASK-0014 event is emitted for `ExistingRunResult`, `BusyResult`,
pre-acceptance cancellation/configuration/persistence failure, a rolled-back
admission loser before its read-only reclassification, or
`NoRecoveryRequiredResult`. These outcomes create no new durable lifecycle
fact.

Trace emission is best-effort and outside database transactions. Failure of
`TraceLogger.emit` cannot roll back durable work, change a public use-case
result, create a retry, or cause content to be logged through a fallback. A
logger that cannot be configured at startup remains a startup configuration
failure; an individual post-commit adapter write failure is contained at the
application trace boundary.

Routine log output must never include original message text, rendered prompts,
model responses, raw provider bodies or exceptions, endpoint URLs, request or
response headers, API keys, authorization data, cookies, full configuration, or
raw memory content. Database trace records retain the data required by the
schema; logs retain identifiers, safe error codes, lengths, hashes, normalized
allowlisted provider metadata, and rule IDs only.

## Startup and test behavior

Configuration validates before the QML window opens. Tests use isolated fixture
directories and explicit environment mappings. A valid fixture must load all
six files; an invalid fixture must name the failed file/key and produce a typed
`ConfigurationError`. No test reads a developer's `.env` or user data path.
