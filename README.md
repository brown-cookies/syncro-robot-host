# SYNCRO Host

Host-side runtime for the SYNCRO robot stack: a voice pipeline (STT →
LLM → TTS) wrapped in a dialogue graph with policy, storage, an affect
runtime, and a WebSocket transport layer.

## Start here

| Doc | Purpose |
| --- | --- |
| `SETUP.md` | Get a clean checkout running from zero |
| `PREFLIGHT.md` | Checklist before a live rehearsal, evidence capture, or demo |
| `techdocs/ARCH.md` | How the pieces connect and why — system-wide, not per work package |
| `techdocs/SPEC.md` | Requirements and contracts |
| `techdocs/roadmap.md` | Where the project is headed |
| `techdocs/ARCHITECTUREREVIEW12926.md` | The architecture review and its full finding list |

## Work packages

| Doc | Covers |
| --- | --- |
| `techdocs/work-packages/WP-102.md` | Host-only pipeline: mic → STT → LLM → TTS → speakers |
| `techdocs/work-packages/WP-103.md` | Dialogue graph, policy/storage boundaries, decision traces |
| `techdocs/work-packages/WP-104.md` | Acoustic-affect ML pipeline and runtime classifier |
| `techdocs/work-packages/WP-105.md` | `/v1/stream` WebSocket transport |

## Project layout

```text
api/                 FastAPI application and HTTP/WebSocket surfaces
adapters/            External technology adapters (affect, llm, stt, tts)
audio/               Host microphone, playback, and audio contracts
composition/         Composition root / dependency wiring
config/              Typed environment-backed settings
pipeline/            Graph state, graph, nodes, and orchestration
storage/             SQLite schema, context retrieval, and decision traces
ml/affect/           Affect feature extraction, training, tuning, evaluation
datasets/            Committed affect manifests and feature tables
evidences/           Live-run stage-timing logs and ML acceptance evidence
scripts/             Manual operational runners and dataset seeding
techdocs/            Specs, architecture, roadmap, and work-package docs
tests/               Unit, contract, architecture, and integration tests
models/              Local model files; keep binary artifacts out of Git
```

See `techdocs/ARCH.md` for what each of these actually does and how they
depend on each other.

## Requirements

Recommended environment for the current repository:

- Python 3.11+
- A working microphone and speaker/audio output for the live host run
- Ollama running locally for the LLM stage
- A Piper voice model installed locally
- Internet access on the first faster-whisper model load so the
  selected Whisper model can be downloaded/cached

The exact Python package versions are pinned in `requirements.txt`. Full
setup steps are in `SETUP.md`.

## Evidence and operational artifacts

Generated databases, local model files, caches, recordings, and other
runtime artifacts should remain local unless explicitly required as
evidence for an acceptance criterion. Keep acceptance evidence small and
reproducible — see each work package's doc for what counts as evidence
for it, and `PREFLIGHT.md` for the pre-capture checklist.
