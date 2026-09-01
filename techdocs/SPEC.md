# Host Specification: SYNCRO Reasoning Host

This document is the requirements and implementation specification for the
SYNCRO **Host AI Server** — the stationary machine that runs speech-to-text,
context retrieval, LLM reasoning, the affect-to-action decision policy, and
text-to-speech synthesis for the SYNCRO reasoning pipeline. It states WHAT
the host must do, WHAT it must expose over the network, and HOW its
contracts (APIs, message formats, schemas) are shaped, so that it can be
implemented and independently verified against this document. It is derived
from Sections VII–XVI of the SYNCRO thesis paper (Almedejar, Espinosa,
Marimla, 2026); where this document formalizes something the paper only
states in prose, that is noted inline.

This document does **not** cover ML model internals (LLM choice, classifier
architecture, training/validation) — those are out of scope for this spec by
request. It references model *usage* (e.g., "the host calls the LLM via
Ollama") only insofar as that usage shapes the host's own architecture and
contracts.

## Table of Contents

1. Purpose, Deliverable and Out of Scope
2. Architecture Overview
3. Stack Overview
4. Current State of the System
5. Functional Requirements (FR-H1..FR-H14, plus FR-H10a, FR-H11a)
6. API Contracts — HTTP
7. API Contracts — WebSocket
8. Data Contracts and Schemas
9. Database Schema (SQLite ERD)
10. Network Discovery (Host Side)
11. Configuration and Tunables
12. Performance and Measurement Requirements
13. Degraded and Error Conditions
14. Constraints, Conventions and Sources of Truth
15. Manual Verification Checklist
16. Open Items Register

## 1. Purpose, Deliverable and Out of Scope

The deliverable of this spec is the **Host AI Server**: a FastAPI + LangGraph
application, running on a stationary local machine, that receives streamed
audio from the ESP32-S3 edge client, runs the four-node reasoning pipeline
(intent classification, context retrieval, LLM reasoning, affect-to-action
policy), runs the parallel acoustic stress/sentiment detection, and returns a
structured response payload for the edge client to speak and (optionally)
act on.

Out of scope for this spec:

- ML model selection, architecture, training, or validation methodology for
  the LLM, STT engine, wake-word model, or acoustic classifier. This spec
  treats each as an opaque callable with a defined input/output contract.
- Mechanical, electrical, and actuation design of the physical robot
  (explicitly deferred by the source paper to a future robotics-focused
  paper; see Section 4).
- Any behavior that happens entirely on the edge client (firmware, motor
  control, on-device wake-word) — see the companion `robot-runtime-spec.md`.
- Cloud hosting via any commercial or third-party service, or any code path
  that transmits participant data to a party other than the research team
  (excluded by NFR-4/NFR-10 in the source paper; see Section 14 for the
  current data-boundary definition, which permits transmission to the
  team-operated host under the stated in-transit/at-rest/retention
  protections — this is not the local-only-network claim of earlier
  revisions, and this document no longer states that claim as absolute).

## 2. Architecture Overview

The host is one half of a strict **cognitive/somatic split** (source paper,
Section XI.D): the host owns language and reasoning — STT, LLM inference,
affect-policy decisioning, and TTS synthesis — and never issues low-level
actuation instructions. The edge client owns all sensing and actuation,
resolved locally and deterministically, and does not require host
availability to execute local safety/idle behavior.

Pipeline, node by node (source paper Section XV):

```
Raw audio (from edge, streamed) 
        │
        ▼
 Node 1: Intent Classification & Transcription (STT + intent schema)
        │                                   ▲
        ▼                                   │ (parallel, same audio)
 Node 2: Memory & Context Retrieval (SQLite)│
        │                                   │
        ▼                                   │
 Node 3: Ollama LLM Reasoning (draft action) │
        │                          Node 4-parallel:
        ▼                    Acoustic Stress/Sentiment Detection
 Node 4: Emotion & Tone Engine       (openSMILE → classifier → Low/Mod/High)
 (rule-based Affect-to-Action Policy) ◄──────────────┘
        │
        ▼
 Output Payload Assembly (JSON: tts_text, state_tag)
        │
        ▼
 Sent to edge client over WebSocket
```

The host is stateless between interactions except for what is persisted in
SQLite (tasks, routine logs, decision traces, the per-user adaptive
lead-time parameter `L`). Every interaction is scoped to a `user_id` /
`session_id` and produces one decision-trace row (Section 8.3).

## 3. Stack Overview

This section consolidates the host-side software stack into one place,
rather than leaving it scattered across Section 4 (Current State) and
Section 16 (Open Items). It covers **host-side components only** — for the
edge-side stack (firmware environment, board, microphone, amplifier), see
`robot-runtime-spec.md` Section 3. Values below are skeleton placeholders
pending confirmation; per project decision (Section 16), a value is only
removed from the Open Items Register once it is confirmed here, not before.

| Layer | Component | Version/Config | Status |
|-------|-----------|-----------------|--------|
| Host OS | Windows 11 | — | Confirmed |
| Host CPU | AMD Ryzen 7 5700X | — | Confirmed |
| Host RAM | 16 GB DDR4 | — | Confirmed |
| Host GPU | RTX 4060 | 8 GB VRAM, driver 596.21 | Confirmed |
| Host storage | 500 GB | — | Confirmed |
| LLM runtime | Ollama | `llama3.1:8b-instruct-q4_K_M` | Confirmed |
| Orchestration | LangGraph | `v1.2.11` | Skeleton |
| API layer | FastAPI + Uvicorn | `v0.141.1 + v0.52.4` | Skeleton |
| Database | SQLite | `TBC` | Skeleton |
| STT engine | faster-whisper | `small`, int8 | Confirmed |
| Acoustic feature extraction | openSMILE (eGeMAPS set) | `TBC` | Skeleton |
| Acoustic classifier | SVM/MLP, `TBC` | `TBC` | Skeleton |
| TTS | Piper | medium quality tier, `en_US-lessac-medium` | Confirmed |
| Transport | WebSocket over TCP | port **8765** | Confirmed |
| Host endpoint resolution | NVS-provisioned static endpoint | `device_token` auth, no runtime discovery (Section 10) | Confirmed |

This table is a placeholder structure, not a finalized bill of software —
each row is expected to be filled in as its corresponding Open Items
Register entry (Section 16) is resolved. A row's `Status` column is updated
in place when resolved; the row itself is **not** deleted, so this table
remains a single traceable record of what the host stack actually is,
alongside the Section 16 register that tracks what is still open.

## 4. Current State of the System

SYNCRO uses the centralized architecture: one host server, owned and
operated by a team member, serving all participant robots over a
WireGuard tunnel.

- Host: RTX 4060 machine at a team member's residence, serving all
  participants concurrently. This is the only configuration this document
  specifies in Sections 5–16 below.
- NFR-1/NFR-2 apply under N simultaneous participant sessions rather than
  one session per dedicated machine.
- Each participant's day-of task list and timer schedule is cached
  locally on the edge unit (extends FR-12/FR-15). On host
  unreachability, the edge degrades to the D7 fallback path, logging
  `degradation_reason`.

At the time of writing, per the source paper and Section 3:

- Host hardware and OS — Windows 11, AMD Ryzen 7 5700X, 16 GB DDR4, RTX 4060
  (8 GB VRAM, driver 596.21), 500 GB storage — are confirmed (Section 3) as
  the shared host.
- NFR-1 (1–3s warm latency) and NFR-2 (VRAM headroom) remain target
  constraints, not yet measured results — see Section 12. Both need
  evaluation under concurrent-session load, not single-session load. A
  prior harness run against these gates exists but is not carried forward
  in this spec: it benchmarked the wrong STT engine against what Section 3
  now locks, and its VRAM figures were flagged by the run itself as
  possibly polluted by a foreign process at baseline. See Section 16 for
  that history. A clean re-run against the confirmed STT engine
  (faster-whisper), a verified-idle GPU, and concurrent-session load is the
  path to closing NFR-1/NFR-2 out.
- The acoustic stress/sentiment classifier has not yet been benchmarked
  against a validated emotional-speech corpus; its deployment readiness is
  contingent on meeting the macro-F1 ≥ 0.70 gate (NFR-3). If not met, the
  host must still ship, but affect-conditioned behavior should be flagged
  downstream as unvalidated (this is a study-reporting concern, not a host
  code-path requirement, but the host's decision trace must retain enough
  detail — Section 8.3 — for that downgrade to be assessed after the fact).
- Protocol/port details for host-to-edge communication, left as "TBC" in the
  source paper, are resolved in this document (Sections 6, 7). Host
  endpoint handling for the centralized topology is specified in Section 10.

## 5. Functional Requirements

Each requirement is phrased so a reviewer can mark it pass/fail against a
running host. Source FR/NFR references from the paper are given in
parentheses.

- **FR-H1 Voice payload ingestion.** The host accepts a streamed sequence of
  binary audio frames from an authenticated WebSocket session, in order, as
  they arrive per `session_id`, and appends each to that session's audio
  buffer as it lands rather than holding frames back and releasing them as
  one block. This is a transport/buffering obligation, not an
  STT-scheduling one — Section 3's confirmed engine, faster-whisper, is not
  a streaming recognizer, so recognition runs once, on `end_audio`, against
  the fully assembled buffer for that session; it does not begin decoding
  partial audio mid-utterance. What streaming transport still buys, and the
  reason it remains the right choice over HTTP/REST (Section XV), is that
  the network transit of every frame but the last overlaps with the
  participant still speaking, rather than being paid in full only after the
  complete clip is assembled and then sent. Frame ordering and completeness
  within a session are the WebSocket/TCP transport's own guarantee, not
  something the host re-verifies per frame (Section 8.2, closes CC-001) —
  the host simply appends each binary frame's PCM payload to that session's
  buffer as frames arrive, until `end_audio`. Matches
  `robot-runtime-spec.md`'s edge-side behavior (Section 6): the edge sends
  frames as captured, not accumulated into one block, for the same
  transit-overlap reason — not because the host decodes them individually
  as they arrive. (FR-1, FR-5, Section 16 of
  source paper)
- **FR-H2 Speech-to-text.** For every completed utterance, the host produces
  a text transcript using a local (non-cloud) STT engine. (FR-5)
- **FR-H3 Intent classification.** The host classifies the transcript into
  exactly one of `{add_task, reschedule_task, request_summary,
  request_break, dismiss_reminder, snooze_reminder, ask_status}`, with a
  confidence score. `snooze_reminder` carries an extracted slot,
  `snooze_minutes` (integer, required when this intent is classified) —
  without it, Section 11.2's `L_hat = L - s` has no source for `s`. This
  intent, together with `dismiss_reminder`, is one of the two capture paths
  Section 11.2a defines for reminder outcomes; before this revision neither
  intent fed that rule. (FR-3)
- **FR-H4 Low-confidence routing.** If top-intent confidence is below the
  configured threshold (Section 11), the host must route to a clarification
  response rather than executing any action. (FR-4)
- **FR-H5 Context retrieval.** For every interaction, the host queries
  SQLite scoped to the requesting `user_id` and returns: top-k upcoming
  tasks by deadline proximity, the most recent break/routine log entry, and
  any overdue tasks. (FR-6)
- **FR-H6 LLM reasoning.** The host passes classified intent, extracted
  slots, and retrieved context to a locally hosted LLM and receives a draft
  natural-language response and a proposed action. (FR-7)
- **FR-H7 Acoustic affect detection (parallel).** For every utterance, the
  host runs feature extraction + classification on the same raw audio in
  parallel with Nodes 1–3, producing exactly one of `{Low, Moderate, High}`.
  (FR-9)
- **FR-H8 Affect-to-action policy application.** The host applies the
  deterministic Node 4 policy (Section 11.1 table) to the detected affect
  level and deadline-proximity context, and the policy's decision — deliver,
  defer, soften, or replace with a break prompt — overrides or passes
  through Node 3's draft action accordingly. (FR-8)
- **FR-H9 Output payload assembly.** The host consolidates the final
  response into the structured JSON payload defined in Section 8.1 and sends
  it to the requesting edge session. Motor/positioning instructions are
  never included as commands — only an optional high-level `state_tag`.
  (FR-10, FR-13)
- **FR-H10 External task ingress endpoint.** The host exposes a generic,
  source-authenticated HTTP endpoint (`POST /v1/tasks/ingest`, Section 6.1a)
  through which an external connector can submit a task object, independent
  of any specific upstream data source. This is the complete substitute for
  the panel's email-notifier recommendation (D4): no mail connector is built
  or deployed to any participant in this study, but the ingress interface is
  built and demonstrable independent of any specific data source. Distinct
  from FR-H10a below — this endpoint authenticates per connector/source, not
  per participant, and is never given a real participant's task data during
  the study. (FR-14)
- **FR-H10a Participant task entry (console-facing).** The host exposes a
  participant-authenticated endpoint (`POST /v1/tasks`, Section 6.1) through
  which the companion console (FR-H11) submits tasks a participant enters
  directly. This is the endpoint actually used during the study; FR-H10's
  ingress is not.
- **FR-H11 Companion console — host's role.** Per source paper Section VI,
  the console PWA itself is **served locally from the participant's own
  machine at `127.0.0.1` by the companion background agent** (the same
  agent that reports idle-time buckets, FR-H-idle/FR-15) — it is not served
  by the host's FastAPI process, and it must remain usable (task entry,
  daily self-report, consent record, exit survey/SUS, read-only decision-
  trace view, data-deletion request) when the host is unreachable. The
  host's obligation is narrower than "serving the PWA": it is the **sync
  target** the local agent talks to when it *is* reachable — accepting
  the HTTP endpoints in Section 6.1–6.6 as a sync interface, not as the
  console's only storage. The console never **routinely** delivers
  reminders, regardless of connectivity state (closes RID-016) — console/screen delivery
  happens only as Section 13's audio-fallback path, when audio delivery
  was attempted and failed, and never as a matter of course. (This
  reconciles FR-H11 with Section 13's fallback table, which does route
  reminders to the console under that specific, logged condition; the two
  previously read as flatly contradictory.) (FR-16)
- **FR-H11b Local caching and sync (companion agent, host-facing
  contract).** The companion agent must persist console writes (task
  entries/edits, self-reports, consent records, exit-survey responses,
  deletion requests) to local storage on the participant's machine
  immediately, independent of host reachability, and queue any write made
  while the host is unreachable for later sync. **Reconnect detection is
  the agent's own concern, not the edge client's (closes RID-017).** The agent runs as a
  process on the participant's computer; it has no visibility into the
  ESP32-S3 edge client's WebSocket connection state and cannot observe
  `robot-runtime-spec.md` Section 10's discovery/connection-state events,
  which belong to a different machine on a different transport entirely. Instead, the agent
  detects reconnect itself: while its sync queue is non-empty, it polls
  `GET /v1/ping` (Section 6.8) at a fixed interval; a `200` response is
  "reconnected," and the agent immediately replays the queue against
  Section 6's endpoints in original order. This is a plain HTTP
  request/response over the same sync interface the agent already uses for
  every other write — no new transport or discovery mechanism is
  introduced. Each replayed write must carry a client-generated idempotency
  key (`client_write_id`, mirroring the `(source, external_id)` pattern
  already used for `POST /v1/tasks/ingest`, Section 6.1a) so that a write
  retried after a partial sync failure does not create a duplicate row on
  the host. The host must reject a replayed write with a previously-seen
  idempotency key as a no-op (`200`, not `201`), not as an error. This
  requirement did not previously exist anywhere in this spec; Section 6's
  endpoints were written as if every console operation reaches the host
  synchronously, which contradicts FR-16's "offline-capable" requirement
  as stated in the source paper.
- **FR-H11a Participant-facing data deletion.** The host exposes an
  authenticated endpoint (`POST /v1/data-deletion-request`, Section 6.5)
  through which an enrolled participant can request deletion of their
  stored data, fulfilling the deletion right stated in the source paper's
  Ethical Considerations section (NFR-11). Before this endpoint existed,
  the ethics section promised a capability the API surface did not provide;
  this closes that gap. Deletion must cover every table scoped to that
  `user_id` (Section 9): `tasks`, `routine_log`, `decision_trace`,
  `activity_buckets`, `lead_time_state`, `outages`, and the
  consent/self-report/exit-survey tables — nine tables in total. The
  `users` row and the `deletion_receipts` row for that `user_id` are
  intentionally excluded from deletion (Section 6.5). (NFR-11)
- **FR-H12 Decision tracing.** Every interaction produces one decision-trace
  record containing at minimum: intent, confidence, retrieved-context IDs,
  detected affect level, the specific policy rule applied (`R1`–`R5`, or
  `n/a` for interactions Section 11.1's table does not govern — Section
  8.3), and `lead_time_min`. (FR-18, FR-21)
- **FR-H13 Task adherence and latency logging.** The host logs task
  completion timestamp/outcome, and end-to-end latency from wake-word
  receipt to TTS onset, per interaction. (FR-19, FR-20)
- **FR-H14 Adaptive reminder lead-time.** The host maintains a per-user
  bounded parameter `L` updated per the EMA rule in Section 11.2, clamped to
  `[5, 60]` minutes, and never modifies any model weight in doing so. (FR-21)

## 6. API Contracts — HTTP

All HTTP endpoints below are served by FastAPI **on the host** and are the
**sync interface** the companion agent's locally-hosted console talks to
when the host is reachable — they are not the console's primary storage.
The console (Section VI of the source paper) is served locally at
`127.0.0.1` by the companion agent and must remain functional against its
own local cache when these endpoints are unreachable (FR-H11/FR-H11b). Base
path for the sync interface: `http://syncro-host.local:8765` — see
Section 10 for the corresponding WebSocket/discovery ports. **Confirmed**;
no longer an open configuration value.

### 6.1 `POST /v1/tasks` — Participant Task Entry (fulfills FR-14 / FR-H10a; `priority`)

Participant-authenticated (Section 14, NFR-14), used by the companion console
(FR-H11) when a participant enters or edits their own task list — either
live or, more commonly, replayed by the agent's sync queue (FR-H11b) after
a period offline. This is the endpoint the study actually uses. Request:

```json
{
  "user_id": "string, required",
  "title": "string, required, 1-200 chars",
  "deadline": "ISO-8601 datetime, optional",
  "notes": "string, optional, <= 1000 chars",
  "source": "string, required, e.g. 'console'",
  "priority": "low | normal | high, optional, default 'normal' — the R5
               discriminator (Section 11.1); carried here because this is
               the endpoint the study actually uses, unlike the `priority`
               field on Section 6.1a's ingest endpoint, which R5 has no
               access to during the study",
  "client_write_id": "string, required — idempotency key generated locally
                       by the companion agent at write time (FR-H11b); a
                       repeated key is a no-op, not a duplicate task"
}
```

Response `201 Created` (new `client_write_id`) or `200 OK` (already-seen
`client_write_id`, no duplicate row — same idempotency pattern as Section 6.1a):

```json
{
  "task_id": "string (uuid)",
  "user_id": "string",
  "title": "string",
  "deadline": "ISO-8601 datetime or null",
  "priority": "low | normal | high",
  "status": "pending",
  "created_at": "ISO-8601 datetime"
}
```

Errors: `401` (auth failure), `422` (validation failure — missing
`title`/`user_id`, malformed `deadline`).

### 6.1a `POST /v1/tasks/ingest` — External Task Ingress (fulfills FR-14 / FR-H10)

This is the artifact demonstrating that the architecture accepts external
task sources (the D4 substitute for an email connector). It is
**source-authenticated, not participant-authenticated** — the token
identifies a connector, not an enrolled participant — and is deliberately
kept separate from Section 6.1 so that demonstrating this interface never
requires a participant's own credentials. **No connector is deployed against
this endpoint during the study**; it exists to be built against and
demonstrated independently.

```
POST /v1/tasks/ingest
Authorization: Bearer <source token>     -- per source/connector, distinct
                                             from any participant console
                                             token issued under Section 6.1
Content-Type: application/json

{
  "source":      "string, required — identifies the connector",
  "external_id": "string, required — idempotency key; a repeated
                  (source, external_id) pair is a no-op, not a duplicate",
  "title":       "string, required",
  "due_at":      "ISO-8601 datetime, optional",
  "priority":    "low | normal | high, optional, default 'normal'",
  "created_at":  "ISO-8601 datetime, required"
}
```

Responses:

| Code | Condition |
|------|-----------|
| `201 Created` | New `(source, external_id)` pair; task created |
| `200 OK` | `(source, external_id)` pair already seen; no-op, no duplicate row |
| `400 Bad Request` | Unknown field present. Unknown fields are rejected, not silently ignored, so a malformed connector fails loudly rather than partially succeeding |
| `401 Unauthorized` | Missing or invalid source token |

Every accepted call (`201` or `200`) writes an ingress event to the decision
trace (`network_event`-style row, or a dedicated `ingress_event_log` —
implementation's choice per the pattern already established in Section 10.3)
carrying the connector's `source` id, so ingested tasks are auditable
alongside every other logged interaction. This endpoint is bound to the
host's own network interface only (Section 14, NFR-4/NFR-10) — it is never
exposed on a public address or port-forwarded, consistent with the
data-boundary protections in Section 14 (WireGuard tunnel only, no
publicly reachable service). This is the reason a mail connector is
declined for the study in the first place: the ingress contract must be
demonstrable without ever exposing a public endpoint, independent of
whether the host sits on the participant's own network or a team-operated
one.

Because a task ingested here has no participant token, it is not
automatically associated with a study `user_id`; this endpoint's purpose in
the study is solely to demonstrate the ingress contract, not to create
tasks a live pipeline acts on. Wiring an ingested task to a specific
participant's task list is out of scope for the study deployment and left
for a future connector implementation to resolve, consistent with "no
connector deployed to any participant" above.

### 6.2 `GET /v1/tasks?user_id=...&status=...`

Returns the participant's task list for the console (fulfills FR-16 /
FR-H11 task-entry surface). Supports `status=pending|overdue|completed`.

### 6.3 `PATCH /v1/tasks/{task_id}`

Console-side edit/complete. Body: any subset of `{title, deadline, notes,
status}`, plus `client_write_id` (string, required — same idempotency
pattern as Section 6.1; a repeated key against the same `task_id` is a
no-op `200` that does not re-apply the edit a second time, since a replayed
`PATCH` after a dropped ack must not, for example, double-log the
task-adherence row below). Writes a task-adherence log row on `status ->
completed` (FR-19).

### 6.4 `GET /v1/decision-trace?user_id=...&since=...&limit=...`

Read-only decision-trace view for the console (FR-16). Returns an array of
the decision-trace record shape defined in Section 8.3. This endpoint must
never accept writes.

### 6.5 `POST /v1/data-deletion-request` — Participant Data Deletion (fulfills NFR-11 / FR-H11a)

Participant-authenticated (Section 14, NFR-14), console-facing. Request:

```json
{
  "user_id": "string, required",
  "confirm": "true, required",
  "client_write_id": "string, required — same idempotency pattern as
                       Section 6.1, since this write can also be replayed
                       by the agent's sync queue (FR-H11b) after a dropped
                       ack"
}
```

On receipt, the host deletes every row scoped to `user_id` across the nine
tables that hold participant-generated data: `tasks`, `routine_log`,
`decision_trace`, `activity_buckets`, `lead_time_state`, `outages`, and the
consent/self-report/exit-survey tables (Section 9). This is a synchronous
operation — the delete completes and the receipt is written before the
response is returned — so the response is `200 OK`, not `202 Accepted`
(closes RID-021): `202` asserts work is still pending, which is false by
the time the receipt exists to return. The response body is the
deletion-receipt record itself (`user_id`, `requested_at`,
`client_write_id`, `tables_cleared`).

**Scope exclusions, both intentional (closes RID-022):**
- **`users`.** The row is retained, not deleted. It carries no behavioral
  or interaction data — only `user_id`, `created_at`, and
  `declared_working_window` — and removing it would (a) sever the FK the
  retained receipt below is keyed to, and (b) reopen `user_id` for
  potential reissue, which risks a future participant's data being
  silently commingled with a deleted one's remnants under the same key.
  Retaining a bare enrollment record is standard research-study practice
  and does not conflict with NFR-11, which commits to deleting a
  participant's collected data, not their fact of having been enrolled.
- **The deletion receipt itself.** Persisted in a new `deletion_receipts`
  table (Section 9), keyed to the now-deleted `user_id`. This is
  deliberately retained, not an oversight: it is the evidence that
  deletion occurred (needed for both the idempotent-replay behavior below
  and for demonstrating compliance with NFR-11), and it contains no
  participant behavioral content of its own — only the `user_id`,
  timestamps, and the list of table names cleared.

A repeated `client_write_id` against a `user_id` whose data was already
cleared by the original call returns `200` with the original receipt
(read back from `deletion_receipts`), not `404` — deletion having already
happened is the success case this call is asking for, not an error
condition, and treating it as `404` on retry would make the endpoint
non-idempotent in exactly the situation FR-H11b requires it to tolerate.
`404` is reserved for a `user_id` that was never valid in the first place
(no `users` row exists, and no prior receipt exists for the presented
`client_write_id` or for any `client_write_id` against that user). Errors:
`401` (auth failure), `404` (`user_id` never valid), `422` (`confirm` not
`true` — deletion must be an explicit, unambiguous action, not a side
effect of a malformed request).

### 6.6 `POST /v1/consent`, `POST /v1/self-report`, `POST /v1/exit-survey`

Console-side research-instrument capture (informed consent record, daily
self-report, exit SUS/interview metadata). Schema left to implementation;
each record must carry `user_id`, `submitted_at`, a `payload` object, and
`client_write_id` (Section 6.1's idempotency pattern, required per
FR-H11b — see closure note in that requirement), and must be stored only
in the host's own SQLite instance (Section 14, NFR-10) — never relayed to
or duplicated in any third-party or commercial service. A repeated
`client_write_id` on any of these three endpoints is a no-op (`200`), not
a duplicate record, identically to Section 6.1.

### 6.7 `POST /v1/activity-buckets` — Idle-Time Bucket Ingest (fulfills FR-15 / FR-R7)

The ingress endpoint FR-R7 requires and that Section 9's `activity_buckets`
table previously had no way to receive data from. Called by the companion
agent (`robot-runtime-spec.md` Section 8), not the edge client — the agent
already holds a participant-scoped credential from its console sync role
(Section 6.1's auth scope; the agent is the same process), so no new
authentication scope is introduced.

```
POST /v1/activity-buckets
Authorization: Bearer <participant token>     -- same scope as Section 6.1
Content-Type: application/json

{
  "user_id":       "string, required",
  "minute_start":  "ISO-8601 datetime, required — start of the 1-minute bucket, truncated to the minute",
  "active_seconds":"integer [0,60], required",
  "idle_seconds":  "integer [0,60], required"
}
```

Responses:

| Code | Condition |
|------|-----------|
| `201 Created` | New `(user_id, minute_start)` pair; bucket row inserted |
| `200 OK` | `(user_id, minute_start)` pair already seen (agent resent after a dropped ack); no-op, no duplicate row — the pair itself is the idempotency key, since a given minute can only have one true bucket per user |
| `400 Bad Request` | `active_seconds + idle_seconds > 60`, or either field outside `[0,60]` |
| `401 Unauthorized` | Missing or invalid participant token |

This is the data path `robot-runtime-spec.md` Section 8.2's release rule
reads from (`get_latest_activity_buckets(user_id, n=2)`); before this
endpoint existed, that call had no way to be populated and FR-15's
idle-gating mechanism had no data path at all.

### 6.8 `GET /v1/ping` — Companion Agent Reconnect Check (fulfills FR-H11b)

Participant-authenticated (same scope as Section 6.1). Returns `200` with
an empty body if the host is reachable and the token is valid; `401` if
the token is invalid. This is the **only** signal FR-H11b's reconnect
detection uses (Section 5) — it exists specifically so the companion
agent has a way to detect "host reachable again" without depending on the
edge client's WebSocket/discovery events (`robot-runtime-spec.md` Section
10), which run on a
different machine and a different transport. The agent polls this at a
fixed interval only while its local sync queue is non-empty; it is not
polled continuously in the steady state.

## 7. API Contracts — WebSocket

### 7.1 Endpoint

`ws://syncro-host.local:8765/v1/stream` — **confirmed port**, one
persistent connection per active edge-client interaction session (Section
XV of source paper: selected over HTTP/REST, raw TCP/UDP, MQTT, and WebRTC;
see that section for the full trade-off rationale, restated only as a
decision here).

### 7.2 Message Sequence (fulfills FR-1, FR-5, FR-13; source paper Section XVI)

```
Edge                                    Host
 │── start_audio ─────────────────────▶ │
 │◀──────────────────────────── ready ──│
 │── audio_frame (N times, streamed) ──▶│
 │── end_audio ────────────────────────▶│
 │                                       │  [Node 1..4 pipeline runs]
 │◀──────────────────────── response ───│
 │◀────── tts_audio_frame (M times) ────│
 │◀──────────────────── tts_audio_end ──│
```

The `response` message (Section 8.1) carries the decision and the text of
what will be said; it does not itself carry audio. The synthesized speech
follows as a separate stream of binary `tts_audio_frame` messages,
terminated by `tts_audio_end` — the downlink mirror of `audio_frame`/
`end_audio` on the uplink. See Section 7.3 for both new schemas and
Section 8.4 for the format, chunking and buffering contract.

### 7.3 Message Schemas

`start_audio` (edge → host):

```json
{
  "type": "start_audio",
  "session_id": "string (uuid)",
  "user_id": "string",
  "wake_word_detected_at": "uint64 (ms epoch, edge-local clock, required)"
}
```

`wake_word_detected_at` is the edge device's own timestamp of wake-word
confirmation (FR-2), captured before any network round trip. Without it the
host has no way to measure the interval FR-20/NFR-H1 actually specifies —
wake-word detection to TTS onset — since the host's own clock only sees
`start_audio` on arrival, which is already downstream of VAD confirmation
and edge-to-host transit. This field closes that gap; see Section 12 for how
it is used and Section 14 for the edge/host clock-sync caveat this
introduces.

`ready` (host → edge):

```json
{ "type": "ready", "session_id": "string" }
```

`audio_frame` (edge → host) — raw PCM audio, sent as a binary WebSocket
message with no header (Section 8.2, closes CC-001), not JSON. A JSON
header variant is not used, to avoid base64 inflation over a link the paper
treats as already latency-constrained (NFR-1).

`end_audio` (edge → host):

```json
{ "type": "end_audio", "session_id": "string", "frame_count": "integer" }
```

The host validates `frame_count` against the number of binary frames
actually received on that connection for the session. A mismatch is logged
as an application-layer anomaly (Section 8.2) without blocking response
generation — since TCP guarantees order and completeness on a live
connection, the only way frames actually go missing is the connection
itself dropping mid-utterance, which is a reconnect/disconnect condition
handled independently (Section 10), not a per-frame gap this count could
localize. `frame_count` catches an edge-side counting bug or an early
`end_audio` send, not network loss.

`response` (host → edge) — see Section 8.1 for full payload shape. Carries
`tts_text` for logging/decision-trace/console display only; it is not what
the edge plays back (Section 8.4).

`tts_audio_frame` (host → edge) — binary WebSocket message, not JSON, for
the same base64-inflation reason `audio_frame` is binary (above). Sent
once per chunk of synthesized audio, streamed as it becomes available
rather than buffered whole on the host first — matching the uplink's
streaming rationale (FR-H1) in the opposite direction. No JSON header is
embedded in the binary payload: the WebSocket message boundary is the
frame boundary, and `session_id`/ordering is established by the fact that
one session has at most one in-flight `response`→playback cycle at a time
(Section 7.4). Payload is raw PCM per Section 8.4's format.

`tts_audio_end` (host → edge):

```json
{ "type": "tts_audio_end", "session_id": "string", "frame_count": "integer" }
```

Signals that the last `tts_audio_frame` for this `response` has been sent.
The edge validates `frame_count` against frames actually received, using
the same mismatch-logging convention `end_audio` uses on the uplink
(above) — a count mismatch is logged, not treated as fatal. This is a
distinct signal from `playback_underrun` (Section 13, Section 8.4): a
`frame_count` mismatch is a post-hoc count check made once streaming has
finished, while `playback_underrun` is detected live, during playback,
from the ring buffer's own fill level running dry — one does not imply or
trigger the other, and TCP already guarantees order/completeness on the
connection, so a `frame_count` mismatch here indicates a host-side
counting bug or an early `tts_audio_end`, not lost frames.

`condition_report` (edge → host, closes RID-007) — the message
`robot-runtime-spec.md` Section 9's `report_condition` call actually sends.
Not tied to a `session_id`: a condition (mute engaged, no output device) can
be true independent of any in-flight interaction, and the host must be able
to write the correct `degradation_reason` (Section 13) even when no
`response` is currently pending.

```json
{
  "type": "condition_report",
  "session_id": "string or null — the in-flight session this condition
                 applies to, if any; null if reported outside an interaction
                 (e.g. mute toggled at idle)",
  "condition": "mute_engaged | audio_device_unavailable | tts_timeout | playback_error",
  "detected_at": "uint64 (ms epoch, edge-local clock)"
}
```

On receipt, the host writes `degradation_reason` (Section 13, same
enumeration as `condition`) to the decision-trace row for `session_id` if
one is given, or to a standalone log entry otherwise, and selects the
fallback channel per Section 13's table. This closes the gap the edge
article previously left as "implementation detail": there is now exactly
one schema, defined here, that both articles reference.

`error` (host → edge, closes RID-008) — the message Section 13 refers to for the two
conditions it disposes of as `error` WS message, and for the session-
collision case in Section 7.4.

```json
{
  "type": "error",
  "session_id": "string — the session the error applies to",
  "error_code": "session_collision | malformed_audio | session_timeout",
  "message": "string, human-readable, optional"
}
```

Receipt of `error` ends the named session on both sides without a
`response`; the edge does not attempt playback and returns to Standby
(`robot-runtime-spec.md` Section 6). `session_timeout` is sent by the host
per Section 7.4's session-expiry rule, below.

### 7.4 Session Lifecycle Rules

- **Authentication (at connection establishment, not per session).** Before
  the host accepts `start_audio` or any other application message, the
  connecting client authenticates once, when the WebSocket connection is
  established: the edge presents its provisioned `device_token`
  (`robot-runtime-spec.md` Section 10.1) as a header on the WebSocket
  upgrade request (`Authorization: Bearer <device_token>`). The host
  validates the token before completing the handshake (Section 10.2) and
  associates the connection with the corresponding `device_id`/`user_id`.
  On success, `connect_success` is logged (Section 10.3) and the connection
  becomes available for the message sequence in Section 7.2. On failure,
  the host refuses the upgrade, logs `connect_failed` (Section 10.3), and
  no application message — including `start_audio` — is ever accepted on
  that connection. Because the same connection is reused across multiple
  interactions (below), authentication is per-connection: a `session_id`'s
  messages are implicitly authenticated by the connection they arrive on,
  and no separate per-session credential is presented. (Transport-security
  disposition — encryption in transit/at rest — is stated in Section 14,
  NFR-4/NFR-10, and is unaffected by this application-layer credential.)
- **Clock-offset handshake (closes RID-009; at connection establishment,
  immediately after authentication).** This is the mechanism Section 12 (NFR-H1) requires and
  previously only named as an option ("via NTP/SNTP ... or a measured
  one-time clock-offset handshake") without specifying either. NTP/SNTP is
  not selected, because it requires the edge to run a full SNTP client and
  reach an external time source — a dependency the edge article does not
  otherwise need and the data-boundary constraints (Section 14, NFR-4/
  NFR-10) make awkward to justify for a device that should not need
  outbound network access beyond the host tunnel. The one-time handshake
  is selected instead:

  ```
  Host                                          Edge
   │◀───────────────────────── clock_sync_request ──│   { type, edge_send_ms: uint64 }
   │── clock_sync_response ─────────────────────────▶│   { type, edge_send_ms (echoed),
   │                                                  │     host_recv_ms, host_send_ms }
  ```

  The edge sends `clock_sync_request` with its own current clock reading
  (`edge_send_ms`) immediately after the WebSocket handshake completes,
  before the first `start_audio` of the connection. The host responds with
  `clock_sync_response`, echoing `edge_send_ms` and adding
  `host_recv_ms`/`host_send_ms` (its own clock at receipt and at reply).
  The host computes `offset = ((host_recv_ms - edge_send_ms) +
  (host_send_ms - edge_send_ms)) / 2` — the standard midpoint estimate,
  which cancels one-way transit time to first order — and stores it against
  the connection for the lifetime of that connection. This is what lets
  `latency_ms` (Section 8.3) translate `wake_word_detected_at` (edge clock)
  into host-clock time; if this exchange has not completed for a
  connection, `latency_basis` degrades to `host_observed_only` for every
  session on it (Section 12), rather than the host guessing an offset of
  zero. The edge's own obligation is only to send `clock_sync_request` and
  echo the value it's given back — it does not need NTP/SNTP or any
  standing wall-clock accuracy of its own (`robot-runtime-spec.md` Section
  7.1).
- One `session_id` maps to exactly one in-flight utterance. A `start_audio`
  for a `session_id` already in flight is rejected with an `error` message
  (Section 13) rather than silently reset.
- **Session expiry (closes RID-013).** A session enters "in-flight" at `start_audio` and
  exits it at `response` (success) or `error` (failure). If a session
  remains in-flight for longer than the **session inactivity timeout**
  (Section 11.3; default 30s, chosen as several multiples of the ≤2-3s
  NFR-H1 target so it never fires on a healthy interaction, while still
  bounding how long a stalled session's buffer is held) with no
  `audio_frame` or `end_audio` received, the host: sends `error`
  (`error_code: session_timeout`) to the edge if the connection is still
  open, discards the session's audio buffer, writes a decision-trace row
  with `degradation_reason: session_timeout` (Section 13), and frees the
  `session_id` so a new `start_audio` using it would no longer be rejected
  as a collision. This is what "abandoned sessions accumulate for the
  process lifetime" (the gap this closes) refers to — before this rule,
  nothing ever reclaimed one.
- The host does not close the WebSocket connection after a `response`; the
  same TCP connection is reused for the next interaction unless the edge
  client disconnects (matches "Normal Operation Cycle" in source paper
  Section XV: Connected → Audio interaction → Host processing → Response →
  Connected).

## 8. Data Contracts and Schemas

### 8.1 Output Payload (`response` message body)

Fulfills FR-10/FR-H9. This is the *only* channel through which the host
influences edge behavior; it never contains a motor command.

```json
{
  "type": "response",
  "session_id": "string",
  "tts_text": "string, required",
  "state_tag": "string, optional, enum: idle | listening | speaking | break_prompt | deferred | null",
  "policy_rule": "string, one of R1..R5, or n/a for interactions Section 11.1 does not govern (mirrors Section 8.3)",
  "lead_time_min": "number"
}
```

The edge client's own firmware — not this payload — determines what
physical motion, if any, corresponds to `state_tag` (see
`robot-runtime-spec.md` Section 7.3, flagged there as an open design
decision not resolved by the source paper). `tts_text` is the transcript
of what will be spoken — used for the decision trace, the read-only
console view (Section 6.4), and as the reported degraded-path content when
Section 13 falls back to text — but it is not the audio the participant
hears. The edge client never synthesizes speech itself and never derives
audio from `tts_text`; the audio the edge plays arrives exclusively as the
`tts_audio_frame`/`tts_audio_end` stream defined in Section 7.3 and 8.4.

### 8.2 Uplink Audio Wire Format (binary-frame contract)

**This replaces a custom per-frame binary header this document previously
defined** (`session_id`, `sequence_number`, `timestamp`, `payload_length`,
`audio_payload` fields on every audio message). That header re-implemented
frame ordering at the application layer despite the WebSocket transport
already running over TCP, which guarantees in-order, complete delivery on
the same connection — the header's own field comment previously conceded
this ("despite TCP's own ordering guarantee"), and Section 13 built
`malformed_audio` handling partly on top of that redundancy. Per the actual
decision of record (`transport-framing-decision.md` §2.1, cited in the
project's spec-review CC-001), no custom header exists: **the WebSocket
frame type itself is the discriminator.**

- **Binary frames** (edge → host, during an active utterance): raw PCM
  audio only. No header, no envelope — the frame's payload *is* the audio.
- **Text frames** (both directions): JSON control messages (`start_audio`,
  `end_audio`, `ready`, `response`, `condition_report`, `error`,
  `clock_sync_request`/`clock_sync_response`) — already the existing
  contract (Section 7.3) and unaffected by this change.

Session association, ordering, and length validation — the three jobs the
old header's `session_id`/`sequence_number`/`payload_length` fields did —
are no longer needed per-frame: session association is already established
by `start_audio`'s `session_id` for the life of that utterance (Section
7.1 — one connection per active session); ordering is the transport's job;
length is inherent to the binary frame itself. `timestamp` (used for
"reconstruction/diagnostics") is dropped from the wire format — the host
stamps arrival time on receipt (already logged as part of the interaction
record) rather than trusting an edge-supplied per-frame value that no
longer has a header to live in.

**Format (closes CC-002):** raw PCM, 16 kHz, 16-bit, mono, little-endian,
no codec — same format the downlink (Section 8.4) already uses, now stated
for the uplink too rather than left open. Capture is chunked into
**20 ms** ring-buffer units (640 bytes) sent as individual binary frames;
this is provisional, not final — it must be resized to match the
wake-word engine's native frame length once that is confirmed (Section 16),
not left at a round millisecond count, or every frame is copied twice on
hardware where RAM is the binding constraint. The still-genuinely-open item
is that one number (the wake-word engine's frame length), not the format
itself.

Host-side validation on receipt: reject (and log, Section 13) any binary
frame received outside an active `start_audio`/`end_audio` window for that
connection, or any PCM payload whose byte length is not a multiple of 2
(not a whole number of 16-bit samples) — surfaced as `error_code:
malformed_audio` (Section 7.3), the same mechanism this document already
used for unreconstructable audio, now without a `sequence_number` gap check
behind it (that check no longer exists — TCP already guarantees order and
completeness on this connection, so a "gap" is not a state the host can
observe).

### 8.3 Decision Trace Record

Fulfills FR-18/FR-H12 and is the object underlying NFR-6 (auditability) and
the study's Policy-Consistency Audit.

```json
{
  "trace_id": "string (uuid)",
  "session_id": "string",
  "user_id": "string",
  "timestamp": "ISO-8601 datetime",
  "intent": "string",
  "intent_confidence": "number [0,1]",
  "retrieved_context_ids": ["string", "..."],
  "affect_level": "Low | Moderate | High",
  "deadline_proximity": "imminent | not_imminent | n/a",
  "policy_rule": "R1 | R2 | R3 | R4 | R5 | n/a",
  "action_taken": "deliver | defer | soften | break_prompt | suppress",
  "lead_time_min": "number",
  "reminder_outcome": "accepted | snoozed | delivery_miss | pending | n/a",
  "degradation_reason": "string or null, enum per Section 13",
  "network_event": "string or null, enum per Section 10.3",
  "latency_ms": "number",
  "latency_basis": "wake_word_to_tts | host_observed_only"
}
```

`reminder_outcome` is the field the Section 11.2 adaptive lead-time rule
reads and writes, and it is where "log as delivery_miss" (Section 11.2)
actually lands — Section 11.2's pseudocode says an ignored reminder is
"logged separately as a delivery miss" but the earlier version of this
schema had nowhere for that to go. Unlike the other trace fields, the
outcome is not necessarily known at the moment the row is created — a
delivered reminder's outcome is only observable after the participant has
had a chance to respond. The row is created with `reminder_outcome:
"pending"` at dispatch and updated in place once the outcome resolves.
`accepted` and `snoozed` feed the `L` update per Section 11.2; `delivery_miss`
(the panel's term for an ignored reminder) does not update `L`, but must
still be written so ignored-vs-responded rates are queryable rather than
silently dropped. `n/a` is used for rows that never carry a reminder
outcome at all (e.g. a `request_summary` or `ask_status` interaction).
`delivery_miss` here is a distinct concept from Section 13's
`degradation_reason: delivery_failed` — the former means the reminder was
delivered but not acted on; the latter means the system could not attempt
delivery at all. The two must not be conflated in analysis.

`policy_rule` (closes RID-019) is `R1`–`R5` only for interactions the
Section 11.1 table actually governs — reminder delivery/defer decisions.
`ask_status` and `request_summary` interactions never pass through Node 4's
policy table at all, so forcing an `R1`–`R5` value onto them would be a
fabricated result, not a recorded one; those rows carry `policy_rule: "n/a"`
instead, with `deadline_proximity` also `"n/a"` on the same row (both fields
are `n/a` together, never one without the other). The Policy-Consistency
Audit (Section 14, NFR-6) compares `(affect_level, deadline_proximity)`
against `policy_rule` only for rows where `policy_rule != "n/a"`; an `n/a`
row is outside the audit's domain by definition and is excluded before the
comparison runs, not flagged as a mismatch.

`action_taken: suppress` (closes RID-020) is never the value written to the
row that triggers an R5 decision — that row's own action was to deliver its
one highest-priority reminder, so it is written with `action_taken:
"deliver"`. `suppress` is instead written to the *other*, already-existing
`pending` decision-trace rows for the reminders R5 suppresses: each such
row is updated in place (the same update-in-place pattern `reminder_outcome`
already uses) with `action_taken: "suppress"`, recording the effect on the
row it actually happened to rather than on the row that caused it.

Every field above must be populated (or explicitly null) on every logged
interaction — partial trace rows are a spec violation, since the
Policy-Consistency Audit depends on the full row being present to compare
`(affect_level, deadline_proximity)` against `policy_rule` for every row
within its domain (see RID-019 closure above for what falls outside it).

### 8.4 TTS Audio Downlink — Format, Chunking, Buffering and Backpressure (closes CC-003)

The message types are defined in Section 7.3; this section defines their
content and the playback contract around them.

- **Format.** Raw PCM, 16 kHz, 16-bit, mono, little-endian, no codec — the
  same format the uplink binary frames use (Section 8.2, closes CC-002), so
  both directions run at one sample rate and the edge needs only one I2S
  clock configuration. Piper's native output rate is resampled to 16 kHz
  **host-side**, before chunking; the edge never resamples.
- **Chunking.** Each `tts_audio_frame` carries one 100 ms segment
  (3,200 bytes at this format) of the resampled audio, sent as it becomes
  available from the synthesis pipeline rather than accumulated into one
  message. This matches the uplink's own streamed-not-buffered convention
  (FR-H1, Section 7.3).
- **Buffering / playback start.** The edge does not begin playback on the
  first `tts_audio_frame`. It accumulates into a ring buffer and starts
  playback once buffered audio reaches a **~250 ms low-water mark**, so a
  brief scheduling jitter on either side does not immediately starve
  playback.
- **Underrun handling.** If the edge's playback buffer empties before
  `tts_audio_end` arrives, that is an **underrun, not a fault**: the edge
  logs `playback_underrun` (Section 13) and resumes playback once the
  buffer refills past the low-water mark again — it does not abort the
  interaction or fall back to the console path on this condition alone.
  This is distinct from `degradation_reason: playback_error` (Section 13),
  which is reserved for a genuine playback failure (e.g. a non-zero return
  from the audio driver) — the two must not be conflated in analysis, the
  same convention already applied to `delivery_miss` vs. `delivery_failed`
  above.
- **Backpressure.** Pacing is the **host's** responsibility: the host
  paces `tts_audio_frame` transmission to the edge's playback rate rather
  than sending the full utterance at once and assuming the edge's ring
  buffer can absorb it. The edge does not implement flow-control signaling
  back to the host for this stream.

## 9. Database Schema (SQLite ERD)

Fills the empty "Database Schema" section left in the source paper
(Section XII). Minimum viable schema to satisfy FR-6, FR-14, FR-16, FR-18–21:

```
users
├── user_id (PK)
├── created_at
└── declared_working_window (start_time, end_time)   -- for Active-Time Ratio scoping

tasks
├── task_id (PK)
├── user_id (FK -> users.user_id)
├── title
├── deadline (nullable)
├── notes
├── priority            -- low | normal | high; the R5 discriminator (Section 11.1) —
│                           set by Section 6.1, defaulted 'normal' if absent from Section 6.1a
├── status              -- pending | overdue | completed
├── created_at
├── completed_at (nullable)
├── client_write_id (nullable, UNIQUE)          -- idempotency key from Section 6.1/6.3 (FR-H11b);
│                                                   null for rows created via Section 6.1a, which
│                                                   uses the pair below instead
└── (source, external_id) (nullable pair, UNIQUE together)  -- idempotency key from Section 6.1a;
                                                                null for rows created via Section 6.1

routine_log
├── log_id (PK)
├── user_id (FK)
├── event_type          -- break | routine
└── logged_at

decision_trace
├── trace_id (PK)
├── session_id
├── user_id (FK)
├── timestamp
├── intent
├── intent_confidence
├── retrieved_context_ids (JSON array, stored as TEXT)
├── affect_level
├── deadline_proximity
├── policy_rule              -- R1 | R2 | R3 | R4 | R5 | n/a
├── action_taken             -- deliver | defer | soften | break_prompt | suppress
├── lead_time_min
├── reminder_outcome         -- accepted | snoozed | delivery_miss | pending | n/a
├── degradation_reason (nullable)
├── network_event (nullable)
├── latency_ms
└── latency_basis          -- wake_word_to_tts | host_observed_only

lead_time_state
├── user_id (PK, FK)
├── current_L
└── last_updated_at

activity_buckets                                       -- fed by idle-time sensor, see robot-runtime-spec.md FR-R7
├── bucket_id (PK)
├── user_id (FK)
├── minute_start
├── active_seconds
└── idle_seconds

consent_records / self_reports / exit_survey_responses
└── (user_id FK, submitted_at, payload JSON-as-TEXT, client_write_id
    UNIQUE) — one table per instrument; `client_write_id` is the same
    Section 6.6 idempotency key, so a replayed submission after a dropped
    ack is a no-op rather than a duplicate research record

outages                                                -- Section 13.1, fulfills D7, closes RID-015;
│                                                          participant-scoped rows, in deletion scope (Section 6.5)
├── outage_id (PK)
├── user_id (FK)
├── started_at
├── ended_at (nullable — null while the outage is open)
└── affected_interaction_count

deletion_receipts                                      -- Section 6.5, closes RID-021/RID-022
├── user_id (FK -> users.user_id)                       -- row retained after deletion; see Section 6.5
├── requested_at
├── client_write_id (UNIQUE)
└── tables_cleared (JSON array, stored as TEXT)
```

Relationships: one `user` has many `tasks`, many `routine_log` entries, many
`decision_trace` rows, many `activity_buckets`, many `outages`, and exactly
one `lead_time_state` row. All foreign keys scope every query in Section 8.3
and FR-H5 to a single `user_id`, consistent with NFR-12 (no cross-participant
or organizational data leakage).

## 10. Device Connection Handling (Host Side)

### 10.1 Listener

The host listens on its configured WebSocket port (Section 7.1) for
incoming connections from provisioned edge devices.

### 10.2 Authentication

The host authenticates the `device_token` each connecting client presents
at connection establishment — Section 7.4 defines the exchange — and
associates the connection with the correct `device_id`/`user_id`. This
happens once per WebSocket connection, not once per session, since the
same authenticated connection is reused across the interactions it
carries.

### 10.3 Network Event Logging

The host logs the same connection-state vocabulary the edge client can
report *to the host* — `connect_attempt`, `connect_success`,
`connect_failed`, `host_disconnected`, `reconnect_success` — to
`decision_trace.network_event` or a dedicated `network_event_log` table —
implementation may choose either, but the events must be queryable
per-session for the same audit purposes as Section 8.3. This is 5 of the 6
events `robot-runtime-spec.md` Section 10.5 lists, not all 6: that
section's `provisioning_missing` is a pre-connection, edge-local event —
it means no `device_token` exists yet to even attempt a WebSocket
handshake with, so there is structurally no channel for the host to
observe or log it on the host's behalf. Its absence here is not a
vocabulary mismatch to reconcile.

### 10.4 Provisioning

Generating and writing the NVS blob (`robot-runtime-spec.md` Section
10.1), including `device_token` issuance, happens once per kit, before
deployment [open item — provisioning tooling itself: Section 16].

## 11. Configuration and Tunables

### 11.1 Affect-to-Action Policy Table (Node 4)

This table is the deterministic mapping the host must implement exactly.
Source paper Table 1.

| Rule | Affect Level | Deadline Proximity   | Action                                                                 | Tone/Content                          |
|------|---------------|-----------------------|-------------------------------------------------------------------------|----------------------------------------|
| R1   | Low           | Any                   | Deliver at scheduled time, standard cadence                             | Neutral, full task detail              |
| R2   | Moderate      | Not imminent (>2h)    | Defer by grace window (default 15 min; release timing owned and executed by the host's policy-tick scheduler — same process as Section 11.2a/13.1 below; release predicate detailed in `robot-runtime-spec.md` Section 8.2 — closes RID-023, RID-024) | Softened, shortened phrasing           |
| R3   | Moderate      | Imminent (≤2h)        | Deliver on schedule; no defer                                            | Softened, framed as priority           |
| R4   | High          | Not imminent          | Defer; insert break prompt before next scheduled item (same release rule as R2, owned by the host's policy-tick scheduler, detailed in `robot-runtime-spec.md` Section 8.2) | Minimal, low-arousal, single item      |
| R5   | High          | Imminent               | Deliver only highest-priority reminder; suppress other queued reminders | Minimal phrasing; break prompt queued  |

The 2-hour and 15-minute values are **designer-set default configuration**,
not literature-derived cutoffs, and are treated as hard discontinuous
boundaries in the current prototype (source paper Scope and Limitations).
They must be host-side configuration values, not hardcoded constants, so
they can be revised without a code change.

### 11.2 Adaptive Lead-Time Parameter (`L`)

```
L₀ = 15 (minutes)
on interaction outcome:
    if outcome == "accepted":
        L_hat = L
        write_to_decision_trace(reminder_outcome = "accepted")
    elif outcome == "snoozed" (by s minutes):
        L_hat = L - s
        write_to_decision_trace(reminder_outcome = "snoozed")
    elif outcome == "ignored":
        # no update to L; still logged, not silently dropped
        write_to_decision_trace(reminder_outcome = "delivery_miss")
        return

    L = clamp((1 - α) * L + α * L_hat, 5, 60)   # α = 0.3
    persist(user_id, L)
    write_to_decision_trace(lead_time_min = L)
```

Whether `L` is held fixed at `L₀` or allowed to vary for the study duration
is a methods decision external to the host's own code (source paper
FR-21) — the host must support both modes via a single configuration flag
(`adaptive_lead_time_enabled: bool`) rather than hardcode one behavior.

### 11.2a Reminder Outcome Capture and Timeout (closes RID-010)

The `on interaction outcome` event Section 11.2's pseudocode consumes was
previously produced by nothing — no endpoint or message recorded which
outcome a dispatched reminder received, and no component was named as
responsible for ever declaring one `delivery_miss`. This section is that
input path.

**Capture paths, one per outcome value:**

- **`accepted`.** Written when, within the reminder response window
  (below) of dispatch, either (a) the participant issues the
  `dismiss_reminder` voice intent (FR-H3) referencing that reminder's
  `session_id`/`trace_id`, or (b) the underlying task's `status` transitions
  to `completed` via `PATCH /v1/tasks/{task_id}` (Section 6.3). Either is
  a legitimate acknowledgment; the host does not require both.
- **`snoozed`.** Written when the participant issues the `snooze_reminder`
  voice intent (FR-H3) within the response window, referencing that
  reminder. `snooze_minutes` from the intent's extracted slot becomes `s`
  in Section 11.2's `L_hat = L - s`.
- **`delivery_miss`.** Written by the host's policy-tick scheduler — the
  same recurring process that runs Section 13.1's retry/drain sweep and
  Section 11.1's R2/R4 idle-release loop (`robot-runtime-spec.md` Section
  8.2) — when
  a `pending` row's dispatch time plus the reminder response window has
  elapsed with neither of the above having arrived. This is the named
  owner and timeout the rule previously lacked: the transition is not
  driven by any client action, only by wall-clock elapse checked on the
  existing tick.
- **`pending`.** The row's state between dispatch and one of the three
  outcomes above; not itself an input path, just the default the row is
  created with (Section 8.3).

**Response window.** The duration used by the `delivery_miss` check above
is the **reminder response window** (Section 11.3), tracked as an open
configuration item rather than fixed here (Section 16) — the same
treatment already given the `delivery_failed` queue bound, since neither
is fixed by any source document the author holds and both are the kind of
number that should be set from observed data (here, typical time-to-
respond) rather than guessed.

### 11.3 Other Tunables

| Parameter                     | Default | Range / Notes                                   |
|--------------------------------|---------|--------------------------------------------------|
| Intent confidence threshold    | **Pilot range: 0.60–0.75** | Below this, route to clarification (FR-4/FR-H4). No single default is fixed yet — the team is deliberately piloting across this range against real traces during the threshold-pilot week and will lock one value before Participant 1's baseline week. **Implementation requirement:** the raw confidence score must be logged unconditionally in every decision-trace row regardless of which threshold value is active on a given pilot day, so multiple candidate thresholds can be evaluated retroactively against the same trace set rather than requiring separate pilot runs per threshold. |
| Deadline-proximity boundary    | 2 hours | Hard cutoff, not smoothed (see Section 11.1 — closes RID-025) |
| Grace window (defer)           | 15 min  | Fixed default; release timing owned by the host's policy-tick scheduler; release predicate detailed in `robot-runtime-spec.md` Section 8.2 (data path: FR-R7) |
| Lead-time bounds               | [5, 60] min | Hard clamp on `L`                             |
| Lead-time smoothing constant α | 0.3     | EMA weight                                        |
| Classifier deployment gate     | macro-F1 ≥ 0.70 | Go/no-go, not a runtime tunable (NFR-3)   |
| `delivery_failed` queue bound (per user) | TBC — deployment/config parameter | Must be a fixed capacity per Section 13.1; the number itself is not fixed by D7 or `roadmap.md` and is tracked as an open configuration item (Section 16), to be set before the live DEL-07 demonstration |
| Overflow policy | drop-oldest | Fixed per Section 13.1 / D7, independent of the numeric bound above |
| Session inactivity timeout | 30 sec | Section 7.4; an in-flight session with no `audio_frame`/`end_audio` for this long is expired |
| Reminder response window | TBC — deployment/config parameter | Section 11.2a; window after dispatch before an un-actioned reminder transitions `pending → delivery_miss`. Not fixed by any source document; tracked as an open configuration item (Section 16), same treatment as the queue bound above |

## 12. Performance and Measurement Requirements

Per source paper NFR-1/NFR-2, restated here with the same honesty
convention the template requires: **no measured figures exist yet.**

- **NFR-H1 Latency gate (target: 1–3 seconds; status: at risk).**
  Warm-path latency from wake-word detection (at
  the edge, per `wake_word_detected_at` in `start_audio`, Section 7.3) to
  **TTS onset at the host** — i.e. the point the host begins synthesis
  output, not the point the participant hears it — is targeted at 1–3
  seconds. `latency_ms` (Section 8.3) is computed as `tts_onset_time -
  wake_word_detected_at`, both compared on the **host's clock**: the host
  translates the edge-supplied `wake_word_detected_at` into host-clock time
  at `start_audio` receipt using the one-time clock-offset handshake
  Section 7.4 defines (`clock_sync_request`/`clock_sync_response`, closes
  RID-009) rather than comparing raw edge and host timestamps directly,
  since the two clocks are not assumed to agree. If that handshake has not
  completed for the connection, the host falls back to measuring only the
  host-observable interval (`start_audio` receipt to TTS onset) and flags
  the row as `latency_basis: host_observed_only` (Section 7.4) rather than
  silently reporting a number that claims to include wake-word-to-network
  latency it did not actually measure.

  **Scope of the metric (closes RID-032).** `latency_ms` deliberately ends
  at TTS onset at the host, not at acoustic output at the edge — it
  excludes the Section 8.4 downlink transmission and the ~250ms
  ring-buffer low-water mark before playback actually starts. Extending
  the metric to the true point of acoustic output would require a new
  edge-to-host timestamp report (e.g. an edge-side `playback_started`
  event) and would put that report on the same clock-sync dependency as
  `wake_word_detected_at` above, which is a protocol addition, not a
  same-pass edit, and is not undertaken in this revision. NFR-H1's 1–3s
  target is restated accordingly: it targets *wake-word-to-host-TTS-onset*
  latency, not wake-word-to-audible-speech latency, and the ~250ms
  low-water mark plus downlink transmission time (Section 8.4, `CC-003`)
  are a known, separately-budgeted addition on top of whatever `latency_ms`
  reports, not folded into it.

  **Evidence as of this revision.** The GPU/latency harness (`report.md`)
  measured the LLM-only warm-path segment at 2.605s — a genuine PASS, but
  against the isolated LLM segment only, not the full interval NFR-H1
  specifies. STT, openSMILE, transport framing (CC-001/CC-002), playback
  buffering (CC-003) and wake-word detection are outside that measurement.
  Summed, the measured floor for the full turn is approximately **2.948s
  (98% of the 3s ceiling)**, with a realistic full turn of **3.3–4.4s** —
  outside target — and approximately **3.90s** before openSMILE, Piper or
  the wake-word engine's own contribution are measured at all. The signed
  disposition letter (`SYNCRO-panel-dispositions-signed.md`) corroborates
  this independently of the harness breakdown: it reports to the panel
  that the 17 August GPU evaluation shows the stages already measured
  consume 98 percent of the latency budget while two of the five pipeline
  stages are not yet installed, and names closing that gap the team's
  immediate engineering priority. This target
  is therefore restated as **at risk**, not unmeasured and not met: the
  1–3s range itself is retained pending the full end-to-end benchmark this
  revision does not yet have, but it must not be presented or reported as
  passing on the strength of the isolated LLM-segment figure alone.

  The host must log actual per-interaction latency (FR-H13) so this target
  can be checked empirically once a full-pipeline benchmark exists — no
  figure, isolated-segment or assembled, may be presented as an
  already-validated full-turn result until that benchmark is run.
- **NFR-H2 VRAM headroom (target, not yet measured).** The host's LLM
  runtime must operate within the GPU's available VRAM (RTX 4060, 8GB) with
  no persistent background service causing severe degradation. The
  specific ~1.68 GiB margin cited in the source paper is a target
  computed against a specific model choice and is out of scope here (ML
  model spec excluded by request) — the host's obligation is to expose a
  way to measure actual VRAM usage at runtime, not to guarantee a specific
  number.
- **NFR-H3 Latency logging.** Every interaction's latency must be written
  to the decision trace (Section 8.3, `latency_ms`) regardless of whether
  it meets the target, so the target vs. achieved gap is auditable rather
  than assumed.
- No nominal or assumed latency figure may be surfaced anywhere (console,
  logs-as-displayed) as if it were measured. This mirrors the "measured vs.
  nominal" distinction required of frame-rate reporting in comparable
  real-time systems.

## 13. Degraded and Error Conditions

Fulfills FR-17/source paper's degradation-fallback design. Checked in order
at dispatch time; each writes a `degradation_reason` to the decision trace.

**This path is not the primary or normal delivery channel.** The screen/
console notification below fires only when the audio channel cannot deliver
the reminder at all. It exists to make the system's graceful degradation —
simpler rather than silent when audio is unavailable — an auditable,
reportable reliability measure, not to serve as an alternate delivery path
in normal operation. Implementations must not route reminders here as a
matter of course; every row produced by this path must carry a
`degradation_reason` proving audio delivery was actually attempted and
failed.

| Condition                                   | `degradation_reason`      | Host behavior |
|-----------------------------------------------|-----------------------------|----------------|
| Physical mute engaged on edge (via `condition_report`, Section 7.3) | `mute_engaged`               | Fallback to console/screen notification |
| No audio output device claimable (via `condition_report`) | `audio_device_unavailable` | Fallback to console/screen notification |
| Edge-reported playback call exceeds 5s without completing (`play(audio)` on the edge, `robot-runtime-spec.md` Section 9 — not host-side synthesis duration, which the edge cannot observe or report on) | `tts_timeout`                 | Fallback to console/screen notification |
| Playback failure (non-zero return, via `condition_report`) | `playback_error` | Fallback to console/screen notification |
| Playback buffer underrun mid-stream (edge-reported) | `playback_underrun` (Section 8.4) | **Not a fault.** Resume playback once buffer refills past the low-water mark; interaction continues. Only escalates to `delivery_failed` below if `tts_audio_end` never arrives at all |
| Both speaker and console session unavailable  | `delivery_failed`             | Queue reminder, retry at next policy tick, increment attempt count. Queue is bounded per user (Section 11.3); overflow, outage tracking and drain behavior are Section 13.1 |
| `frame_count` mismatch at `end_audio` (edge-reported count vs. frames actually received) | n/a (logged separately) | Not a connection fault by itself — TCP already guarantees order/completeness on a live connection, so this indicates an edge-side counting bug or early `end_audio`, not lost frames (Section 8.2). Continue processing the buffer as received if reconstructable; else treat as malformed input |
| Malformed/unreconstructable audio              | n/a — surfaced as `error` WS message (`error_code: malformed_audio`, Section 7.3) | Reject utterance, do not run Nodes 1–4 on incomplete data |
| `session_id` collision (`start_audio` while session already in flight) | n/a — surfaced as `error` WS message (`error_code: session_collision`, Section 7.3) | Reject new session, keep existing one running |
| Session in-flight past the inactivity timeout with no further frames | `session_timeout` (Section 7.4) | Send `error` (`error_code: session_timeout`), discard buffer, free `session_id` |
| Intent confidence below threshold              | n/a (FR-4 path, not a failure) | Route to clarification response, still logged as a normal decision-trace row |
| Idle signal absent/stale at deferred-item release time (Section 11.1 R2/R4; idle-release rule detailed in `robot-runtime-spec.md` Section 8.2, host-executed) | `activity_unavailable` | Deliver at the grace-window deadline as normal (Section 11.3) — this is not an audio-delivery failure; `degradation_reason` here records that the idle-based early-release optimization could not be attempted, not that TTS delivery itself failed |

### 13.1 Queue Bound, Outage Tracking and Drain (fulfills D7; closes RID-015, CC-004)

- **Bound.** The `delivery_failed` queue is bounded **per user**. This is the behavioral
  contract D7 requires — a fixed-capacity store. It must be set — sized against the
  expected per-user reminder rate and expected outage duration once those are known — before
  implementation/testing, and whatever value is chosen remains subject to the drop-oldest,
  outage-tracking and reconnect-drain contract this section defines regardless.
- **Overflow.** When a user's queue is at its bound and a new entry would be added, the oldest
  queued entry for that user is dropped (drop-oldest) to make room, and a decision-trace row is
  written for the dropped entry with `degradation_reason: queue_overflow` (Section 8.3) —
  distinct from `delivery_failed` — so a drop is an auditable record, not a silent loss. This
  preserves the "never silently dropped" intent of the original wording while making the queue
  actually bounded.
- **Outage record.** A per-user outage entity (Section 9, `outages`) tracks contiguous periods
  of delivery failure:
  - Opens (a new row is inserted, `ended_at` null) on the first `delivery_failed` write for a
    user while no outage is currently open for that user.
  - `affected_interaction_count` increments on every subsequent `delivery_failed` or
    `queue_overflow` write for that user while the outage remains open.
  - Closes (`ended_at` set to the current timestamp) at the first successful audio delivery to
    that user after the outage opened.
  This is the outage counter D7 requires, and satisfies RID-015: downtime is measured data
  (start, end, affected-interaction count) rather than inferred from the absence of rows.
- **Drain.** Closing an outage is also the drain trigger. Every entry still queued for that user
  at close time is dispatched in FIFO order (oldest first) starting at the next policy tick.
  Drain does not bypass the normal delivery/retry path (Section 13 table, `delivery_failed` row)
  — it is that path applied to the backlog in order, so per-entry attempt counts and retry
  logic still apply during drain.

## 14. Constraints, Conventions and Sources of Truth

- **NFR-4 / NFR-10 / NFR-11 Data boundary and deletion right.** No
  commercial cloud service processes participant data. Audio and derived
  data cross a network boundary from each participant's home to the
  team-operated host server. The following protections apply and are not
  optional:
  - **In transit:** WireGuard tunnel between each edge client and the host;
    no interaction data traverses any other network path.
  - **At rest:** encryption at rest on the host's data store (audio,
    transcripts, derived features, decision traces).
  - **NFR-11, the participant's right to deletion** (source paper's
    Ethical Considerations section), is fulfilled by `POST
    /v1/data-deletion-request` (Section 6.5, FR-H11a). This document had
    not previously stated this requirement's own name anywhere, despite
    building the endpoint that fulfills it and citing it throughout —
    every other NFR in this section gets its own declaration here; this
    is NFR-11's.
  - **Retention and deletion schedule** (closes RID-014 — previously this
    document specified `POST /v1/data-deletion-request` (Section 6.5)
    without ever stating what exists for it to delete):
    - **Raw audio.** Never persisted. Held only in the per-session,
      in-memory buffer (Section 8.2) while STT decoding is in progress;
      discarded immediately once `end_audio` processing completes and the
      transcript is produced. No table in Section 9 stores audio, and none
      is added by this revision.
    - **Acoustic feature vectors** (openSMILE output, FR-H7). Computed
      in-memory per interaction from the same buffer; discarded once the
      affect classifier has run. Not persisted, not in Section 9.
    - **Transcript text.** Not persisted verbatim. The decision-trace
      record (Section 8.3) stores `intent`, `intent_confidence`, and
      derived context IDs — never the transcript string itself. If a
      future revision needs transcripts retained (e.g. for qualitative
      coding), that is a schema addition and a fresh consent/ethics
      question, not something this document currently provides for.
    - **Structured/derived data that is persisted** — every table in
      Section 9 (`tasks`, `routine_log`, `decision_trace`,
      `activity_buckets`, `lead_time_state`, `outages`, and the
      consent/self-report/exit-survey tables): retained until the earlier
      of (a) study completion plus a **6-month analysis window**, or (b)
      the participant invoking `POST /v1/data-deletion-request` (Section
      6.5, FR-H11a). The 6-month figure is this document's proposed
      default, not yet adviser-confirmed — tracked in Section 16 pending
      that confirmation, the same provisional treatment already applied to
      the architecture decision in that section.
    - **Schedule-triggered deletion mechanism.** A host-side scheduled job
      (run at the same cadence as the Section 13.1 policy tick, or daily —
      implementation's choice, since the window is measured in months, not
      minutes) checks each `user_id`'s earliest `created_at` across the
      tables above against the 6-month window and, on expiry, applies the
      identical per-table deletion Section 6.5 already defines for the
      participant-triggered path. This means Section 6.5's deletion logic
      has exactly one implementation with two triggers (participant
      request, or schedule expiry), not two separate deletion code paths
      to keep in sync.
  - **Controller status:** the team is the named RA 10173 data controller
    for this data.
- **NFR-12 Organizational data boundary.** The host must not access or
  process company emails, employer-confidential data, or anything beyond
  what the participant explicitly submits via the console task-entry
  endpoint (Section 6.1) or a connector submits via the external ingress
  endpoint (Section 6.1a) — and no connector is deployed against the latter
  during the study.
- **NFR-14 Authentication.** Two distinct auth scopes apply and must not be
  conflated: `POST /v1/tasks` (Section 6.1) and all console-facing endpoints
  require authentication scoped to the enrolled participant; `POST
  /v1/tasks/ingest` (Section 6.1a) requires authentication scoped to the
  connector/source instead, and a participant token must not be accepted on
  it. The concrete mechanism for each (token/API-key/session-cookie) is an
  open item (Section 16) but the presence of authentication, and the
  separation between the two scopes, is not optional.
- **NFR-6 Auditability.** The host must expose the Policy-Consistency Audit
  as an automated, deterministic check, scoped to decision-trace rows where
  `policy_rule != "n/a"` (Section 8.3, closes RID-019) — i.e. reminder
  delivery/defer interactions, the only ones Section 11.1's table governs.
  For each row in that domain: given the row's `(affect_level,
  deadline_proximity)`, does `policy_rule` match Section 11.1's table
  exactly? Rows outside the domain (`ask_status`, `request_summary`) are
  excluded before the comparison runs, not evaluated and flagged. This must
  be runnable as a batch query/script against `decision_trace`, not only
  inspectable manually.
- **Licensing/cost.** Per source paper Section XI.A, the host software stack
  (Ollama, LangGraph, FastAPI, SQLite, openSMILE, local STT, Piper) is
  entirely ₱0-cost, open-source or research-use-permitted. Any substitution
  during implementation must preserve this constraint.
- **Source-of-truth note.** This document is the authoritative statement of
  host-side contracts (API shapes, message schemas, DB schema). Where the
  source paper's prose and this document appear to conflict on a resolved
  detail (e.g., transport protocol, discovery mechanism), this document
  governs, since it resolves several items the paper explicitly left `TBC`.
- **Cross-reference naming convention (closes RID-031).** Every
  cross-article reference in this document and in `robot-runtime-spec.md`
  addresses `host-spec.md` / `robot-runtime-spec.md` — the unversioned,
  logical document titles — regardless of the version suffix in either
  article's actual filename on disk for a given revision (e.g. this
  revision's actual filenames carry a `_v12` suffix). This is deliberate,
  not an oversight left over from an earlier revision: a reference
  hardcoded to one revision's filename breaks on every subsequent revision,
  which is the failure this convention exists to avoid. Resolve a
  cross-article reference against whichever revision of the other article
  is current at read time.

## 15. Manual Verification Checklist

1. Start the host with no edge client connected. Connect a test edge
   client using a valid provisioned `device_token`. Confirm the
   connection is accepted and `connect_success` is logged (Section 10.2,
   10.3).
1a. Repeat with an invalid or missing `device_token`. Confirm the
   connection is rejected and `connect_failed` is logged, not silently
   accepted (Section 10.2).
2. Connect a test WebSocket client, send `start_audio`, confirm `ready` is
   returned before any `audio_frame` is sent (Section 7.2).
3. Stream a known short utterance as `audio_frame` messages, send
   `end_audio`, confirm a `response` message is returned containing
   `tts_text`, `policy_rule`, and `lead_time_min` (Section 8.1).
4. Deliberately send a binary `audio_frame` whose byte length is not a
   multiple of 2 (not a whole number of 16-bit samples). Confirm the host
   surfaces `error_code: malformed_audio` (Section 8.2, Section 13) rather
   than silently proceeding — the equivalent check for the current
   no-header binary format; a `sequence_number` gap is no longer a state
   the host can observe (Section 8.2, closes CC-001).
5. Submit a task via `POST /v1/tasks` without an `Authorization` header.
   Confirm `401`, not silent acceptance (Section 14, NFR-14).
6. Submit a task with a missing `title`. Confirm `422` (Section 6.1).
6a. Submit a task via `POST /v1/tasks/ingest` with a valid source token,
   confirm `201` and a decision-trace/ingress-log row carrying that
   `source`. Repeat with the identical `(source, external_id)` pair and
   confirm `200` with no duplicate task row (Section 6.1a).
6b. Submit a task via `POST /v1/tasks/ingest` containing an unrecognized
   field. Confirm `400`, not silent acceptance of the extra field (Section 6.1a).
6c. Submit a task via `POST /v1/tasks/ingest` using a valid *participant*
   token from Section 6.1 instead of a source token. Confirm this is
   rejected — the two auth scopes must not be interchangeable (Section 14,
   NFR-14).
6d. Seed a test participant with rows across all nine scoped tables
   (`tasks`, `routine_log`, `decision_trace`, `activity_buckets`,
   `lead_time_state`, `outages`, and the three instrument tables; Section
   9), call `POST /v1/data-deletion-request` with `confirm: true`, and
   confirm every row for that `user_id` is gone across all nine tables, not
   just `tasks` (closes RID-027, previously underspecified as six). Confirm
   `200 OK` is returned (not `202`), and separately
   confirm the `users` row and the `deletion_receipts` row both still
   exist for that `user_id` — their retention is intentional, not a gap in
   this step. Then repeat the same call with the same `client_write_id`;
   confirm `200 OK` with the original receipt read back from
   `deletion_receipts`, not a `404` (the participant's other data is by now
   already gone, which must not be mistaken for an invalid `user_id`) and
   not a second deletion attempt against tables that are already empty
   (Section 6.5, FR-H11a).
6e. With the host unreachable, use the console to enter a task and submit a
   daily self-report. Confirm both remain usable and locally persisted
   against the agent's own cache, not blocked or lost (Section VI of source
   paper; FR-H11/FR-H11b). Bring the host back online and confirm the
   queued writes sync via `POST /v1/tasks` with `200`/`201` behavior keyed
   on `client_write_id`.
6f. Replay an already-synced `client_write_id` a second time (simulating a
   retry after a dropped sync-ack). Confirm `200`, not a duplicate task row
   (Section 6.1, FR-H11b).
7. Trigger a Low/not-imminent scenario and confirm the resulting
   decision-trace row has `policy_rule = R1` (Section 11.1). Repeat for one
   scenario per rule R2–R5.
8. Run the Policy-Consistency Audit query against a batch of seeded
   decision-trace rows with one intentionally mismatched row and at least
   one `ask_status`/`request_summary` row (`policy_rule: "n/a"`); confirm
   the audit flags exactly the mismatched row and does not flag the `n/a`
   row (Section 14, NFR-6).
9. Simulate a `tts_timeout` condition and confirm `degradation_reason =
   tts_timeout` is written and a fallback notification path is invoked
   (Section 13).
10. Confirm no outbound network call is made to any non-local address
    during a full interaction (packet capture or firewall rule audit)
    (Section 14, NFR-4/NFR-10).
11. Restart the host mid-session (kill and relaunch). Confirm a
    reconnecting edge client can complete a new interaction without a
    manual host-side configuration step (Section 10).
12. Submit an utterance whose classified intent confidence lands below the
    active pilot threshold (Section 11.3). Confirm the response routes to a
    clarification message rather than executing any action, and confirm
    the raw confidence score is still written to the decision-trace row
    regardless (Section 5, FR-H4).
13. Seed a test participant with multiple pending tasks at different
    deadlines (including one overdue) and a recent break/routine-log entry.
    Trigger an interaction. Confirm `retrieved_context_ids` (Section 8.3)
    reflects top-k upcoming tasks by deadline proximity, the most recent
    break/routine entry, and the overdue task (Section 5, FR-H5).
14. Trigger two interactions with different classified intents against the
    same seeded context. Confirm the resulting `tts_text` differs in a way
    that reflects the different intent/context, rather than being a static
    per-intent template (Section 5, FR-H6).
15. Run one neutral-toned and one distressed-toned test utterance through
    the pipeline. Confirm `affect_level` (Section 8.3) is populated with
    one of Low/Moderate/High for each, and confirm total interaction
    latency is not measurably increased by this check relative to a
    baseline run — i.e., it ran in parallel with Nodes 1–3, not serially
    after them (Section 5, FR-H7; Section 2).
16. Seed a decision-trace row with one required field deliberately left
    null (e.g. `policy_rule` on a row that should carry one). Confirm this
    is flagged as a spec violation by the completeness check the
    Policy-Consistency Audit depends on (Section 8.3), not silently
    accepted as a valid partial row (Section 5, FR-H12).
17. Complete a task via the console (`PATCH .../status=completed`, Section
    6.3). Confirm `completed_at` is set on the task row and `latency_ms` is
    present on the corresponding interaction's decision-trace row (Section
    5, FR-H13).
18. For one test user, run three interactions in order with outcomes
    `accepted`, `snoozed` (by 5 min), and — by letting the reminder
    response window elapse with no action — `delivery_miss`. Confirm `L`
    updates per the Section 11.2 EMA rule after the first two, is left
    unchanged by the third, and never leaves `[5, 60]` even from an
    extreme `snooze_minutes` value (Section 5, FR-H14; Section 11.2a).
19. During a multi-session load test (Section 12), sample `nvidia-smi`
    VRAM usage across the run. Confirm no out-of-memory or
    severe-degradation event occurs (Section 12, NFR-H2).

### 15.1 Requirement Traceability Matrix (closes RID-005)

Previously, no mapping from requirement to verification step existed in
either article — coverage could only be assessed by inspection, and by
that method 11 of the host's 20 requirements and 5 of the edge's 12 had no
step at all (see the finding this closes). The table below maps every
FR/NFR in this document to at least one item above, or records an explicit
justification where a manual checklist step is not the right verification
form for that requirement.

| Requirement | Verified by | Note |
|:--|:--|:--|
| FR-H1 | Items 2, 4, 5(NFR-R3 cross-check) | Transport/buffering behavior; streaming is exercised by item 5 on the edge side and mirrored here by item 2 |
| FR-H2 | Item 3 | Transcript production is exercised implicitly (a `response` cannot be produced without it); accuracy is out of scope (ML model internals excluded, Section 1) |
| FR-H3 | Items 3, 12 | Normal-confidence and below-threshold paths respectively |
| FR-H4 | Item 12 | New |
| FR-H5 | Item 13 | New |
| FR-H6 | Item 14 | New |
| FR-H7 | Item 15 | New |
| FR-H8 | Item 7 | Existing — one scenario per rule R1–R5 |
| FR-H9 | Item 3 | `response` payload shape |
| FR-H10 | Items 6a, 6b | Ingress endpoint |
| FR-H10a | Items 6, 6c | Participant task entry, auth-scope separation |
| FR-H11 | Item 6e | Console usable offline |
| FR-H11a | Item 6d | Deletion covers all scoped tables |
| FR-H11b | Items 6e, 6f | Sync-on-reconnect, replay idempotency |
| FR-H12 | Items 3, 8, 16 | Field presence, audit consistency, and completeness respectively |
| FR-H13 | Item 17 | New |
| FR-H14 | Item 18 | New |
| NFR-H1 | Not a checklist item — closed by the dedicated latency benchmark (Section 12) | A single manual pass cannot establish a warm-path latency distribution; this is an explicit, recorded justification, not an omission |
| NFR-H2 | Item 19 | New |
| NFR-H3 | Item 16 (structural) | `latency_ms` is a non-nullable decision-trace field (Section 8.3); any row missing it already fails item 16's completeness check, so no separate step is needed |
| NFR-4/NFR-10 | Item 10 | Existing |
| NFR-6 | Item 8 | Existing |
| NFR-11 | Item 6d | Existing (shared with FR-H11a) |
| NFR-12 | Item 13 (incidental) | Scoping is structural (foreign keys, Section 9); item 13's query is per-`user_id` by construction |
| NFR-14 | Items 5, 6c | Existing |

## 16. Open Items Register

Explicit `TBC` items still genuinely open, carried forward rather than
invented (per project decision to keep these open):

- Exact VRAM margin for `llama3.1:8b-instruct-q4_K_M` on the confirmed RTX
  4060, now co-resident with the confirmed STT engine (faster-whisper) —
  hardware, LLM, and STT are all now locked, so this is measurable and
  should be benchmarked (e.g. `nvidia-smi` during a live inference call)
  on a verified-idle GPU, rather than left as a projected figure (Section 4).
- Concrete authentication mechanism (token vs. session vs. mTLS) for each of
  the two auth scopes: participant-scoped (`POST /v1/tasks` and console
  endpoints) and source-scoped (`POST /v1/tasks/ingest`) — unresolved. The
  scopes themselves, and that they must not be interchangeable, are settled
  (Section 14, NFR-14); only the concrete mechanism is open.
- Wake-word engine's native frame length, to confirm the uplink ring-buffer
  unit (provisionally 20 ms / 640 bytes, Section 8.2) is sized to it rather
  than to a round millisecond count — the format itself (16 kHz/16-bit/
  mono/PCM) is resolved (closes CC-002); this is the one narrower number
  still pending, blocked on the microphone model (`robot-runtime-spec.md`
  Section 16).
- `build_id` format/versioning scheme and where firmware/host version
  compatibility is checked, now that the mDNS TXT-record mechanism is
  removed (Section 10) — whether this moves to session-start validation
  (Section 7.4) or is dropped entirely is open; must be resolved
  identically with `robot-runtime-spec.md` (Section 16 there).
- Local storage format and sync-queue implementation for the companion
  agent's console cache (FR-H11b) — that writes must be cached locally and
  synced with idempotency keys is settled; the concrete local store (e.g.
  IndexedDB, SQLite-on-device) and retry/backoff policy for queued syncs
  are open.
- **Reminder response window** (Section 11.2a, Section 11.3) — that a
  window exists, that it drives the `pending → delivery_miss` transition,
  and that the policy-tick scheduler is its owner, are all fixed as of
  this revision. The numeric duration is not: like the queue bound below,
  it is a deployment/configuration parameter, best set from observed
  time-to-respond data rather than guessed, and is to be confirmed before
  implementation/testing.
- **Retention-window adviser confirmation** (Section 14) — the 6-month
  post-study analysis window is this document's proposed default for
  Section 14's retention-and-deletion schedule, not yet confirmed by the
  adviser/ethics reviewer. The deletion mechanism itself (Section 14,
  Section 6.5) does not depend on the specific number and needs no
  rework if the confirmed figure differs; only the constant changes.
- `delivery_failed` queue bound, per user (Section 11.3, Section 13.1) —
  that the queue must be a fixed capacity, and the overflow policy
  (drop-oldest), are fixed as of this revision, satisfying D7's behavioral
  contract in full. The numeric capacity itself is not fixed by D7 or
  `roadmap.md` and remains open: it is a deployment/configuration
  parameter, to be set (informed by expected per-user reminder rate and
  expected outage duration) before implementation/testing and confirmed
  before the live DEL-07 demonstration (26 September 2026). This does not
  reopen CC-004 — D7 requires the behavior, not a number — but it is a
  genuine open item, not future tuning of an already-fixed default.
- **Written adviser/panel confirmation of the centralized-host architecture
  and revised privacy claim — status: PENDING, blocking.** Sections 4 and
  14 of this document specify the centralized architecture
  unconditionally, per `SYNCRO-redesign-15k.md` §3–§6, which the article
  author holds. That document itself states (§10, action item 1) that
  this is a thesis-level decision requiring adviser sign-off **before
  anything is built against it**, and does not itself constitute that
  sign-off. As of this revision, no written confirmation is on file and
  none is inferable from anything the author holds — **Sections 4 and 14
  are written as settled but remain provisional on this approval, not yet
  authorized.** This is what is being waited on, and nothing else in
  either article is blocked by it. **Owner: article author (Almedejar).
  Action: obtain the adviser's written confirmation and cite the record
  here (replacing this entry's status), or, if it is not obtainable before
  Week 2 transport work (WP-105, WP-106) begins, escalate the absence to
  the adviser rather than let implementation proceed against an
  unconfirmed premise.**