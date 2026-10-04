# Host Specification: SYNCRO Observability and Logging

## 1. Purpose

This specification defines the minimum observability and logging layer for the SYNCRO Host AI Server.

The implementation must let a developer reconstruct one interaction using its `trace_id`:

```text
input
→ pipeline stages
→ important state
→ model result
→ decision / branch
→ action
→ result / failure
→ timing
```

This is a **development and debugging** capability only.

It does not introduce centralized telemetry, dashboards, alerting, OpenTelemetry, or remote log collection.

---

## 2. Architecture

Observability is a shared host-side service used by the existing application components.

```text
Host Component
      ↓
Observability API
      ↓
Structured Event
      ↓
Console / File Sink
```

Observability must never determine or modify functional behavior.

A logging failure must not cause a successful host operation to fail.

---

## 3. Required Observability

The first implementation covers:

1. Interaction correlation
2. Input boundary
3. Pipeline stage lifecycle
4. Important state transitions
5. Model results
6. Decision / branch selection
7. Action execution
8. Errors
9. Timing
10. Redaction

Components must log only explicitly selected diagnostic fields. Entire application state must not be serialized automatically.

---

## 4. Functional Requirements

### FR-O1 — Trace Correlation

Every accepted interaction receives exactly one `trace_id`.

The `trace_id` is minted once, at interaction start, by `InteractionRunner.run`. It is threaded through `DialogueState` and is the same value persisted as `decision_trace.trace_id`. No component may mint a second identifier for the same interaction. In particular, the output node reads `state["trace_id"]` and must not generate its own.

All events belonging to that interaction use the same `trace_id`, including events emitted before the graph runs and events emitted when the interaction fails.

A degraded trace written for a failed interaction reuses that interaction's `trace_id`.

Transport-originated failures that happen before `run()` is reached (`session_timeout`, `queue_overflow`) use a `trace_id` minted by the transport when it accepted the interaction. `InteractionRunner.run` and `persist_transport_degraded_trace` accept that `trace_id` as an optional argument and mint one only when none is supplied.

Existing `session_id` must be preserved when available.

---

### FR-O2 — Event Identity

Every event must contain a unique `event_id`.

---

### FR-O3 — Structured Events

Events must be machine-readable structured records.

Required fields:

```text
event_id
trace_id
timestamp
component
event_type
severity
status
metadata
```

Optional fields:

```text
session_id
duration_ms
parent_event_id
error
```

---

### FR-O4 — Stage Lifecycle

Every instrumented pipeline stage must emit:

```text
stage_started
stage_completed
stage_failed
```

`stage_skipped` may be used when a stage is intentionally bypassed.

Completed and failed stage events must include `duration_ms`.

`stage_failed` is emitted when a stage raises. The instrumentation records the failure and re-raises the original exception unchanged. It must not swallow, wrap, or alter stage exceptions.

---

### FR-O5 — Important State

Each instrumented stage defines its own observability boundary:

```text
input
→ normalized state
→ processing
→ output
```

Only fields needed for debugging are recorded.

**Variable tracing.** For debugger-style inspection, a component may emit `state_snapshot` at explicit points, naming the variables to watch (`snapshot`) or the keys whose values changed across a step (`diff`). Rules:

```text
severity is always DEBUG; the call is a no-op above DEBUG
only explicitly named variables/keys are recorded, never whole state
the source location (file:line function) is recorded as `callsite`
string values are hash-only (length + hash) by type, regardless of variable name,
  unless the caller marks the name as `plain` or full text is enabled (Section 7)
credentials get no length or hash
automatic tracing of arbitrary locals (e.g. sys.settrace) is not permitted
```

---

### FR-O6 — Model Observability

Where available, model events record:

```text
model_name
model_version
prediction
confidence / score
inference_duration_ms
outcome
```

Raw model inputs are not logged unless explicitly classified as safe.

---

### FR-O7 — Decision / Branch

Decision events record:

```text
decision / branch
selected rule
selected action
reason_code
relevant decision inputs
```

Logs must contain decision metadata, not private reasoning or chain-of-thought.

The mutation-claim guard in the LLM stage emits `branch_selected` with rule `mutation_claim_guard` and `reason_code` of `claim_rewritten` or `passed_through`. A rewrite is logged at WARNING. The guard's input and output text follow the redaction policy in Section 7.

---

### FR-O8 — Action Selection and Execution

Current scope: the host selects actions but does not execute them. The LLM stage sets `proposed_action`, and the policy stage sets `action_taken` (`deliver`, `defer`, `soften`, `break_prompt`, `suppress`). No component adds, reschedules, snoozes, or dismisses anything as a result.

Therefore only `action_selected` is emitted today. It is emitted by the policy stage and records `proposed_action`, `action_taken`, and `policy_rule`.

`action_started`, `action_completed`, and `action_failed` are **reserved**. They stay in the event vocabulary but must not be emitted until an action executor exists. When one is introduced it must emit them, and this section must be revised so that a correct decision can be told apart from a failed execution.

---

### FR-O9 — Errors

Failure events record, where available:

```text
error_type
error_code
component
operation
message
recoverable
retry_count
```

Unexpected exceptions must preserve useful diagnostic information.

Stack traces remain in diagnostic logs and must not be exposed through user-facing responses.

---

### FR-O10 — Timing

The implementation measures:

```text
interaction
pipeline stage
model inference
action execution (reserved, see FR-O8)
```

Elapsed durations must use a monotonic clock.

Instrumentation wraps existing timing; it does not replace it. `stage_timings_s`, `stage_durations_s`, and `decision_trace.latency_ms` remain as they are and continue to feed latency measurement. Each duration is read from the clock once, and that same value is used for both the existing timing field and the event's `duration_ms`, so the two cannot disagree.

`decision_trace.latency_ms` remains the authoritative interaction-latency field. `interaction_completed` carries `latency_ms` and `latency_basis` in its metadata so detailed event timing can be related to it by `trace_id`. Event `duration_ms` values are diagnostic and never substitute for it.

`HostPipeline` (the WP-102 host-only path) is out of scope for the first implementation. The dialogue graph is the instrumented path.

---

### FR-O11 — Degradation

A degradation is a reduced-mode outcome that the host handles rather than failing outright.

Every applied degradation emits `degradation_applied` at WARNING severity, at the point the degradation is decided. `metadata.reason_code` must be a value from the existing `DegradationReason` contract in `pipeline/contracts.py`. Observability introduces no new reason strings.

This event is emitted in addition to, not instead of, the stage's own lifecycle events. A degradation that also fails the interaction additionally emits `interaction_failed`.

Initial instrumented degradations:

```text
affect_detector_failure   affect stage falls back after a detector failure
tts_timeout               runner falls back to text (replaces the console print)
pipeline_failure          interaction-boundary failure, degraded trace written
session_timeout           transport
queue_overflow            transport
```

---

## 5. Event Contract

Canonical event shape:

```json
{
  "event_id": "uuid",
  "trace_id": "uuid",
  "session_id": "uuid",
  "timestamp": "ISO-8601 datetime",
  "component": "policy",
  "event_type": "branch_selected",
  "severity": "INFO",
  "status": "success",
  "duration_ms": 12.4,
  "metadata": {},
  "error": null
}
```

Initial event vocabulary:

```text
interaction_started
interaction_completed
interaction_failed

input_received
input_rejected

stage_started
stage_completed
stage_failed
stage_skipped

model_inference_started
model_inference_completed
model_inference_failed

decision_evaluated
branch_selected

action_selected
action_started        (reserved, see FR-O8)
action_completed      (reserved, see FR-O8)
action_failed         (reserved, see FR-O8)

degradation_applied

state_snapshot         (FR-O5, DEBUG only)
```

Existing host-defined network events remain unchanged.

New event types require review rather than ad-hoc strings.

---

## 6. Logging

Severity levels:

```text
DEBUG     developer diagnostics
INFO      normal lifecycle / state transitions
WARNING   recoverable abnormal condition
ERROR     operation failure
CRITICAL  host-level failure
```

Logs must be sufficient to reconstruct:

```text
trace
→ input
→ stages
→ outputs
→ model result
→ decision
→ action
→ final result
```

---

## 7. Redaction and Data Safety

Redaction occurs before events reach a sink.

The following must not be logged directly:

```text
credentials
tokens
secrets
authorization values
passwords
raw participant audio
```

Sensitive text and unrestricted prompts/responses must not be logged by default.

**Default (hash-only).** Events carry safe diagnostic metadata instead of text:

```text
input_length
input_hash
input_type
transcript_length / transcript_hash
final_response_length / final_response_hash
```

A hash is the SHA-256 hex digest of the UTF-8 text, truncated to 16 hex characters.

**Full text (opt-in).** `transcript` and `final_response` may be logged in full only when **both** conditions hold:

```text
LOG_LEVEL=DEBUG
LOG_INCLUDE_TEXT=true      (default: false)
```

Either condition alone is insufficient. When enabled, full text appears only on DEBUG events, and credential/secret/token redaction still applies to it. Raw audio and unrestricted LLM prompts are never logged, regardless of the flag.

Degradations and guard decisions must be diagnosable from `reason_code` plus the hashes alone, without text.

Redaction is centralized rather than implemented separately by each component.

---

## 8. Sinks and Configuration

The first implementation supports:

```text
console
file
```

Configuration is read through `Settings.from_env` and documented in `.env.example`. Keys are unprefixed, matching existing settings such as `HOST_ADDRESS` and `DB_PATH`. `Settings.log_level` already exists and is reused.

```text
LOG_LEVEL=INFO
LOG_OUTPUT=console          console | file
LOG_FILE_PATH=./logs/syncro-events.jsonl    used when LOG_OUTPUT=file
LOG_INCLUDE_TEXT=false
```

If `LOG_OUTPUT=file` and `LOG_FILE_PATH` is missing or unwritable, observability falls back to console and emits a WARNING. It does not fail host startup (Section 9).

Console and file output must use the same structured event schema.

No external telemetry service is required.

---

## 9. Failure Behavior

Observability is non-blocking.

If a sink fails:

```text
application result remains authoritative
observability failure must not fail the interaction
```

If a diagnostic event cannot be safely emitted, it may be reduced to safe metadata or dropped.

A missing telemetry event must never create a second application failure.

---

## 10. Verification

The implementation is verified by confirming that:

1. One interaction produces a consistent `trace_id`.
2. Instrumented stages emit start and completion/failure events.
3. Stage and model durations are recorded.
4. Model results and decision branches are observable.
5. Selected actions are distinguishable from executed actions.
6. Failures produce structured error information.
7. Secrets and raw audio are not logged.
8. `LOG_LEVEL` is respected.
9. File and console sinks use the same schema.
10. A failed log destination does not break the host.
11. One trace can reconstruct the complete interaction.
12. Detailed timing can be related to `decision_trace.latency_ms`.
13. The `trace_id` on events equals `decision_trace.trace_id` for the same interaction, and the output node does not generate its own.
14. An interaction that fails before the graph produces a `trace_id`, and its degraded trace reuses it.
15. The affect fallback emits a WARNING `degradation_applied` event with `reason_code=affect_detector_failure`.
16. Transcript and response text are absent from events by default, and present only with `LOG_LEVEL=DEBUG` and `LOG_INCLUDE_TEXT=true` together.
17. `action_started`, `action_completed`, and `action_failed` are never emitted while no executor exists.
18. For each stage, the event `duration_ms` equals the matching `stage_timings_s` value.
19. `state_snapshot` events appear only at `LOG_LEVEL=DEBUG`, record only the named variables, and contain no raw string values unless marked `plain` or full text is enabled.

---

## 11. Out of Scope

The following are deferred:

```text
centralized log collection
dashboards / alerting
OpenTelemetry
distributed tracing backends
remote log shipping
metrics infrastructure
long-term telemetry storage
advanced sampling / anomaly detection
action executor events (until an executor exists)
HostPipeline (WP-102 path) instrumentation
```

These require a separate specification and implementation when needed.

---

## 12. Acceptance Definition

OBS-LOG is complete when a developer can take one `trace_id` and reconstruct:

```text
what entered the host
→ what stages executed
→ important state at stage boundaries
→ model result
→ selected branch / rule
→ selected action (execution result once an executor exists)
→ failure location
→ timing
```

without relying on unrelated `print()` statements or a centralized observability platform.

---

## 13. Revision Log

**Rev 2 (2026-10-05)** resolves review findings before implementation:

1. FR-O1: one `trace_id`, minted at interaction start and shared with `decision_trace`; no second ID.
2. FR-O8: only `action_selected` is live; `action_started`, `action_completed`, and `action_failed` are reserved until an executor exists.
3. Section 7: transcript and response text are hash-only by default; full text needs both `LOG_LEVEL=DEBUG` and `LOG_INCLUDE_TEXT=true`.
4. Section 8 and FR-O10: config goes through `Settings.from_env` and `.env.example`; event timing wraps existing timing rather than replacing it.
5. FR-O11 and Section 5: new `degradation_applied` event (WARNING), initially covering the affect fallback, plus the mutation-claim guard branch in FR-O7.
6. Sequencing: implementation starts after PR #4 lands, since both touch every node file. The `observability/` package itself touches no node files and can begin earlier.
7. `LOG_FILE_PATH` defaults to `./logs/syncro-events.jsonl` (git-ignored); console remains the default output.

**Rev 3 (2026-10-05)** adds debugger-style variable tracing: new `state_snapshot` event and an FR-O5 amendment (explicit `snapshot` / `diff`, DEBUG only, strings hash-only by type, credentials never hashed, no automatic tracing).