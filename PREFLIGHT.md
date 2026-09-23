# PREFLIGHT

Use this checklist immediately before a live rehearsal, evidence capture, or defense demo.

For first-time installation, use [SETUP.md](SETUP.md).

## 1. Repository and Python environment

- [ ] Correct branch and commit.
- [ ] No unintended source changes.
- [ ] Virtual environment is active.
- [ ] Python dependency set is healthy.
- [ ] Full test suite passes in the intended environment.

```bash
git status --short
git branch --show-current
git rev-parse --short HEAD
python --version
python -m pip check
python -m pytest -q
```

A missing declared dependency is an environment failure, not a passing test run.

## 2. Configuration

- [ ] `.env` exists.
- [ ] The run is using the intended `.env` values.
- [ ] No secret values are copied into evidence.
- [ ] `WS_PORT=8765` is available.
- [ ] `DB_PATH` points to the intended database.
- [ ] D5 timeout invariant is satisfied by the settings loader.

Safe configuration summary:

```bash
python -c "from config.settings import get_settings; s=get_settings(); print('host=',s.host_address); print('ws_port=',s.ws_port); print('db_path=',s.db_path); print('ollama_url=',s.ollama_url); print('llm_model=',s.llm_model); print('stt=',s.stt_model_size,s.stt_device,s.stt_compute_type); print('piper=',s.piper_model_path); print('affect=',s.affect_detector_backend); print('queue=',s.interaction_queue_maxsize); print('timeouts=',s.intent_timeout_s,s.reasoning_timeout_s,s.non_llm_timeout_margin_s,s.session_timeout_seconds)"
```

## 3. Ollama

- [ ] Ollama service is running.
- [ ] Configured model is installed.
- [ ] Model answers a basic prompt.

```bash
curl http://localhost:11434/api/tags
ollama list
ollama run llama3.1:8b-instruct-q4_K_M "Reply with OK."
```

Expected model smoke test:

```text
OK
```

## 4. Piper

- [ ] `PIPER_MODEL_PATH` points to the `.onnx` file.
- [ ] `.onnx` file exists.
- [ ] Companion `.onnx.json` exists.

```bash
python -c "from config.settings import get_settings; from pathlib import Path; p=Path(get_settings().piper_model_path); q=p.with_suffix(p.suffix+'.json'); print('onnx:',p,'exists=',p.is_file()); print('json:',q,'exists=',q.is_file())"
```

Do not proceed with a missing companion JSON file.

## 5. Audio

For a real hardware run:

- [ ] Intended microphone is connected.
- [ ] Intended speaker/headphone output is connected.
- [ ] Input/output device settings are correct.
- [ ] Audio format is 16 kHz, mono.

For a transport-only run, hardware is not required:

```bash
python -m scripts.run_manual_stream --silence --no-play
```

## 6. Database

- [ ] SQLite path is writable.
- [ ] Schema initializes.
- [ ] Intended demo state is present.

Preserve existing demo rows:

```bash
python -m scripts.seed_wp103 --no-reset
```

Reset the demo rows only when a clean deterministic baseline is specifically required:

```bash
python -m scripts.seed_wp103
```

## 7. WP-102 host-only smoke test

Run the real host path:

```bash
python -m scripts.run_wp102 > evidences/live_run_wp102.txt 2>&1
```

Confirm that the evidence contains successful initialization, a transcript, a response, and stage timings.

## 8. WP-103 live interaction

Run:

```bash
python -m scripts.run_wp103
```

Confirm:

- [ ] Intended Ollama model is reported.
- [ ] Intended STT configuration is reported.
- [ ] Intended affect backend is reported.
- [ ] Audio capture succeeds.
- [ ] InteractionRunner completes.
- [ ] Policy rule is reported for policy-governed intents.
- [ ] Decision-trace ID is produced.
- [ ] Evidence file is written.

For an existing trace:

```bash
python -m scripts.run_wp103 --dump-trace TRACE_ID
```

## 9. WP-105 WebSocket transport

Start the host in another terminal:

```bash
python -m uvicorn api.app:app --host 0.0.0.0 --port 8765
```

Then:

```bash
python -m scripts.run_manual_stream --silence --no-play
```

For a real interaction:

```bash
python -m scripts.run_manual_stream --seconds 3
```

Confirm:

- [ ] WebSocket connection succeeds.
- [ ] Clock synchronization succeeds.
- [ ] `start_audio` receives `ready`.
- [ ] Audio frames are accepted.
- [ ] `end_audio` produces a response or an expected bounded error.
- [ ] TTS frames are returned when synthesis succeeds.
- [ ] `tts_audio_end` is received.
- [ ] Decision trace is present when the interaction reaches the trace-writing path.

## 10. Freeze/evidence check

Before final evidence capture:

- [ ] Repository is at the intended commit.
- [ ] `python -m pytest -q` passes in the intended environment.
- [ ] Live run used the intended `.env` configuration.
- [ ] No secrets were copied into evidence files.
- [ ] Evidence names/locations are stable.
- [ ] Latency above 3 seconds is reported as measured; it is not hidden by rounding.
- [ ] Deferred functionality is described as deferred, not demonstrated as implemented.

## 11. Common startup problems

### `Ollama request failed`

Check that Ollama is running and that the configured model exists:

```bash
ollama list
```

Also verify `OLLAMA_URL` and `LLM_MODEL` in `.env`.

### `Piper failed to load voice model`

Check `PIPER_MODEL_PATH` and confirm both the `.onnx` file and its
companion `.onnx.json` file exist at that path.

**Known inconsistency to be aware of:** the settings default and
`.env.example` currently ship `PIPER_MODEL_PATH` *without* the `.onnx`
extension, while `PiperVoice.load()` needs the extension included to
find the matching `.onnx.json` companion file. If Piper fails to load on
a fresh checkout with an otherwise-correct model directory, try setting
`PIPER_MODEL_PATH` to the full `.onnx` filename explicitly rather than
assuming the default is correct as shipped.

### Affect classifier fails to load or errors at inference

If `AFFECT_DETECTOR_BACKEND=classifier` is set, confirm the `opensmile`
Python package is installed (pinned in `requirements.txt`) and that the
`OPENSMILE_EXECUTABLE` binary is reachable — this is a runtime
dependency for live classification, not just for WP-104 training. If the
classifier still cannot be loaded, the affect runtime degrades that turn
to `Low` rather than aborting the interaction, so a silent all-`Low`
session can be a symptom of this rather than of the model itself.

### `faster-whisper` model download/load failure

Check network access for the first model load, available disk space,
and that `STT_MODEL_SIZE`, `STT_DEVICE`, and `STT_COMPUTE_TYPE` are
compatible with the installed runtime.

### Microphone or speaker failure

Set the device fields in `.env` when the default operating-system audio
device is not the one you want:

```dotenv
AUDIO_INPUT_DEVICE=
AUDIO_OUTPUT_DEVICE=
```

The adapter reports the device/open failure at runtime rather than
silently falling back.

### SQLite / trace failure on a fresh database

Use the current `scripts.run_wp103` runner. It creates the required demo
user before writing the decision trace. Do not use the destructive reset
seeder as a prerequisite for every live run.

## 12. Minimal pre-demo sequence

```bash
python -m pytest -q
curl http://localhost:11434/api/tags
ollama run llama3.1:8b-instruct-q4_K_M "Reply with OK."
python -m scripts.seed_wp103 --no-reset
python -m scripts.run_wp103
```

For transport rehearsal, start `uvicorn` first and then:

```bash
python -m scripts.run_manual_stream --silence --no-play
```
