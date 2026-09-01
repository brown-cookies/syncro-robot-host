# SYNCRO Host

## Current work package

This repository currently implements the WP-102 host-only runtime path:

```text
USB microphone → faster-whisper → Ollama → Piper → host speakers
```

The WP-102 exit condition is **audio in, synthesized audio out, on the host alone**.
Robot transport, WebSocket processing, LangGraph Nodes 1–4, affect handling, and
later integration work remain outside this package's implemented runtime.

## Architecture

```text
api/                 FastAPI application and HTTP surfaces
composition/        Composition root; builds real dependencies
pipeline/            Technology-neutral WP-102 orchestration
adapters/            Ollama, faster-whisper, and Piper implementations
audio/               Host microphone and speaker implementations
config/              Immutable typed settings and endpoint constants
scripts/             Manual operational entry points
tests/               Automated unit/architecture tests
techdocs/            Specification and architecture documents
```

The pipeline does not construct concrete adapters or access hardware directly.
`composition/bootstrap.py` is the composition root. Tests can therefore inject fake
implementations without loading models or touching audio devices.

## Commands

Run the automated tests:

```powershell
python -m pytest -q
```

Run the real WP-102 host-only acceptance path:

```bash
python -m scripts.run_wp102
```

Use `.env.example` as the configuration template. `.env` is local-only and must
not be committed or included in project archives.
