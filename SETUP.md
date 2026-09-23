# SETUP

This document gets a clean SYNCRO Host checkout from zero to a runnable development environment.

For the final pre-demo verification sequence, use [PREFLIGHT.md](PREFLIGHT.md).
For requirements and architecture contracts, use `techdocs/SPEC.md` and `techdocs/ARCH.md`.

## 1. Prerequisites

- Python 3.11 or newer
- Git
- Ollama installed and running locally
- A microphone and speaker/audio output for live host runs
- Network access for the first `faster-whisper` model download

The exact Python package versions are pinned in `requirements.txt`.

## 2. Create the Python environment

From the repository root.

### Git Bash / Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Verify the environment:

```bash
python --version
python -m pip check
python -m pytest -q
```

## 3. Create local configuration

Copy `.env.example` to `.env`.

### Git Bash / Linux / macOS

```bash
cp .env.example .env
```

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

`.env` is local configuration and must not be committed.

Important runtime settings include:

```dotenv
HOST_ADDRESS=0.0.0.0
WS_PORT=8765
DB_PATH=./syncro.db

OLLAMA_URL=http://localhost:11434
LLM_MODEL=llama3.1:8b-instruct-q4_K_M

STT_MODEL_SIZE=small
STT_COMPUTE_TYPE=int8
STT_DEVICE=cpu

PIPER_MODEL_PATH=./models/en_US-lessac-medium.onnx

AFFECT_DETECTOR_BACKEND=development
AFFECT_CLASSIFIER_PATH=./models/affect/affect_svc_v1.joblib

AUDIO_SAMPLE_RATE_HZ=16000
AUDIO_CHANNELS=1
AUDIO_CAPTURE_SECONDS=5

INTENT_TIMEOUT_S=5
REASONING_TIMEOUT_S=6
NON_LLM_TIMEOUT_MARGIN_S=10
SESSION_TIMEOUT_SECONDS=30
```

The D5 timeout invariant is enforced by `config/settings.py`: the intent timeout, reasoning timeout, and non-LLM margin must sum to less than the session timeout.

### Optional HTTP authentication settings

The HTTP task-ingest and decision-trace routes support separate source and participant authentication. Local development can leave these empty until those routes are being exercised:

```dotenv
SOURCE_INGEST_TOKEN=
SOURCE_INGEST_SOURCE=
PARTICIPANT_API_TOKENS_JSON={}
```

`SOURCE_INGEST_TOKEN` authenticates a configured connector. `SOURCE_INGEST_SOURCE` identifies that connector. `PARTICIPANT_API_TOKENS_JSON` maps bearer tokens to participant user IDs.

## 4. Install and verify Ollama

Install Ollama for the host operating system and start the local service.

Verify the API:

```bash
curl http://localhost:11434/api/tags
```

On Windows PowerShell:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

Pull the configured model:

```bash
ollama pull llama3.1:8b-instruct-q4_K_M
ollama list
```

Run a real smoke test:

```bash
ollama run llama3.1:8b-instruct-q4_K_M "Reply with OK."
```

Expected response:

```text
OK
```

## 5. Prepare faster-whisper

The default configuration is:

```dotenv
STT_MODEL_SIZE=small
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
```

The first real STT initialization downloads/caches the selected model through the `faster-whisper` / CTranslate2 stack. Whisper model binaries are not committed to this repository.

## 6. Install the Piper voice model

The Piper adapter loads `PIPER_MODEL_PATH` directly as the model path. Set it to the `.onnx` file, not the containing directory.

Expected local files:

```text
models/
├── en_US-lessac-medium.onnx
└── en_US-lessac-medium.onnx.json
```

Use the matching Piper voice release for both files.

Verify the configured files:

```bash
python -c "from config.settings import get_settings; from pathlib import Path; p=Path(get_settings().piper_model_path); print('onnx:',p,'exists=',p.is_file()); q=p.with_suffix(p.suffix+'.json'); print('json:',q,'exists=',q.is_file())"
```

A missing model or companion configuration causes Piper initialization to fail.

Large model files remain local and are ignored by Git.

## 7. Prepare the affect runtime

A clean checkout uses the deterministic development backend:

```dotenv
AFFECT_DETECTOR_BACKEND=development
```

To run the trained WP-104 classifier, place:

```text
models/affect/affect_svc_v1.joblib
```

and set:

```dotenv
AFFECT_DETECTOR_BACKEND=classifier
AFFECT_CLASSIFIER_PATH=./models/affect/affect_svc_v1.joblib
```

If the classifier cannot be loaded, the affect runtime degrades that turn to `Low` rather than aborting the interaction.

## 8. Initialize the database

The WP-103 live runner creates `wp103-demo-user` itself and supports a fresh database.

For deterministic policy/context testing, seed the development dataset:

```bash
python -m scripts.seed_wp103
```

Preserve existing demo rows:

```bash
python -m scripts.seed_wp103 --no-reset
```

The seeder is a development/testing tool; it is not required before every live run.

## 9. Start the host WebSocket service

The FastAPI application is exposed by `api.app:app`.

```bash
python -m uvicorn api.app:app --host 0.0.0.0 --port 8765
```

The WebSocket endpoint is:

```text
ws://127.0.0.1:8765/v1/stream
```

## 10. Run WP-102

```bash
python -m scripts.run_wp102
```

This exercises microphone capture → STT → Ollama → Piper → host playback.

## 11. Run WP-103

```bash
python -m scripts.run_wp103
```

The runner builds the host components, ensures `wp103-demo-user`, simulates the edge-owned wake word, captures audio, runs the graph, synthesizes the response, persists the decision trace, and writes evidence.

To reproduce the evidence for an existing trace without running the pipeline again:

```bash
python -m scripts.run_wp103 --dump-trace TRACE_ID
```

## 12. Run the WebSocket smoke test

With the FastAPI server running in another terminal:

```bash
python -m scripts.run_manual_stream --silence --no-play
```

This uses silence rather than a physical microphone and is intended for a transport/error-path check.

For a real microphone interaction:

```bash
python -m scripts.run_manual_stream --seconds 3
```

## 13. WP-104 dataset and ML reproduction

Raw RAVDESS/TESS files are not committed. Use the committed manifests, feature tables, and scripts described in `techdocs/MLSPEC.md` and `techdocs/dataset_manifest_verification.md` when reproducing the affect experiments.

## 14. Keep local material out of Git

Do not commit:

- `.env` and other local environment files
- local SQLite databases
- Whisper, Ollama, Piper, or other model binaries
- raw RAVDESS/TESS datasets
- local logs or caches

The repository `.gitignore` is configured for these artifacts.
