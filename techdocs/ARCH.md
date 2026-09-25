# SYNCRO Host — System Architecture

This document is the technical design for how SYNCRO Host's pieces connect
and why. Where `techdocs/SPEC.md` states WHAT the system must do and
`techdocs/work-packages/WP-*.md` state what each work package built and its
current status, this document states HOW the pieces fit together
system-wide, independent of which work package built which piece. It is
addressed to an engineer extending or debugging the host and is written to
be usable with no prior knowledge of this repository beyond the modules it
transcribes.

Every mandatory statement in this document ("must", "never", "always")
resolves to a numbered invariant (`INV-n`, section 10) or a labelled locked
decision (`LD-n`, section 2); prose elsewhere cites the identifier that
carries the reason rather than asserting new mandatory language on its own.

## Table of Contents

1. Purpose, Relationship to Other Documents, Targeted System
2. Locked Decisions (LD-1..LD-n)
3. Execution Model Primer
4. Dependency Interface Reference
   - 4.1 adapters/contracts.py
   - 4.2 adapters/stt/whisper_adapter.py
   - 4.3 adapters/llm/ollama_adapter.py
   - 4.4 adapters/tts/piper_adapter.py
   - 4.5 adapters/affect/
   - 4.6 pipeline/graph.py
   - 4.7 pipeline/interaction.py
   - 4.8 pipeline/worker.py
   - 4.9 composition/bootstrap.py
   - 4.10 Exception Surface Summary
   - 4.11 Data Handoff Rules
5. State Model
6. Resource Lifecycle
7. Control Flow
8. Error Handling Matrix
9. Performance Budget
10. Invariants (INV-1..INV-n)
11. Requirement Traceability
12. Notes on Warranted Code Changes

## 1. Purpose, Relationship to Other Documents, Targeted System

This document designs the system-wide structure that every work package
builds inside. Where a work-package doc states what was built, when, and
its acceptance status, this document states the shape that all of them
share: the composition root, the adapter boundary, the graph, the
synchronous-vs-queued execution split, and the failure-classification
contract. A statement here should still be true even if every work package
were renamed tomorrow; anything that is only true "as of WP-10X" belongs in
that work package's own document instead.

Targeted system: the FastAPI + LangGraph host process described in
`techdocs/SPEC.md`, running against Ollama (LLM), faster-whisper (STT),
Piper (TTS), and a locally persisted SQLite database. See `SETUP.md` for
the concrete versions of these external dependencies.

## 2. Locked Decisions

The following are decided, not open questions an implementer may revisit:

- **LD-1.** There is exactly one composition root, `composition/bootstrap.py`.
  No other module constructs a concrete adapter and wires it into the graph.
- **LD-2.** External technologies are accessed only through the Protocol
  contracts in `adapters/contracts.py` (STT, LLM, TTS, IntentClassifier).
  Pipeline nodes and policy code depend on these contracts, never on a
  concrete vendor SDK.
- **LD-3.** `pipeline/interaction.py`'s `InteractionRunner` owns the
  graph → TTS → resample → trace sequence as one unit. No other code path
  calls `graph.invoke()` and `tts.synthesize()` separately outside of tests.
- **LD-4.** The WebSocket transport (`api/ws/stream.py`) never runs an
  interaction synchronously on the event-loop thread. It submits to
  `InteractionWorker`, which processes one interaction at a time on a single
  dedicated background thread.
- **LD-5.** `InteractionWorker`'s queue is bounded and rejects new work
  (`WorkerQueueFullError`) rather than blocking the caller when full (S1).
  An unbounded queue is not an acceptable substitute.
- **LD-6.** No mutation executor is connected to the graph anywhere in the
  system. The reasoning node may only draft a reply describing a mutation;
  it cannot cause one to occur.
- **LD-7.** The intent classifier and the reasoning LLM currently share one
  Ollama model (`LLM_MODEL`); they have independent timeouts (D5, section 9)
  but are not yet split into separate models. This is deferred (D4), not
  unimplemented by oversight.
- **LD-8.** WP-105's `default_dev_authenticate` accepts every WebSocket
  connection; real device-token authentication is intentionally deferred
  (BL-03) on the grounds that a controlled bench network does not require it
  for the prototype defense. This is a stated scope boundary, not scaffold
  debt to close reflexively.

## 3. Execution Model Primer

The host process runs interactions through one of two regimes, and every
entry point uses exactly one of them:

- **Synchronous, script-driven.** `scripts/run_wp102.py` and
  `scripts/run_wp103.py` call `composition/bootstrap.py` directly, obtain a
  `HostComponents.runner`, and call `runner.run(...)` inline. There is no
  event loop to protect, so nothing is gained by queuing; the call blocks
  until the interaction completes.
- **Queued, API-driven.** `api/ws/stream.py` never calls `runner.run(...)`
  directly. It calls `HostComponents.worker.submit(...)`
  (`InteractionWorker`), which enqueues the work and returns a `Future`
  immediately. A single dedicated background thread drains the queue and
  calls `runner.run(...)` on the caller's behalf (LD-4). This exists because
  an interaction can take multiple seconds (STT + LLM + TTS), and the
  WebSocket event loop must keep servicing other connections — including a
  client's clock-sync handshake or a graceful disconnect — while that
  happens.

Both regimes converge on the same `InteractionRunner.run(...)` call (LD-3);
they differ only in whether that call happens inline or is handed to the
worker thread. Adding a third entry point means choosing one of these two
regimes, not inventing a third execution style.

## 4. Dependency Interface Reference

Every subsection names its repository-relative source path first, then
transcribes constants and signatures from the current source with
parameter names, order, defaults and return types unchanged.

### 4.1 adapters/contracts.py

```python
class STT(Protocol):
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str: ...

class LLM(Protocol):
    def generate(self, prompt: str) -> str: ...

class TTS(Protocol):
    def synthesize(self, text: str) -> tuple[np.ndarray, int]: ...

class IntentClassifier(Protocol):
    def classify(self, transcript: str) -> tuple[str, float, dict[str, object]]: ...
```

These four Protocols are the entire surface pipeline nodes are allowed to
depend on (LD-2). A concrete adapter satisfies one of these structurally
(no explicit inheritance required); the composition root is the only place
that imports a concrete adapter class.

### 4.2 adapters/stt/whisper_adapter.py

```python
class STTAdapterError(RuntimeError): ...

class WhisperSTTAdapter:
    def __init__(self, settings: Settings | None = None) -> None: ...
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str: ...
```

`__init__` resolves `settings` via `get_settings()` if not supplied, lazily
imports `faster_whisper.WhisperModel` (raising `STTAdapterError` if the
package is missing), and constructs the model with `settings.stt_model_size`,
`settings.stt_device`, and `settings.stt_compute_type`; a construction
failure is wrapped in `STTAdapterError` rather than propagated raw.
`transcribe` requires `float32` PCM at exactly `settings.audio_sample_rate_hz`
— a dtype or rate mismatch raises `STTAdapterError` before any model call is
made, not a silent resample or truncation.

### 4.3 adapters/llm/ollama_adapter.py

```python
class LLMAdapterError(RuntimeError): ...

class OllamaLLMAdapter:
    def __init__(self, settings: Settings | None = None) -> None: ...
    def generate(self, prompt: str) -> str: ...
```

`generate` posts to `{ollama_url}/api/generate` with `stream=False`,
`keep_alive` from settings, and `options.num_ctx` from settings, using
`settings.reasoning_timeout_s` as the request timeout — this is the
"reasoning" half of the two sequential per-turn Ollama calls (LD-7, section
9) and does not share a timeout with the intent classifier. A request
failure, an unparseable response, or an empty response string all raise
`LLMAdapterError`; none of the three is silently converted into a fallback
reply.

### 4.4 adapters/tts/piper_adapter.py

```python
class TTSAdapterError(RuntimeError): ...

class PiperTTSAdapter:
    def __init__(self, settings: Settings | None = None) -> None: ...
    def synthesize(self, text: str) -> tuple[np.ndarray, int]: ...
```

`__init__` lazily imports `piper.PiperVoice` and loads
`settings.piper_model_path` directly as the model path argument; both the
import and the load are wrapped in `TTSAdapterError`. `synthesize` refuses
empty/whitespace-only text (raises `TTSAdapterError`) rather than
synthesizing silence, and returns `float32` PCM in `[-1.0, 1.0]` at the
sample rate Piper's own WAV output reports — the caller resamples if a
different rate is required (section 4.11).

### 4.5 adapters/affect/

```python
class DevelopmentAffectDetector:
    def detect(self, audio: Any, sample_rate: int) -> str: ...  # always "Low"

class ClassifierAffectDetector:
    def __init__(self, model_path: str | Path) -> None: ...
    def detect(self, audio: Any, sample_rate: int) -> str: ...  # -> "Low" | "Moderate" | "High"
```

Both raise `ValueError` for `audio is None` or `sample_rate <= 0` before
doing any work. `DevelopmentAffectDetector.detect` is otherwise
unconditional and deterministic — it is a stable, permanent fallback, not
scaffolding to delete once a classifier exists. `ClassifierAffectDetector`
extracts features via `ml.affect.features.extract_features` (a runtime
dependency on the `opensmile` package and `OPENSMILE_EXECUTABLE` binary,
not just a training-time one — see `techdocs/work-packages/WP-104.md`),
predicts with the loaded artifact, and raises `RuntimeError` if the
prediction falls outside `{"Low", "Moderate", "High"}`. The composition
root, not this class, is responsible for falling back to the development
detector when construction fails (section 6).

### 4.6 pipeline/graph.py

```python
def build_dialogue_graph(
    *,
    stt, intent_classifier, llm, store, affect_detector,
    confidence_threshold: float,
    context_top_k: int,
    deadline_proximity_hours: int,
    grace_window_minutes: int,
    default_lead_time: float,
):
    ...  # -> compiled LangGraph graph

def invoke_dialogue(
    graph, *, session_id: str, user_id: str, audio: Any, sample_rate: int,
) -> DialogueGraphResult:
    ...
```

`build_dialogue_graph` wires seven nodes (`node1_stt`, `node1_intent`,
`node2_context`, `node3_llm`, `affect`, `node4_policy`, `output`) with two
parallel branches off `START` — the STT→intent→context→LLM chain, and the
independent `affect` branch on the same raw audio — that both feed
`node4_policy` as a synchronization point before `output`. `node1_stt` and
`affect` are wrapped in `timed(...)` so their durations land in the
reducer-backed `stage_timings_s` key (F5) rather than a plain dict key that
a parallel branch could overwrite. Every dependency (`stt`,
`intent_classifier`, `llm`, `store`, `affect_detector`) is injected as a
parameter — this function never imports a concrete adapter itself (LD-2).

### 4.7 pipeline/interaction.py

```python
@dataclass(frozen=True, slots=True)
class SessionContext:
    session_id: str
    user_id: str
    started_monotonic: float
    wake_word_detected_at: int | None = None  # edge-clock epoch ms, SPEC 7.3
    clock_offset_ms: float | None = None

@dataclass(frozen=True, slots=True)
class InteractionResult:
    session_id: str
    trace_id: str
    response_payload: dict[str, Any]
    tts_audio: np.ndarray          # 16 kHz int16 mono, after resampling (S5)
    tts_sample_rate: int
    stage_timings_s: dict[str, float]
    latency_ms: float
    latency_basis: str

@dataclass(frozen=True, slots=True)
class FailureDisposition:
    stage: str
    wire_code: str
    degradation_reason: str | None
    trace_required: bool

class InteractionError(RuntimeError):
    def __init__(
        self, stage: str, cause: BaseException, *,
        wire_code: str, degradation_reason: str | None, trace_required: bool,
    ) -> None: ...

class InteractionRunner:
    def __init__(
        self, *, graph: Any, store: Any, tts: Any,
        resampler: Callable[[np.ndarray, int], np.ndarray],
        clock: Callable[[], float] = monotonic,
        clock_ms: Callable[[], float] | None = None,
    ) -> None: ...
    def run(self, *, session: SessionContext, audio: np.ndarray, sample_rate: int) -> InteractionResult: ...
    def persist_session_timeout_trace(self, *, session: SessionContext) -> None: ...
```

`wake_word_detected_at` and `clock_offset_ms` on `SessionContext` are
forward-looking: no caller in this codebase supplies non-`None` values for
either today (WP-107's wake-word integration and WP-105's clock-sync
handshake are both still ahead), so `InteractionRunner.run` always resolves
`latency_basis` to `"host_observed_only"` in practice; the
`"wake_word_to_tts"` branch exists and is unit-tested, but translating the
edge's clock into this runner's `clock()` domain is WP-105/WP-107's
responsibility, not this document's.

`graph` must expose the same `.invoke(dict) -> dict` shape used by
`pipeline.graph.invoke_dialogue` (a fake satisfying this shape is
sufficient for tests). `resampler` matches `audio.resample.to_pcm16_16k`'s
signature. `clock` is injectable so tests can control elapsed-time readings
deterministically without real sleeps.

The central failure-classification table (F4) lives in this module:

```python
_FAILURE_MAP: tuple[tuple[type[Exception], str, str, str | None, bool], ...] = (
    (STTAdapterError, "stt", "malformed_audio", "pipeline_failure", True),
    (IntentClassifierError, "intent", "pipeline_failure", "pipeline_failure", True),
    (LLMAdapterError, "llm", "pipeline_failure", "pipeline_failure", True),
    (TTSAdapterError, "tts", "pipeline_failure", "pipeline_failure", True),
    (ValueError, "pipeline", "pipeline_failure", "pipeline_failure", True),
    (RuntimeError, "pipeline", "pipeline_failure", "pipeline_failure", True),
)
```

Transport code (`api/ws/stream.py`) consumes the stable `wire_code` this
table produces; it never imports an adapter-specific exception class
directly (section 8 restates this as an invariant).

### 4.8 pipeline/worker.py

```python
class WorkerQueueFullError(RuntimeError): ...
class WorkerStoppedError(RuntimeError): ...

class InteractionWorker:
    def __init__(self, *, runner: InteractionRunner, maxsize: int) -> None: ...
    def start(self) -> None: ...
    def submit(self, *, session: SessionContext, audio: np.ndarray, sample_rate: int) -> "Future[InteractionResult]": ...
    def stop(self, *, timeout: float | None = None) -> None: ...
```

`start()` is idempotent-guarded: a second call raises rather than silently
spawning a second thread, since two threads would violate the
single-threaded-library contract this class exists to guarantee. `submit`
never blocks: a full queue raises `WorkerQueueFullError` immediately rather
than waiting for room (LD-5) — this is the entire reason S1 asks for a
bounded queue over an unbounded one, since an unbounded queue would let the
caller block indefinitely instead of failing fast. `stop()` appends a
sentinel to the same FIFO queue as real work, so every item queued before
`stop()` is called still runs before the thread exits; submissions made
after `stop()` raise `WorkerStoppedError` immediately.

### 4.9 composition/bootstrap.py

```python
@dataclass(frozen=True, slots=True)
class HostComponents:
    graph: Any
    store: SQLiteStore
    audio_input: Any
    audio_output: Any
    tts: Any
    affect_detector: ClassifierAffectDetector | DevelopmentAffectDetector
    runner: InteractionRunner
    worker: InteractionWorker

def build_host_components(
    settings: Settings | None = None, *, affect_detector=None,
) -> HostComponents: ...
```

`HostComponents` replaced a positional tuple return (S2) specifically
because every component the sprint added — the runner, the worker, session
tracking, authentication — used to change that tuple's arity and break
every caller and every test that unpacked it by position. Adding a field
here is additive and non-breaking for callers that access fields by name;
this is the reason new cross-cutting state should be added as a
`HostComponents` field rather than threaded through as an extra parameter
elsewhere.

`build_host_components` is the only place in the repository allowed to
construct a concrete `WhisperSTTAdapter`, `OllamaLLMAdapter`,
`PiperTTSAdapter`, `ClassifierAffectDetector`, or `DevelopmentAffectDetector`
(LD-1). Its affect-backend selection is the one place the
classifier-to-development fallback is decided (section 6), not inside
`ClassifierAffectDetector` itself.

### 4.10 Exception Surface Summary

| Entry point                          | Exception              | When                                                        |
| -------------------------------------- | ------------------------ | -------------------------------------------------------------- |
| `WhisperSTTAdapter.__init__`         | `STTAdapterError`      | `faster-whisper` missing, or model construction fails.       |
| `WhisperSTTAdapter.transcribe`       | `STTAdapterError`      | Wrong dtype, wrong sample rate, or transcription failure.     |
| `OllamaLLMAdapter.generate`          | `LLMAdapterError`      | Request failure, unparseable response, or empty response.     |
| `PiperTTSAdapter.__init__`           | `TTSAdapterError`      | `piper-tts` missing, or voice model fails to load.            |
| `PiperTTSAdapter.synthesize`         | `TTSAdapterError`      | Empty/whitespace text, or synthesis failure.                  |
| `ClassifierAffectDetector.detect`    | `ValueError`            | `audio is None` or `sample_rate <= 0`.                        |
| `ClassifierAffectDetector.detect`    | `RuntimeError`          | Feature extraction fails, inference fails, or an invalid label is produced. |
| `InteractionRunner.run`              | `InteractionError`      | Any adapter/pipeline failure crossing the interaction boundary (F4 mapping, section 4.7). |
| `InteractionWorker.submit`           | `WorkerQueueFullError` | The bounded queue is already full.                             |
| `InteractionWorker.submit`           | `WorkerStoppedError`   | Called after `stop()`.                                         |
| `InteractionWorker.start`            | `RuntimeError`          | Called more than once.                                         |

`InteractionRunner.run` is the single boundary where every adapter-specific
exception is normalized into `InteractionError` with a stable `wire_code`
(section 4.7); transport code downstream never needs to know which adapter
failed, only the wire code and whether a trace is required.

### 4.11 Data Handoff Rules

Audio crossing the STT boundary must already be `float32` PCM at
`settings.audio_sample_rate_hz`; `WhisperSTTAdapter.transcribe` does not
resample or convert dtype itself (section 4.2) — that conversion is the
caller's responsibility, upstream of the adapter. TTS output crossing back
out of `PiperTTSAdapter.synthesize` is `float32` PCM at whatever sample rate
Piper's own WAV output reports, not a fixed constant; `InteractionRunner`
resamples this to 16 kHz int16 mono (S5) before it becomes
`InteractionResult.tts_audio` — the resample step is `InteractionRunner`'s
job specifically so that no caller of the runner needs to know Piper's
native output rate. The value returned by `pipeline.graph.invoke_dialogue`
is consumed only by `InteractionRunner.run`, which is the only code path
permitted to turn a raw graph result into a `InteractionResult` (LD-3);
nothing downstream of the runner reads the graph's raw dict.

## 5. State Model

| State                          | Owner                                   | Lifetime                                    | Mutator                                             |
| --------------------------------- | ------------------------------------------ | ---------------------------------------------- | ------------------------------------------------------ |
| `HostComponents`                | `composition/bootstrap.py`               | Process lifetime, built once at startup        | Only `build_host_components`; frozen thereafter        |
| Compiled dialogue graph          | `HostComponents.graph`                   | Process lifetime                                | Immutable once compiled by `build_dialogue_graph`       |
| `SessionContext`                | Caller (script or WebSocket route)       | One interaction                                 | Constructed once, frozen, passed to `runner.run`        |
| `stage_timings_s` (graph state) | LangGraph reducer, per invocation         | One graph invocation                            | `timed(...)`-wrapped nodes only, via the reducer (F5)   |
| `InteractionWorker`'s queue     | `InteractionWorker`                       | Process lifetime, bounded by `maxsize`          | `submit()` enqueues; `_run()` dequeues on the worker thread |
| Decision trace row               | `storage/decision_trace.py` via `store`  | Persisted (SQLite)                              | `InteractionRunner.run` and `.persist_session_timeout_trace` |
| WebSocket session (`SessionRegistry`) | `api/ws/session_registry.py`         | One WebSocket connection, host-wide tracked      | `api/ws/connection.py`'s `Connection` seam              |

The composition root's output (`HostComponents`) is the single object that
threads every other piece of state together; a new cross-cutting concern
should be added as a field on it (section 4.9), not as a new global or a
parameter threaded through every call site.

## 6. Resource Lifecycle

**Composition happens once.** `build_host_components` runs once at process
startup (per script invocation, or once for the FastAPI app's lifetime) and
constructs every adapter, the graph, the runner, and the worker. Nothing in
steady-state request handling re-runs composition.

**Affect-backend fallback is a composition-time decision.** When
`AFFECT_DETECTOR_BACKEND=classifier` and the artifact fails to load
(`FileNotFoundError` or `RuntimeError`), `build_host_components` catches
that failure, logs a warning naming the configured path, and falls back to
`DevelopmentAffectDetector` — this happens once, at startup, not per-turn.
A per-turn fallback to `Low` (documented in `ClassifierAffectDetector`,
section 4.5, and in `techdocs/work-packages/WP-104.md`) is a distinct,
narrower behavior: it covers a classifier that loaded successfully at
startup but fails on a specific turn's inference, not a classifier that
never loaded at all.

**The worker thread is started once and stopped once.** `InteractionWorker.start()`
being idempotent-guarded (section 4.8) is deliberate: nothing in the
request-handling path should ever need to start a second worker thread, and
a caller that tries is very likely wiring a second, competing composition
root rather than reusing the one from startup.

**LLM warm-up happens before the graph is usable.** `build_host_components`
calls `_warm_up_llm(settings)` before constructing the graph, using a
separate `llm_warmup_timeout_s` (deliberately larger than
`reasoning_timeout_s` — section 9) because Ollama's cold-start model load
can cost multiple seconds to tens of seconds, a cost that per-turn inference
timeouts are not meant to absorb.

## 7. Control Flow

```text
scripts / API
      ↓
composition/bootstrap.py   (build once, LD-1)
      ↓
pipeline graph + injected contracts   (technology-neutral, LD-2)
      ↓
adapters / audio / storage
      ↓
external systems
(Ollama, Whisper, Piper, SQLite, microphone, speakers)
```

**Synchronous path** (scripts): build components once, then call
`components.runner.run(session=..., audio=..., sample_rate=...)` directly
and block until `InteractionResult` returns.

**Queued path** (`api/ws/stream.py`): build components once at app startup;
per interaction, call `components.worker.submit(session=..., audio=...,
sample_rate=...)`, which returns a `Future[InteractionResult]` immediately;
await that future rather than calling the runner inline (LD-4).

**Inside `InteractionRunner.run`**, in order: invoke the compiled graph
(`pipeline.graph.invoke_dialogue`'s shape); resample the resulting TTS audio
to 16 kHz int16 mono (S5); persist the decision trace; classify any raised
exception through the F4 `_FAILURE_MAP` (section 4.7) into a stable
`InteractionError` before it can reach a caller; return `InteractionResult`.
This is exactly the "second, drifting copy of the sequence" problem LD-3
exists to eliminate — code that called `graph.invoke()` and
`tts.synthesize()` separately, as earlier revisions of the host did, is the
pattern to avoid in any new entry point.

## 8. Error Handling Matrix

| ID | Failure | Detected where | Downstream contract | Trace behavior |
| ---- | --------- | ----------------- | ---------------------- | ----------------- |
| ERR-1 | STT adapter cannot transcribe (bad dtype, wrong rate, or backend failure). | `WhisperSTTAdapter.transcribe` raises `STTAdapterError`. | `InteractionRunner` maps to `wire_code="malformed_audio"`, `stage="stt"` (F4). | `trace_required=True`; degraded trace written. |
| ERR-2 | Intent classification fails. | `IntentClassifierError`. | `wire_code="pipeline_failure"`, `stage="intent"`. | `trace_required=True`. |
| ERR-3 | LLM request fails, or Ollama returns an unusable payload. | `LLMAdapterError`. | `wire_code="pipeline_failure"`, `stage="llm"`. | `trace_required=True`. |
| ERR-4 | TTS synthesis fails. | `TTSAdapterError`. | `wire_code="pipeline_failure"`, `stage="tts"`. | `trace_required=True`. |
| ERR-5 | Affect classifier fails at inference time on a loaded model. | `RuntimeError` from `ClassifierAffectDetector.detect`. | Degrades that turn's affect level to `"Low"` rather than aborting the interaction (per-turn fallback, distinct from ERR-6). | Interaction continues; not itself trace-required. |
| ERR-6 | Affect classifier artifact never loads at startup. | `FileNotFoundError`/`RuntimeError` from `ClassifierAffectDetector.__init__`, caught in `build_host_components`. | Composition falls back to `DevelopmentAffectDetector` for the process lifetime (section 6). | Logged once at startup; no per-turn trace impact. |
| ERR-7 | Worker queue is full. | `InteractionWorker.submit` raises `WorkerQueueFullError`. | Caller (the WebSocket route) must reject the new work rather than block the event loop (LD-4, LD-5). | No trace — the interaction never started. |
| ERR-8 | Submission arrives after `stop()`. | `WorkerStoppedError`. | Caller must treat this as a shutdown-in-progress condition. | No trace. |

Any exception not explicitly named above but matching `ValueError` or
`RuntimeError` still resolves through the F4 map's catch-all rows (section
4.7) to `stage="pipeline"`, `wire_code="pipeline_failure"`,
`trace_required=True` — there is no exception type that reaches
`InteractionRunner.run` and produces an unclassified failure.

## 9. Performance Budget

The D5 timeout invariant, enforced by `config/settings.py`'s
`__post_init__` (not merely documented — a violated invariant raises at
settings load, before the process can serve a single request):

```text
intent_timeout_s + reasoning_timeout_s + non_llm_timeout_margin_s < session_timeout_seconds
```

Default values: `intent_timeout_s=5`, `reasoning_timeout_s=6`,
`non_llm_timeout_margin_s=10`, `session_timeout_seconds=30` — a budget of
21 seconds against a 30-second ceiling. The intent classifier and the
reasoning LLM are two sequential Ollama calls per turn (LD-7); they used to
share one timeout, which meant a slow reasoning call could starve the
budget the intent classifier needed, or vice versa. Splitting them (F6) lets
each call be bounded independently while the sum invariant guarantees the
whole turn fits inside the 30-second session ceiling that the WP-105
inactivity reaper (`_StreamSession.run_reaper`) enforces.

`llm_warmup_timeout_s` (default 120s) is deliberately separate from both
per-turn timeouts (section 6): it bounds Ollama's cold-start model load at
composition time, a multi-second-to-tens-of-seconds cost that per-turn
inference timeouts are not meant to absorb and that the D5 invariant does
not govern.

## 10. Invariants

Every invariant below is presented in exactly three labelled parts — Rule,
Reason, Failure mode if violated.

**INV-1. Composition root exclusivity.**
Rule: only `composition/bootstrap.py` constructs concrete adapter instances
(`WhisperSTTAdapter`, `OllamaLLMAdapter`, `PiperTTSAdapter`,
`ClassifierAffectDetector`, `DevelopmentAffectDetector`) and wires them into
the graph.
Reason: pipeline nodes and policy code depend only on the Protocol contracts
in `adapters/contracts.py` (LD-2) so tests can inject fakes without any real
hardware or external service; a second construction site defeats that
isolation for whatever it constructs.
Failure mode if violated: a test or a new entry point that constructs its
own adapter bypasses the affect-backend fallback logic (section 6), the LLM
warm-up (section 6), and any future cross-cutting concern added to
`build_host_components` — it silently diverges from every other caller's
behavior.

**INV-2. `InteractionRunner` owns the full sequence.**
Rule: no code outside `InteractionRunner.run` calls `graph.invoke()` (or
`invoke_dialogue`) and then separately calls `tts.synthesize()`, resamples,
or writes a decision trace.
Reason: this is precisely the "second, drifting copy of the sequence"
problem `InteractionRunner` was built to eliminate (section 7); a second
copy of the sequence can silently omit the resample step (S5) or the trace
write while still appearing to work in the common case.
Failure mode if violated: an entry point that reassembles the sequence
itself will pass tests that don't exercise the resample or trace-write path,
then produce audio at the wrong sample rate or an interaction with no
decision trace in production, with no test catching it beforehand.

**INV-3. The event loop never blocks on an interaction.**
Rule: `api/ws/stream.py` never calls `InteractionRunner.run` directly; it
always goes through `InteractionWorker.submit`.
Reason: an interaction can take multiple seconds; the WebSocket event loop
must keep servicing other connections' clock-sync handshakes and
disconnects during that time (LD-4).
Failure mode if violated: one slow interaction (a slow Ollama response, a
Whisper cold load) stalls every other concurrent WebSocket session on the
same process, turning one user's slow turn into an outage for everyone
connected.

**INV-4. The worker queue fails fast, never blocks.**
Rule: `InteractionWorker.submit` raises `WorkerQueueFullError` immediately
when the bounded queue is full; it never waits for room (LD-5).
Reason: a caller on the event loop thread must not be stalled by a
saturated worker — an unbounded or blocking queue would reintroduce exactly
the stall INV-3 exists to prevent, just one layer down.
Failure mode if violated: under load, the WebSocket route blocks inside
`submit()` waiting for queue space, which blocks the event loop exactly as
if `InteractionRunner.run` had been called directly — INV-3 is satisfied in
name only.

**INV-5. Every adapter failure is normalized before crossing the interaction
boundary.**
Rule: transport code (`api/ws/stream.py`) reads only `InteractionError`'s
`wire_code`, `degradation_reason`, and `trace_required` fields; it never
imports or checks for an adapter-specific exception type
(`STTAdapterError`, `LLMAdapterError`, `TTSAdapterError`, etc.).
Reason: the F4 mapping in `pipeline/interaction.py` (section 4.7) exists
precisely so transport code has one stable contract regardless of which
adapter or how many adapters exist; adapters are expected to change and be
replaced (INV-1).
Failure mode if violated: transport code that special-cases
`LLMAdapterError` today breaks silently — not with a type error, but with a
missed branch — the day an adapter is replaced with one that raises a
different exception type carrying the same F4 classification.

**INV-6. No mutation executor means no claimed mutation.**
Rule: the reasoning node's drafted reply must never assert that a mutation
(adding a task, dismissing a reminder, rescheduling something) has already
happened, because no mutation executor exists anywhere in the system to
make one happen (LD-6). `_reject_unexecuted_mutation_claim` in
`pipeline/nodes/llm.py` enforces this.
Reason: if a drafted reply claimed a mutation occurred and none did, the
user would hear a spoken confirmation for something that never happened,
and would have no reason to retry.
Failure mode if violated: silently correct-sounding responses that describe
actions the system cannot take, discovered only when a user later finds the
task was never added — a failure mode with no error, no trace anomaly, and
no test failure to point at it.

The guard behind INV-6 is a lexical rule, not a parser, and is deliberately
imperfect in two known ways, documented here rather than fixed because
closing either would break a more common case:

- **Cross-clause negation is not tracked.** A reply that denies and then
  claims in the same sentence passes through unguarded, e.g. "You told me
  not to, but this was added anyway." Catching it would require
  distinguishing a negator that governs the verb from one that does not,
  which the current clause-scope model cannot do without re-breaking "I
  have not, however, dismissed that reminder."
- **Comma-coordinated denials are over-caught.** A denial whose subject is a
  comma-separated list, e.g. "None of the milk, eggs, or bread was added.",
  is replaced by the generic reply "I have not added that yet, but I can
  add it to your list if you would like." This is over-caution rather than
  a false statement, but loses which items were meant. It does not affect
  object-position lists, parentheticals, or comma-free lists.

Two smaller gaps are known and accepted for the same reason: a completed
verb followed by a bare noun with no colon ("Added task buy milk."), and
mutation verbs outside the per-intent word lists ("Bumped the call to
6pm."). When changing this guard, test both directions — claims that must
be caught and ordinary wording that must pass through untouched are held
together in `tests/unit/pipeline/test_llm.py`, whose two parametrised tests
pick up new rows automatically. Widening the rule to catch one more
phrasing has twice introduced a false positive on a commoner one; treat a
reported example as a sample of a class rather than as the thing to patch.

**INV-7. The D5 timeout sum invariant is enforced at settings load, not
just documented.**
Rule: `intent_timeout_s + reasoning_timeout_s + non_llm_timeout_margin_s`
must be strictly less than `session_timeout_seconds`; `config/settings.py`
raises at load time if this does not hold.
Reason: a per-turn budget that exceeds the session timeout would allow
the WP-105 inactivity reaper to reclaim a session mid-turn on every
interaction rather than only as a rare edge case (section 9).
Failure mode if violated: were this only documented and not enforced, a
future settings change (raising `reasoning_timeout_s` without checking the
sum) would ship silently and only surface as sessions timing out under
normal load, far from the settings change that caused it.

## 11. Requirement Traceability

| Concern | Design section(s) |
| --------- | -------------------- |
| Composition root / dependency injection (S2) | Section 4.9; INV-1 |
| Technology-neutral pipeline nodes | Section 4.1, 4.6; INV-1 |
| Interaction sequence ownership (F1) | Section 4.7, 7; INV-2 |
| Failure-boundary mapping (F4) | Section 4.7, 8; INV-5 |
| Degraded-trace contract (F2) | Section 8 (ERR-1–ERR-4) |
| Intent/reasoning timeout split (F6) / D5 invariant | Section 9; INV-7 |
| Graph-state reducers (F5) | Section 4.6 |
| Host-side audio resampling (S5) | Section 4.11; INV-2 |
| `InteractionWorker` background thread (S1) | Section 4.8; INV-3, INV-4 |
| `Connection` auth/clock-sync seam (S6) | `techdocs/work-packages/WP-105.md` (system-wide seam, WP-105-specific implementation) |
| No mutation executor connected | Section 10 (INV-6) |
| D4 (intent/reasoning model split deferred) | Section 2 (LD-7) |
| BL-03 (WP-105 device auth deferred) | Section 2 (LD-8) |

See `techdocs/ARCHITECTUREREVIEW12926.md` for the review and its full
finding list, and each `techdocs/work-packages/WP-*.md` for which work
package closed which finding and when.

## 12. Notes on Warranted Code Changes

No code was changed in the course of writing this document. Every
signature, constant, and behavioral note in section 4 was transcribed from
the current source in `adapters/contracts.py`, `adapters/stt/whisper_adapter.py`,
`adapters/llm/ollama_adapter.py`, `adapters/tts/piper_adapter.py`,
`adapters/affect/`, `pipeline/graph.py`, `pipeline/interaction.py`,
`pipeline/worker.py`, and `composition/bootstrap.py` as read during
authoring, not recalled from memory. The discrepancies found during this
reorganization are documentation/source-alignment issues: the
`PIPER_MODEL_PATH` extension mismatch, the stale F6 status previously in
`techdocs/ARCH.md`, and the WP-105 reaper being documented as implemented
when it was, at the time, still deferred (closed by a later fix; see
`techdocs/work-packages/WP-105.md`).