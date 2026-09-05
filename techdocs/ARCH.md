# ARCH.md — SYNCRO Host Runtime Scaffolding

This document is the implementation architecture for the current SYNCRO host
development work package, **WP-102**.

WP-102 is defined in `roadmap.md` as:

> Host runtime scaffolding: FastAPI + Ollama + `faster-whisper` + Piper, wired
> end to end and driven by a USB microphone. No robot involved.

Its exit condition is:

> Audio in, synthesized audio out, on the host alone.

This document therefore describes **only the current WP-102 scaffolding** and
the repository structure required to build it. It does not invent the design
for later work packages. Dialogue Nodes 1–4, the affect branch, the transport
work package, Porcupine, and later integration work remain outside the scope of
this document unless already present as a current repository artifact.

The specification remains the source of truth for requirements and shared data
contracts. This document describes the implementation structure used to satisfy
the current work package.

---

## Table of Contents

1. Purpose, Relationship to the Specification, Targeted Environment
2. Locked Decisions (LD-1..LD-n)
3. Project Structure
4. WP-102 Runtime Architecture
5. Current Module / Dependency Interface Reference
   - 5.1 `api/app.py`
   - 5.2 `api/http/health.py`
   - 5.3 `api/ws/stream.py`
   - 5.4 `config/settings.py`
   - 5.5 `config/endpoints.py`
   - 5.6 `adapters/`
   - 5.7 `audio/`
   - 5.8 `pipeline/`
6. State and Resource Ownership
7. WP-102 Control Flow
8. Error Handling Boundary
9. WP-102 Performance and Measurement
10. Invariants (INV-1..INV-n)
11. WP-102 Verification / Traceability
12. Notes on Warranted Code Changes

---

## 1. Purpose, Relationship to the Specification, Targeted Environment

### 1.1 Purpose

`SPEC.md` / `host-spec` defines WHAT the host must do. `ARCH.md` defines HOW
the current implementation is organized for WP-102.

For WP-102, the implementation target is the host alone:

```text
USB microphone
      ↓
host audio path
      ↓
faster-whisper
      ↓
Ollama
      ↓
Piper
      ↓
host audio output
```

The robot is not part of WP-102.

### 1.2 Work-package boundary

The current development target is exactly WP-102. Its predecessor is WP-101
and its successor is WP-103. The roadmap assigns WP-102 to the Host AI pipeline
workstream and defines the exit criterion as audio entering the host and
synthesized audio leaving the host, without the robot. fileciteturn8file1L80-L90

No later work-package behavior is treated as implemented merely because a
folder exists in the repository.

### 1.3 Targeted components

The roadmap explicitly names these WP-102 runtime components:

- FastAPI
- Ollama
- `faster-whisper`
- Piper
- USB microphone

The host specification identifies the currently selected local AI/runtime
stack, including Ollama with `llama3.1:8b-instruct-q4_K_M`, `faster-whisper`
`small` with int8, and Piper `en_US-lessac-medium`. Where those values are
still marked open in the specification, this document does not replace them
with an invented value.

---

## 2. Locked Decisions

These are the decisions that apply to the current WP-102 implementation.

### LD-1. WP-102 is the current scope.

This architecture document covers host runtime scaffolding only.

### LD-2. The WP-102 acceptance target is host-only.

The USB microphone, host processing, and host audio output are exercised
without the robot.

### LD-3. FastAPI is the host application/API framework.

The current repository already contains the FastAPI application entry point
under `api/app.py`.

### LD-4. Ollama, `faster-whisper`, and Piper remain adapter boundaries.

The current repository keeps these technologies under `adapters/` rather than
coupling the API entry point directly to each vendor/runtime interface.

### LD-5. The current repository structure is the source of truth for the
scaffolding layout.

This document records the structure already created by the implementation
rather than replacing it with a proposed alternative.

### LD-6. Empty directories are scaffolding, not implemented functionality.

The existence of `audio/`, `pipeline/`, or an adapter subdirectory does not
mean that the corresponding runtime behavior is complete.

### LD-7. Generated Python cache files are not source components.

`__pycache__/` and `*.pyc` are generated artifacts and are not part of the
architectural source tree.

### LD-8. `pipeline/` does not construct concrete runtime dependencies.

The WP-102 pipeline depends only on technology-neutral processing and audio
contracts. Concrete microphone, speaker, STT, LLM, and TTS implementations are
constructed by `composition/bootstrap.py`.

### LD-9. Configuration is immutable and injected at construction boundaries.

`Settings` is a frozen configuration object. Components receive the
settings snapshot they need at construction rather than relying on mutable global
configuration.

---

## 3. Project Structure

The current WP-102 repository structure is:

```text
syncro-host/
│
├── adapters/
│   ├── contracts.py              # technology-neutral STT/LLM/TTS protocols
│   ├── llm/
│   │   ├── ollama_adapter.py
│   │   └── __init__.py
│   ├── stt/
│   │   ├── whisper_adapter.py
│   │   └── __init__.py
│   ├── tts/
│   │   ├── piper_adapter.py
│   │   └── __init__.py
│   └── __init__.py
│
├── api/
│   ├── app.py
│   ├── http/
│   │   ├── health.py
│   │   └── __init__.py
│   ├── ws/
│   │   ├── stream.py                # future transport scaffold
│   │   └── __init__.py
│   └── __init__.py
│
├── audio/
│   ├── capture.py               # host microphone implementation
│   ├── contracts.py             # AudioInput / AudioOutput protocols
│   ├── playback.py              # host speaker implementation
│   └── __init__.py
│
├── config/
│   ├── endpoints.py
│   ├── settings.py              # immutable Settings + get_settings()
│   └── __init__.py
│
├── pipeline/
│   ├── host_pipeline.py         # WP-102 orchestration only
│   ├── graph.py                 # future WP-103 scaffold
│   ├── state.py                 # future WP-103 scaffold
│   ├── nodes/                    # future WP-103 scaffolding
│   └── __init__.py
│
├── composition/
│   ├── bootstrap.py              # WP-102 composition root
│   └── __init__.py
│
├── scripts/
│   ├── run_wp102.py              # manual real-runtime acceptance run
│   └── __init__.py
│
├── techdocs/
│   ├── ARCH.md
│   ├── profile-full-report-rtx-4060.md
│   ├── roadmap.md
│   └── SPEC.md
│
└── tests/
    ├── unit/
    │   ├── api/
    │   ├── config/
    │   ├── adapters/
    │   ├── audio/
    │   ├── pipeline/
    │   └── composition/
    ├── integration/
    │   ├── test_host_pipeline_integration.py
    │   ├── test_dialogue_graph_integration.py
    │   └── test_affect_classifier_integration.py
    ├── test_wp102_architecture.py
    ├── conftest.py
    └── __init__.py
```

`api/http/` and the future graph/node files may exist as repository scaffolding,
but their presence does not claim that the full SPEC host server or WP-103 is
implemented. The implemented WP-102 path is centered on `composition/`, `pipeline/`,
`audio/`, and the three AI adapter packages. Automated verification is layered
under `tests/unit/` and `tests/integration/`.

---

## 4. WP-102 Runtime Architecture

The current end-to-end objective is deliberately simple:

```text
                    HOST ONLY

USB microphone
     │
     ▼
┌───────────────┐
│ Audio input   │
└───────┬───────┘
        │ PCM/audio data
        ▼
┌───────────────┐
│ faster-       │
│ whisper       │
└───────┬───────┘
        │ transcript
        ▼
┌───────────────┐
│ Ollama        │
│ LLM           │
└───────┬───────┘
        │ response text
        ▼
┌───────────────┐
│ Piper         │
│ TTS           │
└───────┬───────┘
        │ synthesized audio
        ▼
┌───────────────┐
│ Host audio    │
│ output        │
└───────────────┘
```

WP-102 is successful only when this host-only path can be exercised
end-to-end.

The WebSocket/robot path is not required for this work-package exit condition.

---

## 5. Current Module / Dependency Interface Reference

This section describes only files and directories that currently exist in the
repository. It does not assign unimplemented responsibilities to them.

### 5.1 `api/app.py`

Current role: FastAPI application entry point.

The file is the host API composition location.

WP-102 requirement:

- provide the application object needed to run the host service;
- remain independent from robot hardware.

No additional application behavior is claimed here unless implemented in the
file.

### 5.2 `api/http/health.py`

Current role: HTTP health endpoint location.

This provides the first simple HTTP surface used to verify that the FastAPI
application can start independently of the AI pipeline.

It is a composition/bootstrap check, not the WP-102 audio acceptance path.

### 5.3 `api/ws/stream.py`

Current role: WebSocket endpoint location.

The host specification defines `/v1/stream` and the WebSocket message protocol.
The complete transport implementation is outside the narrow WP-102 acceptance
criterion.

For WP-102, this file may remain scaffolding while host-only audio processing is
built and verified.

### 5.4 `config/settings.py`

Current role: host runtime settings.

Configuration that is needed by the current host runtime belongs here rather
than being duplicated across API, adapters, and pipeline code.

Only settings that are actually required by WP-102 should be added during this
work package.

### 5.5 `config/endpoints.py`

Current role: configured service/endpoint locations.

This is the single location for endpoint-related configuration already chosen
for the repository.

No new service endpoint is introduced here unless the specification or WP-102
implementation requires it.

### 5.6 `adapters/`

The current adapter structure is:

```text
adapters/
├── llm/
├── stt/
└── tts/
```

These folders correspond directly to the three external/local runtime
technologies named by WP-102:

```text
adapters/llm  → Ollama
adapters/stt  → faster-whisper
adapters/tts  → Piper
```

The adapter layer exists so that the rest of the host does not need to depend
directly on technology-specific implementation details.

At WP-102 start, an adapter directory is a boundary; it is not evidence that
the adapter is already implemented.

### 5.7 `audio/`

Current role: host-side audio handling location.

WP-102 needs a host audio path capable of receiving input from a USB microphone
and producing host-side synthesized audio output.

Only the behavior actually implemented and verified in this directory should
be considered complete.

### 5.8 `pipeline/`

Current role: host processing/pipeline location.

`host_pipeline.py` owns only the WP-102 stage sequence. It depends on contracts
for audio input/output and STT/LLM/TTS processing; it does not construct concrete
implementations or import vendor SDKs. This keeps the orchestration layer
deterministic and directly unit-testable.

The later LangGraph Nodes 1–4 work belongs to WP-103, which the roadmap places
after WP-102. fileciteturn8file1L88-L90

### 5.9 `composition/`

Current role: process-level composition root.

`composition/bootstrap.py` is the one place where the WP-102 production objects are
assembled: `MicrophoneAudioInput`, `WhisperSTTAdapter`, `OllamaLLMAdapter`,
`PiperTTSAdapter`, and `SpeakerAudioOutput`. Keeping construction here prevents
application orchestration and tests from reaching into concrete dependency setup.

---

## 6. State and Resource Ownership

For WP-102, keep state limited to what the host-only audio path actually needs.

### 6.1 Runtime resources

The three named model/runtime dependencies are:

```text
faster-whisper
Ollama
Piper
```

Each belongs behind its corresponding adapter boundary.

### 6.2 Interaction data

The current host-only interaction needs:

```text
microphone input
→ audio representation
→ transcript
→ LLM response text
→ synthesized audio
```

The implementation should avoid adding persistence requirements merely for
scaffolding.

### 6.3 No robot state

WP-102 does not own or require:

```text
ESP32 state
device motion
motor commands
robot playback
WebSocket edge execution
```

Those belong to later work.

---

## 7. WP-102 Control Flow

The WP-102 control flow is:

```text
1. Start the host application.
2. Initialize the host-side runtime dependencies required by WP-102.
3. Acquire audio from the USB microphone.
4. Pass the captured audio through the STT adapter.
5. Pass the resulting text through the LLM adapter.
6. Pass the generated text through the TTS adapter.
7. Produce synthesized audio on the host.
8. Make the host audio output observable for verification.
```

The implementation should keep each technology behind its adapter boundary.

The acceptance path does not require the robot or robot WebSocket transport.

---

## 8. Error Handling Boundary

WP-102 should make failures visible at the dependency boundary rather than
silently substituting a different runtime.

### Current failure classes

| ID | Failure | Boundary |
|---|---|---|
| ERR-1 | USB microphone unavailable | `audio/` |
| ERR-2 | `faster-whisper` initialization/transcription failure | `adapters/stt/` |
| ERR-3 | Ollama unavailable/model failure | `adapters/llm/` |
| ERR-4 | Piper unavailable/synthesis failure | `adapters/tts/` |
| ERR-5 | Host audio output unavailable | `audio/` |

These identifiers are local WP-102 architecture labels; they do not replace
error codes already defined by `SPEC.md` / `host-spec`.

A failed dependency must surface as a failure of that dependency boundary. The
host must not report the WP-102 audio-in/audio-out path as successful when one
of its required stages did not execute.

---

## 9. WP-102 Performance and Measurement

WP-102 needs to prove that the host-only chain works, not merely that imports
succeed.

The minimum useful measurements are:

```text
microphone capture starts
STT completes
LLM response completes
TTS synthesis completes
audio output is produced
```

Where timing is collected, record the individual stage durations separately
rather than presenting an aggregate number without knowing which stage produced
it.

The hardware capacity validation in WP-101 is the predecessor to WP-102. The
roadmap states that WP-101 validates `llama3.1:8b` on the RTX 4060 with
`faster-whisper small int8` loaded alongside it. fileciteturn8file7L300-L305

Therefore WP-102 should use the already-established platform result rather than
inventing a new hardware assumption.

---

## 10. Invariants

Every invariant below has a Rule, Reason, and Failure mode if violated.

### INV-1. WP-102 remains host-only.

Rule: the WP-102 acceptance path does not require the robot.

Reason: the roadmap explicitly defines "No robot involved" for WP-102.

Failure mode: host-runtime failures become entangled with firmware or transport
failures, making the work package impossible to isolate.

### INV-2. The three named AI technologies remain separate adapters.

Rule: Ollama, `faster-whisper`, and Piper are accessed through their respective
adapter boundaries.

Reason: each dependency has its own runtime/API and can fail independently.

Failure mode: vendor/runtime details leak through the application and make later
replacement or testing unnecessarily coupled.

### INV-3. Audio flows through the host-only chain.

Rule: successful WP-102 execution must contain the complete path

```text
audio in → STT → LLM → TTS → audio out
```

Reason: that is the defined WP-102 exit condition.

Failure mode: the project can falsely mark scaffolding complete when only
individual components run independently.

### INV-4. No later work package is claimed complete by folder existence.

Rule: an existing directory or empty module does not count as implemented
behavior.

Reason: the repository is being scaffolded incrementally.

Failure mode: the project documentation claims functionality that has not been
built or verified.

### INV-5. Configuration is not duplicated unnecessarily.

Rule: values needed by multiple WP-102 components are sourced from the
configuration layer rather than repeated as independent literals.

Reason: duplicated configuration creates drift.

Failure mode: two components use different runtime endpoints, model names, or
timeouts without the discrepancy being obvious.

### INV-6. Failed dependencies do not produce false success.

Rule: if a required WP-102 stage fails, the end-to-end path is considered
failed.

Reason: synthesized audio output is only meaningful when the preceding stages
actually executed.

Failure mode: a fallback or placeholder is mistaken for a successful
STT → LLM → TTS run.

---

## 11. WP-102 Verification / Traceability

WP-102 has one primary exit condition:

```text
Audio in, synthesized audio out, on the host alone.
```

The verification path is therefore:

| WP-102 element | Verification | Status |
|---|---|---|
| FastAPI host starts | Start the host application successfully | **Verified** - health check return `{ "status": "ok" }` |
| USB microphone input | Capture real microphone audio | **Verified** — `audio_capture` stage completed in a live run |
| `faster-whisper` | Produce a transcript from captured audio | **Verified** — real transcript produced ("Hello hello, how are you? I'm good") |
| Ollama | Produce a response from the transcript | **Verified** — real LLM response produced |
| Piper | Synthesize audio from the response | **Verified** — synthesized audio produced and played |
| Host-only output | Produce observable synthesized audio without the robot | **Verified** — audio heard on host speakers |
| End-to-end path | Complete audio-in → synthesized-audio-out in one run | **Verified**, single run, stage durations: capture 5.39s, stt 1.41s, llm 12.97s, tts 0.54s, audio_output 12.77s |

The roadmap places WP-103 after WP-102 and assigns the LangGraph Nodes 1–4 work
to WP-103, so Node 1–4 completion is not used as a hidden prerequisite for
declaring WP-102 complete. fileciteturn8file1L88-L90

---

## 12. Notes on Warranted Code Changes

The host-only path described in Section 4 is implemented and has been run
successfully end-to-end (Section 11). All five stages — capture, STT, LLM,
TTS, audio output — executed in one run with per-stage timing recorded.

The architecture refactor separates construction from orchestration and makes
the WP-102 core directly testable with injected fakes. The next warranted work
for WP-102 is therefore focused pytest coverage: each concrete adapter should
get happy-path and failure-path tests, the audio boundaries should get device/error
tests, and the pipeline should verify INV-6 by proving that a failure at any
single stage fails the whole run and is tagged with the correct stage name.

As before: any change introducing robot transport, LangGraph Nodes 1-4, the
affect branch, Porcupine, or later integration behavior remains outside
WP-102 scope.