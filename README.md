# SYNCRO Host

Host-side runtime for the SYNCRO robot stack. This repository contains the **WP-102 host pipeline**, the **WP-103 dialogue-graph scaffold**, and the **WP-104 acoustic-affect ML pipeline/runtime boundary**.

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

The affect runtime exposes a stable contract-boundary detector. WP-104 supplies the production classifier:

```python
ClassifierAffectDetector(model_path).detect(audio, sample_rate)  # -> "Low" | "Moderate" | "High"
```

The WP-104 affect model, feature extraction, training, evaluation, and macro-F1 evidence are documented under `techdocs/MLSPEC.md` and implemented under `ml/affect/`, with runtime loading through `adapters/affect/`. A clean clone defaults to the deterministic development affect detector; the persisted classifier is selected when explicitly configured and successfully loaded.

## Project layout

```text
api/                 FastAPI application and HTTP/WebSocket surfaces
adapters/            External technology adapters
  affect/             WP-104 affect runtime adapter
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
models/              Local model files; keep binary artifacts out of Git
  affect/             WP-104 artifact instructions and generated classifier metadata
```

## Requirements

Recommended environment for the current repository:

- Python 3.11+
- A working microphone and speaker/audio output for the live host run
- Ollama running locally for the LLM stage
- A Piper voice model installed locally
- Internet access on the first faster-whisper model load so the selected Whisper model can be downloaded/cached

The exact Python package versions are pinned in `requirements.txt`.

WP-104 training also relies on the committed feature tables in `datasets/features/` and their committed `.alignment.json` sidecars. These sidecars bind each feature table to the exact manifest fingerprint used during extraction.

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
INTENT_CONFIDENCE_THRESHOLD=0.60
AFFECT_DETECTOR_BACKEND=development
AFFECT_CLASSIFIER_PATH=./models/affect/affect_svc_v1.joblib
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

## 6a. Prepare WP-104 affect runtime

A clean checkout does not require a trained binary to start. The default is:

```dotenv
AFFECT_DETECTOR_BACKEND=development
```

This returns the deterministic `Low` fallback. To use the trained classifier after generating the artifact locally, set:

```dotenv
AFFECT_DETECTOR_BACKEND=classifier
AFFECT_CLASSIFIER_PATH=./models/affect/affect_svc_v1.joblib
```

If the classifier cannot be loaded, the graph falls back to `Low` for that turn instead of aborting the dialogue.

## 6b. WP-104 command guide

All commands in this section are run from the repository root after activating the Python virtual environment. The commands use the repository's committed scripts directly; there is no separate experiment notebook or undocumented generation step.

### WP-104 workflow order

Use this order when rebuilding the affect dataset and experiments from raw audio:

```bash
# 1. Build canonical RAVDESS/TESS manifests
python -m scripts.build_affect_manifests \
  --ravdess-root datasets/raw/ravdess \
  --tess-root datasets/raw/tess \
  --output-dir datasets/affect/manifests

# 2. Verify the manifests and dataset structure
python -m scripts.verify_affect_manifests \
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \
  --tess-manifest datasets/affect/manifests/tess.csv \
  --ravdess-root datasets/raw/ravdess \
  --tess-root datasets/raw/tess

# 3. Extract the committed 88-feature eGeMAPSv02 feature tables
python -m ml.affect.extract_features \
  --ravdess-root datasets/raw/ravdess \
  --tess-root datasets/raw/tess \
  --manifest-dir datasets/affect/manifests \
  --output-dir datasets/features

# 4. Train the frozen WP-104 SVC baseline and write acceptance evidence
python -m ml.affect.train \
  --ravdess-features datasets/features/ravdess.csv \
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \
  --tess-features datasets/features/tess.csv \
  --tess-manifest datasets/affect/manifests/tess.csv \
  --output models/affect/affect_svc_v1.joblib \
  --evidence-dir evidences/ml/experiment \
  --n-splits 6

# 5. Compare the frozen SVC against the prespecified shallow MLP
python -m ml.affect.compare \
  --ravdess-features datasets/features/ravdess.csv \
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \
  --n-splits 6 \
  --output evidences/ml/experiment/svc_vs_mlp_comparison.json

# 6. Reproduce the fine-tuning/search evidence
python -m ml.affect.tune \
  --ravdess-features datasets/features/ravdess.csv \
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \
  --tess-features datasets/features/tess.csv \
  --tess-manifest datasets/affect/manifests/tess.csv \
  --output-dir evidences/ml/finetune \
  --n-splits 6 \
  --inner-splits 3
```

The repository also supports rebuilding only the already-committed experiment results. In that case, start at step 4 because `datasets/affect/manifests/` and `datasets/features/` are already present.

### 6c. Manifest commands

Build both canonical manifests from the two downloaded corpora:

```bash
python -m scripts.build_affect_manifests \
  --ravdess-root datasets/raw/ravdess \
  --tess-root datasets/raw/tess \
  --output-dir datasets/affect/manifests
```

Verify them without rebuilding anything:

```bash
python -m scripts.verify_affect_manifests
```

To also verify that the manifest audio paths exist under the raw corpus directories:

```bash
python -m scripts.verify_affect_manifests \
  --ravdess-root datasets/raw/ravdess \
  --tess-root datasets/raw/tess
```

### 6d. Feature extraction

Extract RAVDESS and TESS features using the canonical manifests:

```bash
python -m ml.affect.extract_features \
  --ravdess-root datasets/raw/ravdess \
  --tess-root datasets/raw/tess \
  --manifest-dir datasets/affect/manifests \
  --output-dir datasets/features \
  --progress-every 25
```

This writes the feature tables plus their alignment sidecars. The sidecars bind each feature table to the manifest fingerprint used for extraction.

### 6e. Frozen baseline training and acceptance evidence

Train the fixed SVC baseline:

```bash
python -m ml.affect.train \
  --ravdess-features datasets/features/ravdess.csv \
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \
  --tess-features datasets/features/tess.csv \
  --tess-manifest datasets/affect/manifests/tess.csv \
  --output models/affect/affect_svc_v1.joblib \
  --evidence-dir evidences/ml/experiment \
  --n-splits 6
```

The frozen acceptance baseline is **0.632258 macro-F1** on RAVDESS, below the **0.70** gate, so the acceptance result is **NO-GO**. This model remains a prototype affect signal and is not a clinical stress detector.

### 6f. SVC versus MLP comparison

Run the fixed SVC/MLP comparison using the same speaker-disjoint folds:

```bash
python -m ml.affect.compare \
  --ravdess-features datasets/features/ravdess.csv \
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \
  --n-splits 6 \
  --output evidences/ml/experiment/svc_vs_mlp_comparison.json
```

This writes the comparison JSON, including both macro-F1 values, the delta, the selected winner, and confusion matrices. It does not modify the shipped classifier.

### 6g. Reproducible fine-tuning

Fine-tuning is a separate research experiment and must not silently replace the frozen acceptance baseline.

Run the committed producer:

```bash
python -m ml.affect.tune \
  --ravdess-features datasets/features/ravdess.csv \
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \
  --tess-features datasets/features/tess.csv \
  --tess-manifest datasets/affect/manifests/tess.csv \
  --output-dir evidences/ml/finetune \
  --n-splits 6 \
  --inner-splits 3
```

The command produces all currently tracked fine-tuning evidence from committed code:

| Artifact | Producer | Purpose |
|---|---|---|
| `svc_finetune_current.json` | `ml.affect.tune` | Fixed-fold OVR + SelectKBest search |
| `svc_ovr_nested_tuning.json` | `ml.affect.tune` | Nested speaker-disjoint model selection |
| `tess_holdout.json` | `ml.affect.tune` | RAVDESS → TESS cross-corpus holdout |
| `fine_tuning_summary.md` | `ml.affect.tune` | Human-readable summary generated from the fresh results |

Recorded research results are approximately:

```text
Frozen SVC acceptance baseline:       0.632258
OVR + SelectKBest research candidate: 0.651618
Nested OVR research estimate:         0.650564
TESS cross-corpus holdout:             0.240470
Deployment gate:                      0.700000
Acceptance status:                    NO-GO
```

The **0.651618** and **0.650564** values are research candidates, not replacement baseline values. The baseline remains **0.632258**.

The fine-tuning evidence records runtime provenance, including Python/NumPy/scikit-learn versions, the required scikit-learn pin, random state, and SHA-256/fingerprint information for the input feature tables and manifests. This makes the evidence traceable to exact inputs rather than treating committed JSON files as the source of truth.

### 6h. Full WP-104 tests

Run the whole test suite:

```bash
python -m pytest -q
```

Run only the WP-104 unit tests:

```bash
python -m pytest -q tests/unit/ml_affect
```

Run only the reproducibility tests:

```bash
python -m pytest -q tests/unit/ml_affect/test_tune.py
```

For a clean verification before merge, use:

```bash
python -m pytest -q tests/unit/ml_affect tests/integration/test_ml_affect_integration.py
```

### 6i. Useful inspection commands

See the command-line options for any executable module:

```bash
python -m ml.affect.train --help
python -m ml.affect.compare --help
python -m ml.affect.tune --help
python -m ml.affect.extract_features --help
python -m scripts.build_affect_manifests --help
python -m scripts.verify_affect_manifests --help
python -m scripts.seed_wp103 --help
```

The other repository modules under `ml/affect/` (`dataset.py`, `features.py`, `label_mapping.py`, `model.py`, `evaluate.py`, and `artifacts.py`) are library modules used by these command-line entry points; they are not standalone CLI scripts.

## 6j. WP-103 operational scripts

The repository's `scripts/` directory contains the operational runners for WP-102 and WP-103 in addition to the WP-104 dataset helpers.

### Run the WP-102 host-only pipeline

```bash
python -m scripts.run_wp102
```

This requires the configured Ollama, faster-whisper, Piper, microphone, and speaker/audio output.

### Seed the deterministic WP-103 SQLite dataset

Reset the demo rows first:

```bash
python -m scripts.seed_wp103
```

Preserve existing demo rows:

```bash
python -m scripts.seed_wp103 --no-reset
```

Use a specific SQLite database:

```bash
python -m scripts.seed_wp103 --db ./syncro.db
```

### Run the live WP-103 dialogue graph

```bash
python -m scripts.run_wp103
```

The runner creates/uses the `wp103-demo-user`, simulates the edge-owned wake-word event, captures microphone audio, executes the graph, speaks the final response, and prints the decision-trace ID.


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

### Known limitations of the unexecuted-mutation guard

No mutation executor is connected to the graph. Node 3 drafts a reply and nothing can actually add a task, dismiss a reminder, snooze one, or reschedule anything. `_reject_unexecuted_mutation_claim` in `pipeline/nodes/llm.py` therefore exists to stop a drafted reply asserting that a mutation already happened: if it did, the user would hear a spoken confirmation for something that never occurred, and would not retry.

The guard is a lexical rule, not a parser, so it is deliberately imperfect in two known ways. Both are documented here rather than fixed, because closing either would break a more common case:

- **Cross-clause negation is not tracked.** A reply that denies and then claims in the same sentence passes through unguarded, for example `"You told me not to, but this was added anyway."` Catching it would require distinguishing a negator that governs the verb from one that does not, which the current clause-scope model cannot do without also re-breaking `"I have not, however, dismissed that reminder."`

- **Comma-coordinated denials are over-caught.** A denial whose subject is a comma-separated list, for example `"None of the milk, eggs, or bread was added."`, is replaced by the generic reply `"I have not added that yet, but I can add it to your list if you would like."` This is over-caution rather than a false statement - both sentences tell the user nothing was added - but it loses which items were meant. It does not affect object-position lists, parentheticals, or comma-free lists.

Two smaller gaps are known and accepted for the same reason: a completed verb followed by a bare noun with no colon (`"Added task buy milk."`), and mutation verbs outside the per-intent word lists (`"Bumped the call to 6pm."`).

When changing this guard, test both directions. Claims that must be caught and ordinary wording that must pass through untouched are held together in `tests/unit/pipeline/test_llm.py`, and the two parametrised tests there pick up new rows automatically. Widening the rule to catch one more phrasing has twice introduced a false positive on a commoner one, so treat a reported example as a sample of a class rather than as the thing to patch.

## 9. Testing the WP-103 scaffold

Run all tests:

```bash
python -m pytest -q
```

Run the WP-103 integration tests specifically:

```bash
python -m pytest -q tests/integration/test_dialogue_graph_integration.py tests/unit/pipeline/test_graph.py
```

The graph tests may inject a fake affect detector where the test is intended to isolate graph behavior. Runtime composition uses the WP-104 classifier artifact directly.

## 10. Model boundaries: WP-103 vs WP-104

WP-103 uses these external model boundaries:

| Component | WP-103 behavior | Production owner |
|---|---|---|
| STT | `faster-whisper` | Existing host pipeline |
| LLM | Ollama + configured local model | Existing host pipeline |
| TTS | Piper + configured local voice | Existing host pipeline |
| Affect | `ClassifierAffectDetector` → `Low` / `Moderate` / `High` | **WP-104** |

WP-104 owns the affect model file, openSMILE feature extraction, scikit-learn classifier, training/evaluation data, and acceptance evidence described in `techdocs/MLSPEC.md`.

WP-104 now supplies the implementation behind the affect adapter contract together with the model/evaluation evidence required by the roadmap.

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
