# SYNCRO Host

Host-side runtime for the SYNCRO robot stack. This repository contains the **WP-102 host pipeline** and the **WP-103 dialogue-graph scaffold**. WP-104 owns the production acoustic-affect classifier and is intentionally **not** implemented here.

## What is implemented

### WP-102

The host-only path is:

```text
USB microphone
    ↓
audio capture
    ↓
faster-whisper (STT)
    ↓
Ollama (LLM)
    ↓
Piper (TTS)
    ↓
host speakers
```

### WP-103 scaffold

WP-103 adds the dialogue graph and its policy/storage boundaries:

```text
                         ┌───────────────┐
                         │  START AUDIO  │
                         └───────┬───────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ↓                               ↓
        ┌─────────────────┐             ┌─────────────────┐
        │  Node 1: STT    │             │ Node 4: Affect  │
        │ faster-whisper  │             │ WP-103 scaffold │
        └────────┬────────┘             │ returns "Low"   │
                 ↓                      └────────┬────────┘
        ┌─────────────────┐                       │
        │ Node 2: Intent  │                       │
        │ / Context       │                       │
        └────────┬────────┘                       │
                 ↓                                │
        ┌─────────────────┐                       │
        │ Node 3: Ollama  │                       │
        │ draft response  │                       │
        └────────┬────────┘                       │
                 └──────────────┬─────────────────┘
                                ↓
                      ┌──────────────────┐
                      │ Policy / Join    │
                      │ deterministic    │
                      └────────┬─────────┘
                               ↓
                        Decision trace
```

`composition/bootstrap.py` is the **composition root**. It creates concrete adapters and storage dependencies and injects them into the graph. The graph itself should remain technology-neutral so tests can replace hardware, STT, LLM, TTS, and affect components with fakes.

The WP-103 affect implementation is deliberately only a contract-boundary stub:

```python
DevelopmentAffectDetector().detect(...)  # -> "Low"
```

Do **not** add the WP-104 classifier to this work package. The production affect model, feature extraction, training, evaluation, and macro-F1 evidence belong to WP-104.

## Project layout

```text
api/                 FastAPI application and HTTP/WebSocket surfaces
adapters/            External technology adapters
  affect.py          WP-103 affect contract + development stub
  llm/               Ollama adapter
  stt/               faster-whisper adapter
  tts/               Piper adapter
audio/               Host microphone, playback, and audio contracts
composition/         Composition root / dependency wiring
config/              Typed environment-backed settings
pipeline/            LangGraph state, graph, nodes, and orchestration
storage/             SQLite schema, context retrieval, and decision traces
scripts/             Manual operational runners and WP-103 seeding
techdocs/            SPEC / ARCH / roadmap and supporting documents
tests/               Unit, contract, architecture, and integration tests
models/              Local model files; keep these out of Git
```

## Requirements

Recommended environment for the current repository:

- Python 3.11+
- A working microphone and speaker/audio output for the live host run
- Ollama running locally for the LLM stage
- A Piper voice model installed locally
- Internet access on the first faster-whisper model load so the selected Whisper model can be downloaded/cached

The exact Python package versions are pinned in `requirements.txt`.

## 1. Create the Python environment

PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Check the installation:

```bash
python --version
python -m pytest -q
```

The tests should be run before a live demo. Environment-dependent LangGraph integration tests may be skipped when their runtime dependency is unavailable.

## 2. Configure local settings

Copy the environment template:

PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Important settings:

```dotenv
OLLAMA_URL=http://localhost:11434
LLM_MODEL=llama3.1:8b-instruct-q4_K_M
STT_MODEL_SIZE=small
STT_COMPUTE_TYPE=int8
STT_DEVICE=cpu
PIPER_MODEL_PATH=./models/en_US-lessac-medium
DB_PATH=./syncro.db
```

`.env` is local configuration and must not be committed.

## 3. Install and prepare Ollama

Install Ollama using the normal installer for your operating system, then start the Ollama service.

Verify that the local API is reachable:

```bash
curl http://localhost:11434/api/tags
```

On Windows PowerShell you can use:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

Pull the model configured by this repository:

```bash
ollama pull llama3.1:8b-instruct-q4_K_M
```

Then confirm it is present:

```bash
ollama list
```

If you use another Ollama model, set `LLM_MODEL` in `.env` to the exact installed model name.

## 4. Prepare the faster-whisper model

The STT adapter uses `faster-whisper`. With the default configuration, the first run loads the `small` model with CPU `int8` compute:

```dotenv
STT_MODEL_SIZE=small
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
```

The model is downloaded/cached by the `faster-whisper`/CTranslate2 stack when it is first constructed. No model file needs to be committed to this repository.

For a different model size, change `STT_MODEL_SIZE` in `.env`, for example:

```dotenv
STT_MODEL_SIZE=base
```

For GPU execution, use a CUDA-compatible environment and set the corresponding `STT_DEVICE` and `STT_COMPUTE_TYPE` values supported by the installed `faster-whisper`/CTranslate2 build. Keep the WP-103 tests model-free by using their injected fakes.

## 5. Install the Piper voice model

WP-102/WP-103 expect the Piper voice directory configured by:

```dotenv
PIPER_MODEL_PATH=./models/en_US-lessac-medium
```

Create that directory and place the matching Piper voice model files in it. The directory must contain the `.onnx` voice model and its companion `.json` configuration used by Piper.

After installation, verify that the path in `.env` points to the directory containing the voice files. The application loads the voice during startup, so a missing or invalid model fails fast with a clear adapter error.

Do not commit large model files to Git. Keep them under the ignored local `models/` directory.

## 6. Prepare the WP-103 SQLite database

The runner now creates the demo user itself, so a completely fresh database is supported.

For repeatable policy/context testing, you can also seed the deterministic WP-103 dataset:

```bash
python -m scripts.seed_wp103
```

This creates the demo user and sample tasks/routine events. By default the seeder resets the WP-103 demo rows first.

To preserve the existing WP-103 demo rows:

```bash
python -m scripts.seed_wp103 --no-reset
```

The live runner does **not** call the resetting seeder automatically.

## 7. Run WP-103

Start Ollama first, make sure your Piper model path is valid, and connect the microphone/speaker you want to use.

Then run:

```bash
python -m scripts.run_wp103
```

The runner:

1. builds the real WP-103 graph from the composition root;
2. ensures `wp103-demo-user` exists in SQLite;
3. simulates the edge-owned wake-word event (`syncro`);
4. records a fixed-duration microphone sample;
5. runs the graph;
6. prints per-stage timing and the final response;
7. writes the resulting decision trace to SQLite.

The wake-word stage is intentionally simulated in this host runner because wake-word ownership is outside the WP-103 host graph boundary.

## 8. How the architecture is used

For normal application execution, use the composition root instead of constructing concrete adapters inside graph nodes:

```python
from composition.bootstrap import build_wp103_components
from config.settings import get_settings

settings = get_settings()
graph, store, audio_input, audio_output, tts = build_wp103_components(settings)
```

The important dependency direction is:

```text
scripts / API
      ↓
composition/bootstrap.py
      ↓
pipeline graph + injected contracts
      ↓
adapters / audio / storage
      ↓
external systems
(Ollama, Whisper, Piper, SQLite, microphone, speakers)
```

### Why this boundary exists

- **Pipeline nodes** contain workflow logic, not vendor setup.
- **Adapters** translate external technologies into small application contracts.
- **Composition** decides which concrete implementations are used.
- **Tests** can inject fakes without a microphone, Ollama, Piper, or downloaded models.
- **Storage** owns persistence rather than leaking SQLite operations into graph nodes.

This is the expected way to extend the host: add or replace an adapter at the boundary and wire it through the composition root rather than importing the concrete technology directly into the graph.

## 9. Testing the WP-103 scaffold

Run all tests:

```bash
python -m pytest -q
```

Run the WP-103 integration tests specifically:

```bash
python -m pytest -q tests/integration/test_wp103_integration.py tests/test_wp103_graph.py
```

The WP-103 graph tests inject a fake affect detector. That is intentional: **WP-103 validates graph wiring and policy behavior without depending on the future WP-104 acoustic classifier.**

## 10. Model boundaries: WP-103 vs WP-104

WP-103 uses these external model boundaries:

| Component | WP-103 behavior | Production owner |
|---|---|---|
| STT | `faster-whisper` | Existing host pipeline |
| LLM | Ollama + configured local model | Existing host pipeline |
| TTS | Piper + configured local voice | Existing host pipeline |
| Affect | `DevelopmentAffectDetector` → `Low` | **WP-104** |

WP-103 therefore does **not** require an affect model file, openSMILE feature extraction, a scikit-learn classifier, or affect-training data to exercise its scaffold.

When WP-104 is developed, it should replace the implementation behind the affect adapter contract and then supply the real model/evaluation evidence required by the roadmap.

## 11. Common startup problems

### `Ollama request failed`

Check that Ollama is running and that the configured model exists:

```bash
ollama list
```

Also verify `OLLAMA_URL` and `LLM_MODEL` in `.env`.

### `Piper failed to load voice model`

Check `PIPER_MODEL_PATH` and confirm the directory contains the matching `.onnx` and `.json` voice files.

### `faster-whisper` model download/load failure

Check network access for the first model load, available disk space, and that `STT_MODEL_SIZE`, `STT_DEVICE`, and `STT_COMPUTE_TYPE` are compatible with the installed runtime.

### Microphone or speaker failure

Set the device fields in `.env` when the default operating-system audio device is not the one you want:

```dotenv
AUDIO_INPUT_DEVICE=
AUDIO_OUTPUT_DEVICE=
```

The adapter reports the device/open failure at runtime rather than silently falling back.

### SQLite / trace failure on a fresh database

Use the current `scripts.run_wp103` runner. It creates the required demo user before writing the decision trace. Do not use the destructive reset seeder as a prerequisite for every live run.

## 12. Evidence and operational artifacts

Generated databases, local model files, caches, recordings, and other runtime artifacts should remain local unless they are explicitly required as evidence for an acceptance criterion.

Keep acceptance evidence small and reproducible. For WP-103, useful evidence includes:

- passing WP-103 graph/integration test output;
- a successful fresh-database live run;
- stage-level timings from `run_wp103.py`;
- the resulting decision trace row(s).

See `techdocs/SPEC.md`, `techdocs/ARCH.md`, and `techdocs/roadmap.md` for the normative architecture and acceptance requirements.
