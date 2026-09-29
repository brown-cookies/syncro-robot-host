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

Every accepted interaction receives a `trace_id`.

All events belonging to that interaction use the same `trace_id`.

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

---

### FR-O8 — Action Execution

Action handling must distinguish:

```text
action_selected
action_started
action_completed
action_failed
```

This must make it possible to distinguish a correct decision from a failed action execution.

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
action execution
```

Elapsed durations must use a monotonic clock.

The existing `decision_trace.latency_ms` remains the authoritative interaction-latency field.

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
action_started
action_completed
action_failed
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

Safe diagnostic metadata may include:

```text
input_length
input_hash
input_type
```

Redaction is centralized rather than implemented separately by each component.

---

## 8. Sinks and Configuration

The first implementation supports:

```text
console
file
```

Configuration:

```text
LOG_LEVEL=INFO
LOG_OUTPUT=console
LOG_FILE_PATH=<optional>
```

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
→ selected action
→ action result
→ failure location
→ timing
```

without relying on unrelated `print()` statements or a centralized observability platform.
