# SYNCRO Host - Architecture Review

| | |
|---|---|
| **Author** | Morgan Blue |
| **Date** | 12 September 2026 |
| **Subject** | Host-side software (`syncro-robot-host`), readiness for WP-105 / WP-107 / WP-108 / WP-401 |
| **Baseline reviewed** | `origin/main` @ `793ec91` (PR #3, WP-103 merged) |
| **Also examined** | `origin/feature/wp-104` @ `5132c9b`, `origin/feature/observability-logging` @ `e695c06` |
| **Test baseline** | `python -m pytest -q` on `793ec91`: 186 passed, exit 0, 1.25 s |
| **Status** | Final |

---

## Contents

1. Purpose and scope
2. Summary verdict
3. Method and evidence standard
4. What the system is today
5. What the next work packages demand of it
6. Findings - blocking
7. Findings - structural
8. Integration risk: `feature/wp-104` against trunk
9. Trace-field ownership
10. Recommended target shape
11. Sequencing
12. Housekeeping
13. Appendix A - verification log
14. Appendix B - files read

---

## 1. Purpose and scope

The sprint enters its compressed phase this week: WP-105 (transport), WP-106 (firmware module
specs), WP-107 (wake word), WP-108 (latency budget) and the WP-401 integration push all land
between now and the 26 September freeze. This review asks one question of the host codebase as it
stands on trunk:

> Will the current architecture absorb that work without a redesign, and will the result be
> something the team can still change quickly after the freeze?

It is a review of structure, seams and contracts. It is not a code-quality audit, not a security
audit, and it does not assess the affect classifier's ML method (that is WP-104's own evidence
folder). Where a defect is cited it is because it reveals a structural gap, not because it is a
bug worth fixing on its own.

Scope: everything under `adapters/`, `api/`, `audio/`, `composition/`, `config/`, `pipeline/`,
`storage/`, `scripts/`, `tests/`, plus `techdocs/SPEC.md` sections 7, 8, 12, 13 and the sprint
plan. Out of scope: edge firmware, the console, the ML training pipeline under `ml/`.

## 2. Summary verdict

**The skeleton is sound and should be kept. The edges of the graph are not ready.**

What is right, and should not be touched:

- Technology-neutral `Protocol` contracts for STT, LLM, TTS, intent, audio in/out
  (`adapters/contracts.py`, `audio/contracts.py`).
- One composition root (`composition/bootstrap.py`) that constructs every concrete dependency;
  nodes and the graph receive their collaborators and never import an adapter.
- Pipeline nodes as factory functions returning closures over injected dependencies.
- Storage split into a connection owner (`SQLiteDatabase`), DDL in one module (`schema.py`),
  and repositories that acquire connections through a context manager that closes on both paths.
- Tests that use `tmp_path` and a real SQLite file for anything touching storage, and fakes for
  everything else. The suite runs in about a second, which is what makes it usable under
  pressure.

What is not ready, in order of consequence:

| # | Finding | Blocks | Severity |
|---|---|---|---|
| F1 | The decision-trace row is written inside the graph, before TTS runs, so `latency_ms` cannot measure the interval NFR-H1 defines and cannot be corrected afterwards | WP-108, WP-105 | Blocking |
| F2 | The trace contract cannot represent a degraded interaction (no intent, no affect) that SPEC 7.4 / 13 require rows for | WP-105 | Blocking |
| F3 | There is no shared interaction runner; capture -> graph -> TTS -> playback orchestration exists only inside `scripts/run_wp103.py` | WP-105, WP-401 | Blocking |
| F4 | Node and adapter failures propagate as five unrelated exception types with no mapping to the wire `error` message or to a trace row | WP-105 | Blocking |
| F5 | Any per-stage key written by more than one node crashes the existing STT/affect fan-out unless it carries a reducer | WP-105, WP-108 | Blocking (proved) |
| F6 | Two sequential 8B-model round trips per turn, synchronous, with a 60 s timeout that exceeds the 30 s session timeout | WP-108, W5 failure drills | Blocking (budget) |
| S1-S9 | Structural: async boundary, bootstrap return type, storage pragmas, schema versioning, downlink audio path, auth/clock-sync seams, trace-field ownership, known deferred items | WP-105 onward | Should fix |
| I1 | `feature/wp-104` touches every product module and adds an enum value that is not in SPEC 13 | branch cut for WP-105 | Decide first |

None of the blocking findings requires abandoning a design decision already made. They are
missing pieces at the boundary between the graph and the world, and they are small. The
recommendation in section 10 is roughly two days of work and leaves every existing test intact.

## 3. Method and evidence standard

- Every product module on `origin/main` was read in full (Appendix B). The branch was checked
  out into a detached, throwaway worktree so the working tree on `main` was never switched.
- The full test suite was run on that checkout (Appendix A).
- Claims about LangGraph runtime behaviour were tested against the installed version
  (`langgraph==1.2.11`) with a probe script, not asserted from documentation (Appendix A).
- Latency figures are quoted from `techdocs/profile-full-report-rtx-4060.md` and from
  `techdocs/SPEC.md` section 12. No new latency measurement was taken: the live runners need a
  microphone, an Ollama server and a Piper voice, none of which were available to this review.
- File references are `path:line` against `793ec91`.

Where this document says "will", it means "follows from the code as it is". Where it says
"likely", it is a judgment and is marked as such.

## 4. What the system is today

### 4.1 Runtime shape

Two pipelines coexist:

- **WP-102 `HostPipeline`** (`pipeline/host_pipeline.py`): a linear capture -> STT -> LLM ->
  TTS -> playback class with a per-stage error boundary (`PipelineStageError(stage, cause)`)
  and per-stage durations. Still constructed by `build_wp102_pipeline` and pinned by
  `tests/test_wp102_architecture.py`.
- **WP-103 dialogue graph** (`pipeline/graph.py`): a LangGraph `StateGraph` over
  `DialogueState`. `START` fans out to `node1_stt` and `affect` in parallel; the STT branch
  continues through `node1_intent -> node2_context -> node3_llm`; `node4_policy` joins the LLM
  draft with the affect result; `output` builds the `response` payload and writes the decision
  trace. TTS and playback happen **after** `graph.invoke` returns, in the caller.

The second is the production path. The first is kept for the WP-102 demonstration item.

### 4.2 Data flow per interaction (trunk)

```
scripts/run_wp103.py
  ensure_user(user_id)
  audio_input.capture()                       5 s fixed-length sounddevice recording
  graph.stream(state)                         sync; nodes run in LangGraph's executor
     node1_stt      WhisperSTTAdapter.transcribe        blocking, CPU by default
     affect         DevelopmentAffectDetector.detect    constant "Low"
     node1_intent   OllamaIntentClassifier.classify     HTTP POST /api/generate, format=json
     node2_context  SQLiteStore.retrieve_context
     node3_llm      OllamaLLMAdapter.generate           HTTP POST /api/generate
     node4_policy   apply_policy + get_lead_time (+ R5 suppress write)
     output         ensure_user + save_decision_trace   <-- trace row written HERE
  tts.synthesize(final_response)              Piper, whole utterance to WAV in memory
  audio_output.play(...)                      sounddevice
```

### 4.3 Storage

SQLite, `PRAGMA foreign_keys = ON` per connection, a new connection per repository call. Eleven
tables from SPEC 9; only `users`, `tasks`, `routine_log`, `decision_trace` and
`lead_time_state` have any reader or writer today. `DecisionTraceRepository` exposes `save`,
`suppress_pending_reminder_traces`, `list_for_user`. Nothing writes `lead_time_state`.

### 4.4 API surface

`api/app.py` mounts one router (`/health`). `api/ws/stream.py` is a zero-byte file.
`config/endpoints.py` declares thirteen paths; one is served. There is no lifespan hook, no
`app.state`, and nothing connects the FastAPI application to `build_wp103_components`.

### 4.5 Configuration

`config/settings.py`: a frozen dataclass populated from environment variables, cached once per
process. `load_dotenv()` runs at import. Relevant defaults: `stt_device="cpu"`,
`ollama_timeout_s=60.0`, `session_timeout_seconds=30`, `llm_model="llama3.1:8b-instruct-q4_K_M"`
used for both the intent classifier and the reasoner.

### 4.6 Observability

None. There are zero `import logging` statements on trunk. Stage visibility is `print` in the
runner scripts. `techdocs/OBS-LOG.md` on the observability branch is a 431-line specification
with no implementation behind it.

## 5. What the next work packages demand of it

Drawn from the sprint plan (section 3, WBS 1) and SPEC sections 7, 8, 12, 13.

| WP | Exit condition | Concrete host requirements |
|---|---|---|
| WP-105 transport | Endpoints serve the edge unit; every stage emits a timestamped record | `ws /v1/stream`; per-connection auth (deferred to BL-03 for the demo but the seam must exist); `clock_sync_request/response` per connection; `start_audio` / binary `audio_frame` / `end_audio` uplink; session registry with collision rejection and a 30 s inactivity timeout that writes a `session_timeout` trace row; `response` then paced `tts_audio_frame` stream at 16 kHz int16 100 ms chunks then `tts_audio_end`; `condition_report` handling that updates `degradation_reason` on an existing row or logs standalone; `network_event` logging; a request queue with instrumented depth; per-stage latency records |
| WP-107 wake word | Measured false-accept / false-reject | Host consumes `wake_word_detected_at` from `start_audio` and uses it for `latency_ms` when clock sync has completed |
| WP-108 latency budget | Per-stage table populated from real measurements | Every stage timed on every interaction; `latency_ms` as SPEC 12 defines it (wake word to TTS onset, host clock); nothing nominal presented as measured |
| WP-401 integration | Full loop runs once on real hardware | All of the above, plus a failure mode that returns the edge to Standby via `error` rather than hanging |

The rest of this document measures the trunk against that table.

## 6. Findings - blocking

### F1. The trace row is written too early to satisfy NFR-H1 / NFR-H3

**Where.** `pipeline/nodes/output.py:139-148`. The output node computes

```python
latency_ms=max(0.0, (monotonic() - float(started_monotonic)) * 1000.0),
latency_basis="host_observed_only",
```

then calls `store.save_decision_trace(...)`. `started_monotonic` is set by the caller before the
graph starts. TTS runs after the graph returns (`scripts/run_wp103.py:101`).

**Why it matters.** SPEC 12 defines `latency_ms` as `tts_onset_time - wake_word_detected_at`
on the host clock, and NFR-H3 requires it on every row. The value written today stops at the
output node, which is before TTS onset, so it under-reports by the full synthesis time on
every interaction. `latency_basis` is a string constant; the `wake_word_to_tts` value can never
be written. `wake_word_detected_at` is declared in `DialogueState` (`pipeline/state.py:13`)
and read by nothing.

**Why it is structural.** The repository has no update-in-place for latency
(`storage/decision_trace.py:24-57`: `save`, `suppress_pending_reminder_traces`,
`list_for_user`). The row is immutable once the output node returns. WP-108's entire
deliverable is this number; there is currently no place in the code where the correct number
is knowable and the row is still writable.

**Decision required.** One of:

- (a) Move trace finalisation out of the graph. The output node assembles the record and
  returns it in state; the interaction runner (F3) writes it after TTS onset, with the real
  latency and basis. Cleanest; the graph stops having a side effect on the store for the
  common path.
- (b) Keep the in-graph write and add
  `DecisionTraceRepository.finalize_latency(trace_id, latency_ms, latency_basis)`, called by
  the runner at TTS onset. Smaller diff; leaves two writers for one row.

Recommendation: (a). It also resolves half of F2 and F4 for free, because the runner becomes
the one place that knows whether the interaction completed.

### F2. The trace contract cannot express a degraded interaction

**Where.** `pipeline/contracts.py:53-77`. `DecisionTraceRecord` requires `intent: str`,
`intent_confidence: float` in [0, 1], `affect_level: Literal["Low","Moderate","High"]`,
`policy_rule`, `action_taken`, `lead_time_min`, `reminder_outcome`. The output node
additionally requires a non-empty `final_response` and raises `RuntimeError` on any missing
key (`pipeline/nodes/output.py:22-40`).

**What SPEC requires.** Rows for interactions where none of those exist:

- SPEC 7.4: session inactivity timeout - "writes a decision-trace row with
  `degradation_reason: session_timeout`". No audio was transcribed; there is no intent.
- SPEC 13.1: queue overflow - a row with `degradation_reason: queue_overflow` for a dropped
  entry.
- SPEC 7.3: `condition_report` with `session_id: null` - "a standalone log entry".
- SPEC 8.3: `degradation_reason` and `network_event` "must be populated (or explicitly null)
  on every logged interaction". On trunk both are hardcoded `None`
  (`pipeline/nodes/output.py:137-138`) and there is no writer.

**Why it is structural.** This is a gap between the specification and the type that enforces
it. Patching the output node to tolerate `None` would silently weaken validation on the
normal path. The choice is between:

- (a) A second record type, `DegradedTraceRecord`, sharing the identifying fields
  (`trace_id`, `session_id`, `user_id`, `timestamp`, `degradation_reason`, `network_event`,
  `latency_ms`, `latency_basis`) with the remaining columns written as `NULL`/`n/a`. Requires
  relaxing `NOT NULL` on `intent`, `intent_confidence`, `affect_level` in `storage/schema.py`.
- (b) A separate `degradation_log` table with its own record type, and a rule that the
  Policy-Consistency Audit never reads it. Keeps `decision_trace` fully populated as SPEC 8.3
  literally says, but SPEC 7.4 literally says the timeout row goes in the decision trace.

Recommendation: (a), with a `model_validator` that forbids a non-null `intent` when
`degradation_reason` is one of the no-interaction reasons. SPEC 8.3's "every field populated
or explicitly null" is satisfied; the audit already excludes `policy_rule == "n/a"` rows.
Either way the decision is a SPEC amendment and should be recorded as one.

### F3. There is no interaction runner

**Where.** `scripts/run_wp103.py:58-110` is the only code that performs the full sequence:
`ensure_user`, capture, `graph.stream`, per-node reporting, `tts.synthesize`,
`audio_output.play`. It does so with `print` and `try/except Exception: return 1`.

**Why it matters.** WP-105's WebSocket handler needs the identical sequence with a different
audio source (uplink frames), a different sink (paced downlink frames), a different failure
channel (`error` message) and real timing records. If the script remains the only
implementation, the handler will be a second copy, the two will drift, and every WP-108
timing change lands twice.

**Why it is structural.** The graph is a pure function from audio to a response payload. What
sits around it - session, timing, TTS onset, trace finalisation, failure mapping - has no home.
`HostPipeline` is that home for WP-102 and shows the pattern already works in this codebase.

**Recommendation.** Introduce `pipeline/interaction.py`:

```python
@dataclass(frozen=True, slots=True)
class InteractionResult:
    session_id: str
    trace_id: str
    response_payload: dict[str, Any]
    tts_audio: np.ndarray          # 16 kHz int16 after resampling (S5)
    tts_sample_rate: int
    stage_timings_s: dict[str, float]
    latency_ms: float
    latency_basis: str

class InteractionRunner:
    def __init__(self, *, graph, store, tts, resampler, clock=monotonic): ...
    def run(self, *, session: SessionContext, audio: np.ndarray, sample_rate: int) -> InteractionResult:
        # graph.invoke -> tts.synthesize -> resample -> finalize trace (F1) -> return
        # every failure is raised as InteractionError(stage, cause) (F4)
```

`SessionContext` carries `session_id`, `user_id`, `wake_word_detected_at`, the connection's
clock offset (or `None`), and `started_monotonic`. `scripts/run_wp103.py` becomes a thin
caller that builds a `SessionContext` with `clock_offset=None`; the WS handler builds one with
the negotiated offset. Both get the same timings and the same trace.

### F4. Failures have no boundary and no wire mapping

**Where.**

- `pipeline/nodes/stt.py:13,16`: `RuntimeError` on missing keys, `ValueError` on an empty
  transcript.
- `pipeline/nodes/intent.py`, `context.py`, `policy.py`, `output.py`: `RuntimeError`,
  `ValueError`, `TypeError`.
- `adapters/*`: `STTAdapterError`, `LLMAdapterError`, `TTSAdapterError`,
  `IntentClassifierError`, `AudioCaptureError`, `AudioPlaybackError`, each a direct
  `RuntimeError` subclass with no common parent.
- `pipeline/nodes/affect.py`: `AffectDetectionError`.

`graph.invoke` propagates whichever fires first, unwrapped.

**What SPEC requires.** SPEC 7.3 defines `error{error_code}` with three codes:
`session_collision`, `malformed_audio`, `session_timeout`. There is no code for "STT produced
nothing", "Ollama unreachable", "Ollama returned malformed JSON", "Piper failed". SPEC 13's
table is about delivery degradation, not pipeline failure. Yet SPEC 8.3 says every logged
interaction has a full row and SPEC 7.3 says receipt of `error` returns the edge to Standby.

**Consequence on trunk.** A silent 5 s capture (common in a demo room) raises `ValueError`
out of `graph.invoke`. In the script that is `return 1`. In a WS handler it is an unhandled
exception in the worker, no `error` frame, and an edge that waits until its own timeout.

**Recommendation.** One boundary, applied in the runner:

```python
class InteractionError(RuntimeError):
    def __init__(self, stage: str, cause: BaseException, *, wire_code: str | None): ...
```

with a single mapping table from `(stage, cause type)` to `(wire error_code, degradation_reason
or None, trace row yes/no)`. The three SPEC codes are insufficient; propose one addition to
SPEC 7.3, `pipeline_failure`, with `message` naming the stage. Recording that as a SPEC
amendment is part of the work. `HostPipeline._run_stage` is the existing precedent and can be
lifted almost verbatim.

### F5. Per-stage keys break the fan-out without a reducer (proved)

**Where.** `pipeline/graph.py:71-72`: `START -> node1_stt` and `START -> affect` run in the
same LangGraph superstep. `DialogueState` (`pipeline/state.py`) declares every key as a plain
type with no reducer, so every key is last-write-wins within a step and **rejects two writes
in the same step**.

**Proof.** Probe against `langgraph==1.2.11` (Appendix A, item 3): two parallel nodes each
returning `{"stage_timings": {...}}` raise

```
InvalidUpdateError: At key 'stage_timings': Can receive only one value per step.
Use an Annotated key to handle multiple values.
```

With `stage_timings: Annotated[dict, merge]` the same graph returns
`{'affect': 0.2, 'stt': 0.1}`.

**Why it matters now.** WP-105's exit condition ("every stage emits a timestamped record") and
WP-108 both want per-node timings. The obvious implementation - wrap each node factory in a
timer that adds `stage_timings[name]` - crashes on the first interaction. Separately,
`feature/wp-104` adds `degradation_reason: str | None` to state as a plain key written from
`affect`; the moment any second node writes it (F2's transport reasons, for instance), the
graph dies the same way.

**Recommendation.** Two reducer-carrying keys in `DialogueState`:

```python
stage_timings_s: Annotated[dict[str, float], _merge_dicts]
degradations: Annotated[list[str], operator.add]
```

and a `timed(name, node)` wrapper in `pipeline/graph.py` applied in `build_dialogue_graph`.
Put a test in `tests/unit/pipeline/test_graph.py` that asserts both parallel branches' timings
are present after one invoke; that test fails on the plain-key version and is the regression
guard.

### F6. LLM budget: two 8B round trips, synchronous, 60 s timeout

**Where.**

- `adapters/llm/intent_classifier.py:54` and `adapters/llm/ollama_adapter.py:30`: two separate
  `requests.post(.../api/generate)` per interaction, same model
  (`config/settings.py:51`), `stream=False`, no `num_predict`, no `keep_alive`.
- `config/settings.py:53`: `ollama_timeout_s = 60.0`. `session_timeout_seconds = 30`.
- `config/settings.py:59`: `stt_device = "cpu"`.

**Measured context.** `techdocs/profile-full-report-rtx-4060.md`: warm end-to-end for **one**
call at about 350 input / 120 output tokens is 2.605 s (three repetitions, 2.55-2.66 s).
SPEC 12 already restates NFR-H1 as *at risk* on that basis: "the measured floor for the full
turn is approximately 2.948 s (98% of the 3 s ceiling)". That floor counts one LLM call. The
trunk makes two. The two-call chain has not been measured by anyone.

**Consequences.**

1. Likely: the LLM stage alone is 3.5-5 s before STT, which puts every interaction outside
   NFR-H1 by construction. WP-108 will document this; it would be better to know today.
2. Certain: a stalled Ollama call holds the worker for 60 s. The session was declared dead at
   30 s and an `error{session_timeout}` sent, but the host is still blocked on the stale turn
   when the edge retries. This is exactly the W5 "model stalls" failure drill.

**Recommendation, cheapest first.**

- Add `num_predict` to the intent call (the JSON reply is under 40 tokens) and `keep_alive`
  to both so the model never unloads between turns.
- Split `llm_model` into `intent_model` and `reasoning_model`. A 1-3B instruct model handles
  seven-way JSON classification; this removes roughly one full generate from the budget.
- Derive stage timeouts from the session budget (`ollama_timeout_s` must be less than
  `session_timeout_seconds`, and the runner should cancel rather than wait).
- Default `stt_device` to `cuda` where available; the profile measured STT at 0.343 s versus
  1.562 s assumed, and the budget was computed with whisper co-resident on the card.
- Measure the two-call chain before any of this, and record it, so WP-108 has a before figure.

## 7. Findings - structural

These do not block the branch cut but each will cost more later than now.

### S1. Synchronous work under an asynchronous server

faster-whisper, Piper, `requests` and `graph.invoke` are all blocking. FastAPI WebSocket
handlers are coroutines. Running the graph inline in a handler blocks the event loop, which
means: no other connection's `clock_sync` is answered, the session-timeout timer for every
session stalls, and `condition_report` frames queue behind the running turn.

The sprint plan's own WP-105 wording - "request queue with instrumented depth" - is the right
answer: one worker thread owning the `InteractionRunner`, a bounded `queue.Queue` of
`(SessionContext, audio, future)`, the handler awaiting the future. This also makes
`WhisperModel` and `PiperVoice` single-threaded by construction, which is the only concurrency
contract either library is known to honour on this hardware. Queue depth is then a single
integer to log.

Decide this before the first line of `api/ws/stream.py` is written; retrofitting a worker into
a handler that already calls the graph inline is a rewrite of the handler.

### S2. `build_wp103_components` returns a positional 5-tuple

`composition/bootstrap.py:65`: `return graph, store, audio_input, audio_output, tts`. Every
new component (runner, queue, resampler, session registry) changes the arity and breaks every
caller and every test that unpacks it. Replace with a frozen `HostComponents` dataclass. The
FastAPI app then needs a `lifespan` that builds it once and stores it on `app.state`; nothing
of the sort exists (`api/app.py` is seven lines).

### S3. Storage pragmas for concurrent writers

`storage/database.py:22-24` opens a fresh connection per call with `foreign_keys = ON` and
nothing else. Today there is one writer. WP-105 adds a worker thread writing traces; WP-304's
console stub adds HTTP handlers writing `tasks` and `self_reports` from FastAPI's thread pool.
With the default rollback journal and the default 5 s busy timeout, the first overlapping
write during a demo will surface as `sqlite3.OperationalError: database is locked`.

Two lines in `connect()`:

```python
conn.execute("PRAGMA journal_mode = WAL")
conn.execute("PRAGMA busy_timeout = 5000")
```

WAL is set once per file and persists; executing it per connection is harmless. The
one-connection-per-call design is otherwise the right one for this and needs no change.

### S4. No schema versioning

`storage/schema.py` is `CREATE TABLE IF NOT EXISTS` throughout. That is idempotent for a
fresh file and a silent no-op for an existing one: a column added for WP-105 will not appear
in the `syncro.db` that was seeded for the demo, and the first insert that names it fails.
Either add a one-row `schema_version` table and refuse to start on a mismatch, or write the
rule "delete `syncro.db` after any schema change" into the README and the demo runbook. The
first is about twenty lines; the second is free but relies on memory during W5.

### S5. No downlink audio path

SPEC 8.4: Piper's native rate is resampled to 16 kHz **host-side**, then chunked to 100 ms
(3,200 bytes of int16 mono) and paced to playback rate. On trunk: `PiperTTSAdapter.synthesize`
returns float32 at the voice's native rate (22,050 Hz for the configured voice), nothing
resamples, nothing converts to int16, nothing chunks, nothing paces. `TTS.synthesize` is
whole-utterance.

For the demonstration, resampling and chunking a completed buffer satisfies the wire contract
and is what the runner (F3) should do. True streaming - sending frames as Piper produces them
- is an additive `synthesize_stream(text) -> Iterator[tuple[np.ndarray, int]]` on the
`Protocol`, not a change to the existing method. No resampling dependency is installed; a
linear-interpolation resampler in `numpy` is adequate for speech at this ratio and avoids
adding `scipy` under freeze.

### S6. Authentication and clock-sync seams do not exist yet

The plan defers per-device tokens and TLS to BL-03 and runs plain WebSocket for the demo.
That is a reasonable scope decision. The architectural requirement it leaves is that the
handler be written so that BL-03 is a swap, not a restructure:

- an injected `authenticate(headers) -> DeviceIdentity | None` callable, with the demo
  implementation returning a fixed identity;
- a `Connection` class (not closure variables) holding `device_id`, `user_id`, the negotiated
  `clock_offset_ms | None`, and the session registry for that connection.

`latency_basis` is decided by whether `clock_offset_ms` is `None`, which is why it must be
per-connection state and not per-message.

### S7. `DialogueState` is a flat bag with no ownership

Twenty-one keys, all optional, all writable by any node. `final_response` is written by
`node1_intent` (clarify path) and overwritten by `node4_policy`; `proposed_action` by
`node1_intent` and `node3_llm`. It works because the graph is linear after the join. It will
stop being obvious the moment WP-105 adds transport-side keys. The cost is low today; the
recommendation is only to keep the reducer keys from F5 as the sole multi-writer keys and to
document which node owns each of the rest in `pipeline/state.py`.

### S8. Docs and code have already diverged

- `techdocs/ARCH.md` is WP-102-scoped by its own locked decision LD-1 and describes
  `HostPipeline` as the runtime; the WP-103 graph is not in it.
- `techdocs/OBS-LOG.md` specifies structured events (FR-O1..O10) that nothing emits.
- `CLAUDE.md` (local, uncommitted) describes PR #3 as open and WP-104 as not started.
- `README.md` is the most accurate of the four.

Four overlapping documents at 3,500 lines is more than a three-person team can keep true
during a freeze. Recommend: ARCH.md gets a short "WP-103 runtime" section and a note that
sections 4-8 describe the WP-102 path; OBS-LOG.md is either implemented (the F3 runner's
`stage_timings_s` is 80% of FR-O4/O10) or moved to the backlog.

### S9. Known deferred items, restated

Carried from the WP-103 review; none has changed.

- `ContextResult.ids` (`storage/context.py`) mixes `tasks.task_id` and `routine_log.log_id`
  into one untyped list that becomes `decision_trace.retrieved_context_ids`. Corrupts the
  trace's meaning, not behaviour. Needs an id-shape decision before the Policy-Consistency
  Audit reads that column.
- `apply_policy` returns R1 for every governed interaction on trunk because affect is pinned
  to `"Low"`. R2-R5 execute only under test fakes. WP-104 changes this.
- No mutation executor exists. `add_task`, `snooze_reminder`, `dismiss_reminder` produce text
  only; the guard in `pipeline/nodes/llm.py` is the sole defence against the robot claiming
  otherwise. Unchanged and out of scope here, but it bounds what the demo can honestly show.

## 8. Integration risk: `feature/wp-104` against trunk

`origin/feature/wp-104` @ `5132c9b`, diffed against `origin/main`:

- 117 files, +14,523 / -203. The bulk is `ml/`, `datasets/`, `evidences/`, `models/`
  metadata and the `tests/unit/ml_affect/` suite.
- Product-code delta is modest: 37 modules, +415 / -52. But it touches **every** module in
  `adapters/`, `audio/`, `pipeline/`, `storage/`, `config/`, `scripts/`, most by rewriting or
  adding one-line docstrings. A WP-105 branch cut from `main` today will conflict with it
  trivially and everywhere.
- Adds `opensmile==2.6.0`, `scikit-learn==1.9.0`, `joblib==1.6.0`, `soundfile==0.13.1`.
- Adds `affect_detector_backend` setting with a runtime fallback to the development detector
  when the model artifact is missing (logs a warning). Reasonable.
- Adds `"affect_detector_failure"` to `DegradationReason` in `pipeline/contracts.py`. **That
  value is not in SPEC 13's enumeration.** It is a sensible reason to record; it needs a SPEC
  amendment, not a silent widening of the Literal.
- Writes `degradation_reason` from the `affect` node as a plain state key (see F5).

Recommendation: decide the fate of wp-104 before cutting WP-105 - merge it (and reconcile the
enum with SPEC) or explicitly park it - and cut WP-105 from whichever `main` results. Do not
develop the two in parallel from today's trunk.

## 9. Trace-field ownership

The three fields SPEC 8.3 leaves as "populated or explicitly null" have, on trunk and on the
wp-104 branch combined, the following writers. Every future writer must be added to this table
before it is added to the code.

| Field | Trunk writer | wp-104 writer | WP-105 writer (planned) | Proposed single owner |
|---|---|---|---|---|
| `latency_ms` | output node (wrong interval, F1) | same | must be TTS onset | `InteractionRunner` |
| `latency_basis` | output node (constant) | same | depends on clock sync | `InteractionRunner` from `SessionContext.clock_offset_ms` |
| `degradation_reason` | `None` | `affect` node | transport (`session_timeout`, `condition_report`), queue (`queue_overflow`) | `InteractionRunner` from the F5 `degradations` reducer list plus transport events; first-wins ordering per SPEC 13 ("checked in order") |
| `network_event` | `None` | `None` | connection lifecycle | `Connection` writes standalone rows; never on an interaction row |
| `reminder_outcome` | policy node (`pending`/`n/a`) | same | none | update-in-place path still unimplemented (SPEC 11.2a); out of sprint scope |

## 10. Recommended target shape

Everything below is additive to trunk. No existing test changes meaning; the WP-102 path and
its architecture test are untouched.

```
composition/bootstrap.py
    build_host_components(settings) -> HostComponents          (S2)
        .graph .store .tts .runner .queue .session_registry .authenticate

pipeline/interaction.py                                        (F1, F3, F4)
    SessionContext, InteractionResult, InteractionError, InteractionRunner

pipeline/state.py                                              (F5, S7)
    stage_timings_s: Annotated[dict, merge]   degradations: Annotated[list, add]

pipeline/graph.py
    timed(name, node) wrapper; output node returns the assembled record in state
    instead of writing it                                      (F1 option a)

pipeline/contracts.py                                          (F2)
    DegradedTraceRecord (or nullable fields + validator); SPEC amendment recorded

storage/decision_trace.py                                      (F1, F2)
    save(record) accepts both record types; set_degradation(trace_id, reason)

storage/database.py                                            (S3)
    WAL + busy_timeout

storage/schema.py                                              (S4)
    schema_version table, or the documented delete rule

audio/resample.py                                              (S5)
    to_pcm16_16k(audio, rate) -> np.ndarray[int16]; chunk_100ms()

api/app.py                                                     (S1, S2)
    lifespan builds HostComponents; app.state.components

api/ws/stream.py                                               (S1, S6)
    Connection class; authenticate hook; clock sync; session registry;
    handler enqueues to the worker and awaits a future; paced downlink

scripts/run_wp103.py
    thin caller of InteractionRunner with clock_offset=None
```

Estimated effort for the pipeline/storage half (everything above `api/`): one focused day, all
of it testable with fakes and `tmp_path`. The `api/` half is WP-105 proper.

## 11. Sequencing

1. **Decisions (half a day, no code):** F1 option, F2 option, F6 model split, S4 versioning
   rule, wp-104 merge-or-park. Record the two SPEC amendments (F2 degraded rows, F4
   `pipeline_failure` error code, and the wp-104 `affect_detector_failure` reason if it
   merges).
2. **Land or park wp-104.** Reconcile the enum.
3. **Foundations branch (one day):** F3 runner, F4 boundary, F5 reducers + timer, F1 trace
   finalisation, S2 dataclass, S3 pragmas, S5 resampler. Every item has a unit test that fails
   on trunk. Suite must stay green; this is a refactor with a measurable before/after (the
   `run_wp103.py` output is the acceptance check for "nothing changed").
4. **Measure F6** with the runner's timings before touching the LLM calls. Then apply the
   cheap mitigations and measure again. That pair of numbers is WP-108's first row.
5. **WP-105** on top of the foundations branch, as its own change.
6. WP-107 consumes `wake_word_detected_at` through `SessionContext`; nothing else changes.

Doing step 3 inside WP-105 instead of before it is possible, but it puts the refactor and the
protocol work in one review, under RR-1/RR-2, in the same week as G4. Separating them is the
lower-risk order.

## 12. Housekeeping

Observed during the review; none is architectural.

- Local `main` is 18 commits behind `origin/main`. `origin/feature/wp-103` and
  `origin/fix/wp-103-review-findings` were pruned on fetch; the local copies are orphans.
- Two git worktrees from earlier sessions are still registered in temporary directories, one
  of them holding `fix/wp-103-review-findings` checked out. `git worktree prune` will not
  clear them while the directories exist.
- `ollama==0.6.2` is pinned in `requirements.txt` and unused; both Ollama adapters use
  `requests` directly, with duplicated request/parse code.
- `PiperTTSAdapter` round-trips through an in-memory WAV to obtain PCM; Piper 1.7's
  `synthesize()` yields chunks directly and would remove both the WAV encode and the decode.
- `SQLiteStore.ensure_user` imports `datetime` inside the method body.

## 13. Appendix A - verification log

All commands run on 12 September 2026 from a detached worktree at `origin/main` @ `793ec91`,
Python 3.12.2, `langgraph==1.2.11`, `pydantic==2.12.5` (installed; `requirements.txt` pins
2.13.5 - the suite passes on both).

**1. Baseline suite.**

```
$ python -m pytest -q
........................................................................ [ 38%]
........................................................................ [ 77%]
..........................................                               [100%]
186 passed, 1 warning in 1.25s
```

The warning is Starlette's `httpx` deprecation in `TestClient`; unrelated.

**2. Logging on trunk.**

```
$ grep -rn "import logging\|getLogger" --include=*.py .
(no output)
```

**3. LangGraph parallel-write probe (F5).** Two nodes fanned out from `START`, each returning
`{"stage_timings": {...}}`, joined into a third node.

```
plain key    -> RAISES InvalidUpdateError : At key 'stage_timings': Can receive only one
                value per step. Use an Annotated key to handle multiple values.
reducer key  -> {'affect': 0.2, 'stt': 0.1}
```

**4. Branch inventory.**

```
origin/main                            793ec91  Merge pull request #3 (WP-103)
origin/feature/wp-104                  5132c9b  fix: update document measured mlp comparison
origin/feature/observability-logging   e695c06  chore: add initial spec for observability
local main                             1ffcccb  (18 behind origin/main)
```

**5. wp-104 product-code footprint.**

```
$ git diff --stat origin/main...origin/feature/wp-104 -- pipeline storage composition adapters audio api config scripts requirements.txt
37 files changed, 415 insertions(+), 52 deletions(-)
```

**6. Not verified here.** No live run was possible (no microphone, no Ollama server, no Piper
voice in the review environment). Latency figures are quoted from the existing profile report
and are not re-measured. The two-call LLM chain (F6) has no measurement anywhere in the
repository.

## 14. Appendix B - files read

Read in full on `793ec91`:

```
adapters/affect.py                 adapters/contracts.py
adapters/llm/intent_classifier.py  adapters/llm/ollama_adapter.py
adapters/stt/whisper_adapter.py    adapters/tts/piper_adapter.py
api/app.py  api/http/health.py  api/ws/stream.py (empty)
audio/capture.py  audio/contracts.py  audio/playback.py  audio/wake_word.py
composition/bootstrap.py
config/endpoints.py  config/settings.py
pipeline/contracts.py  pipeline/graph.py  pipeline/host_pipeline.py  pipeline/state.py
pipeline/nodes/affect.py  context.py  intent.py  llm.py (non-AI-block region)  output.py
pipeline/nodes/policy.py  stt.py
storage/context.py  database.py  decision_trace.py  schema.py  sqlite_store.py
scripts/run_wp103.py
tests/test_wp102_architecture.py
requirements.txt  pytest.ini  .env.example
techdocs/SPEC.md sections 7, 8, 12, 13   techdocs/profile-full-report-rtx-4060.md (claims table)
Sprint plan: sections 3, 4
```

Read as diffs against `origin/main`:

```
feature/wp-104: composition/bootstrap.py, pipeline/graph.py, pipeline/nodes/affect.py,
                pipeline/nodes/output.py, pipeline/state.py, pipeline/contracts.py,
                storage/*, adapters/contracts.py, config/settings.py, requirements.txt,
                adapters/affect/classifier_detector.py (full)
feature/observability-logging: techdocs/OBS-LOG.md (headings)
```
