# SPECIFICATION.md — WP-104 ML Development & Runtime Contract (SYNCRO)

Self-contained. No reference to any prior conversation is required to resume work from this
file alone.

## 0. Context restated

**Project:** SYNCRO — a voice-assisted robot companion capstone (Team 9, Holy Angel University:
Almedejar / AI-software lead, Espinosa, Marimla). Prototype defense: 1 October 2026.

**Work package:** WP-104, per the baselined roadmap (`techdocs/roadmap.md`, rev 2.2/2.3),
owned solely by Almedejar, scheduled in Week 1 (31 Aug–6 Sep 2026), gated at **G3 (6 Sep
2026\)**. **G3 is today's date in the active session** — this work package is not upcoming, it
is due.

**Deliverable it satisfies:** DEL-02 — "Affect classification branch: openSMILE eGeMAPS →
scikit-learn classifier → macro-F1 result." Acceptance per the roadmap: *"A macro-F1 figure
exists, produced under speaker-independent cross-validation (**`GroupKFold`* *grouped by speaker),
with the methodology documented."* Evidence required: script or notebook; confusion matrix;
method note.

**Why this package first:** RSK-05 (affect classifier scores below macro-F1 0.70) is the
project's highest-rated risk. It needs no hardware, so it is scheduled earliest deliberately —
a result below threshold is "worth six weeks of warning rather than six days."

**Governing decision document already produced by the team:** `techdocs/MLAlgo.md` (also
present as `decisions/MLAlgo.md` on the `feature/wp-104` branch). It fixes: openSMILE eGeMAPS
v02 for feature extraction (deterministic DSP, not ML); scikit-learn (`StandardScaler` →
`SVC(kernel="rbf", class_weight="balanced")`, or `MLPClassifier` for comparison) for
classification (the only learned component); `GroupKFold` grouped by speaker for evaluation;
RAVDESS (1,440 clips, 24 speakers) as the primary GroupKFold training/eval corpus; TESS (2,800
clips, 2 speakers) as a held-out generalisation check only, never folded into GroupKFold
training. This specification does not re-litigate those decisions — it specifies the
deliverable that implements them.

**Existing WP-103 scaffold this package integrates with:**

- `adapters/affect.py` — `DevelopmentAffectDetector.detect(audio, sample_rate: int) -> str`, a WP-103 development stub that always returns `"Low"`. WP-104 replaces this implementation behind the same contract.
- `pipeline/nodes/affect.py` — `make_affect_node(detector)` wraps any object exposing `.detect(audio, sample_rate) -> str`, validates the return is one of `{"Low", "Moderate", "High"}` (`ALLOWED_AFFECT_LEVELS`), raises `AffectDetectionError` otherwise, and returns `{"affect_level": affect_level}` into `DialogueState`. **This node requires no change for WP-104.**
- `config/settings.py` — `audio_sample_rate_hz: int = 16000` is the host pipeline's fixed capture rate and the common audio normalization target for WP-104 feature extraction.
- `requirements.txt` — WP-104 must add its ML/runtime dependencies as specified by criterion 14.

### 0.1 Structural decision — ML development vs runtime location

WP-104 is split into two explicit implementation boundaries. The separation is contractual and is
intended to preserve the WP-103 graph architecture while allowing the classifier to be developed,
evaluated, versioned, and replaced independently of the host pipeline.

- **`ml/affect/` is the offline ML-development boundary.** It owns dataset manifests/validation,
  label mapping, openSMILE eGeMAPSv02 feature extraction, model construction/training, speaker-
  independent evaluation, artifact creation, and ML evidence generation. It does **not** become a
  runtime dependency of `pipeline/nodes/affect.py`.
- **`adapters/affect/` is the runtime boundary.** It owns the concrete detector implementation that
  consumes a trained artifact and exposes the existing `.detect(audio, sample_rate) -> str`
  contract. `pipeline/nodes/affect.py` remains implementation-agnostic and unchanged.
- **`pipeline/nodes/affect.py` remains the orchestration boundary.** It accepts any detector that
  satisfies the existing detector contract, validates the returned value against
  `ALLOWED_AFFECT_LEVELS`, and places `affect_level` into `DialogueState`.
- **`models/affect/` contains trained artifacts and version metadata only.** It is an output of
  `ml/affect/` and an input to the runtime adapter; it is not a Python package.
- **`datasets/affect/` contains manifests and acquisition/instructions only.** Raw RAVDESS/TESS
  corpora are external/local assets and are not committed to the repository.
- **`evidences/wp104/` contains acceptance evidence** such as the method note, metrics, and
  confusion matrix.

The concrete repository layout is therefore:

```text
ml/
└── affect/
    ├── __init__.py
    ├── dataset.py
    ├── label_mapping.py
    ├── features.py
    ├── model.py
    ├── train.py
    ├── evaluate.py
    └── artifacts.py

adapters/
└── affect/
    ├── __init__.py
    └── classifier_detector.py

datasets/
└── affect/
    └── manifests/

models/
└── affect/

evidences/
└── wp104/

tests/
├── unit/
│   ├── ml_affect/
│   └── adapters/
│       └── test_affect_adapter.py
└── integration/
    └── wp104/
```

### 0.2 Contract mapping to `techdocs/SPEC.md`

This specification does not replace or reinterpret the host specification. The following mapping is
the contract of record for WP-104:

| `techdocs/SPEC.md` requirement | WP-104 responsibility | Explicit boundary |
|---|---|---|
| **FR-H7** — every utterance produces exactly one of `{Low, Moderate, High}` and the affect branch runs in parallel on the same raw audio | WP-104 supplies a detector capable of returning exactly one allowed affect level for runtime audio | Runtime: `adapters/affect/`; orchestration remains `pipeline/nodes/affect.py` |
| **FR-H8 / §11.1** — Node 4 applies the deterministic R1–R5 policy using affect + deadline proximity | WP-104 supplies `affect_level` only; it does not implement or modify R1–R5 | Policy remains WP-103 |
| **§8.3 Decision Trace** — `affect_level` is required and limited to `{Low, Moderate, High}` | Runtime detector and node must preserve this 3-valued contract; no `None`/fourth value may be emitted | Runtime adapter + existing node |
| **§11.3 / NFR-3** — classifier deployment gate is macro-F1 ≥ 0.70 and is not a runtime tunable | ML evaluation reports the measured macro-F1; the result is not hidden or retried until it passes | Offline `ml/affect/evaluate.py` |
| **§12 / NFR-H1** — classifier/openSMILE contribution is currently unmeasured | WP-104 records its own affect-stage timing so WP-108 can consume it; WP-104 does not claim to close NFR-H1 | Runtime detector instrumentation |

The key consequence is that **the ML-development contract ends at a validated, versioned model
artifact plus evidence**. The runtime contract begins when `adapters/affect/classifier_detector.py`
loads that artifact.

### 0.3 ML-development contract

The offline ML side has the following explicit contracts:

**Input**

- RAVDESS: 1,440 clips, 24 speakers, used as the primary training/evaluation corpus.
- TESS: 2,800 clips, 2 speakers, used only as a held-out generalisation check.
- Each training/evaluation record must retain an audio path, source corpus, speaker identifier,
  source emotion label, and mapped `{Low, Moderate, High}` target label.
- Audio is normalized to 16 kHz mono before eGeMAPSv02 extraction, consistent with the host's fixed
  `audio_sample_rate_hz = 16000`.

**Label mapping**

RAVDESS:

```text
Neutral    -> Low
Calm       -> Low
Happy      -> Moderate
Sad        -> Moderate
Angry      -> High
Fearful    -> High
Disgust    -> High
Surprised  -> High
```

TESS:

```text
Neutral            -> Low
Happy              -> Moderate
Sad                -> Moderate
Pleasant Surprise  -> Moderate
Angry              -> High
Fear               -> High
Disgust             -> High
```

Every source label used by either corpus must appear exactly once within its corpus mapping and map to exactly one allowed level. The RAVDESS and TESS mappings are evaluated independently; identical emotion names across corpora are separate source labels.

**Label-mapping justification**

The three target levels are intended to represent increasing affective arousal / stress relevance rather than
a claim that the source corpora directly measure clinical stress. The mapping is therefore a modelling
choice made to create a reproducible three-class target for the WP-104 classifier. The rule is deliberately
simple, fixed before training, and applied identically to every clip of a given source label so that the
macro-F1 result cannot be changed retrospectively after seeing model performance.

- **Neutral -> Low.** Neutral speech is the lowest-arousal baseline available in both corpora and is the
  clearest anchor for the Low class.
- **Calm -> Low (RAVDESS).** Calm is explicitly the low-arousal counterpart to several higher-arousal
  RAVDESS emotions, so grouping it with Neutral preserves a coherent low-arousal class.
- **Happy -> Moderate.** Happiness is positively valenced but can carry substantial activation; it is therefore
  not treated as the low-arousal baseline and is placed in the middle class. This also avoids defining High
  solely as all non-neutral emotions.
- **Sad -> Moderate.** Sadness is negative in valence but generally does not imply the same acute high-arousal
  state represented by anger, fear, or disgust in this project's operational taxonomy.
- **Pleasant Surprise -> Moderate (TESS).** The explicit ``pleasant`` qualifier distinguishes this TESS label
  from an unqualified high-arousal surprise state. It is grouped with Happy and Sad as a non-baseline,
  non-high target.
- **Angry -> High.** Anger is treated as a high-arousal, negative-valence state and is therefore an anchor
  for the High class.
- **Fearful / Fear -> High.** Fear is treated as an acute high-arousal negative state and grouped with Anger.
- **Disgust -> High.** Disgust is treated as a strongly negative, high-arousal state within the project's
  three-level operational taxonomy.
- **Surprised -> High (RAVDESS).** RAVDESS uses the unqualified ``Surprised`` label. For this project it is
  treated as the ambiguous/high-arousal surprise category rather than conflated with TESS's explicitly
  positive ``Pleasant Surprise`` label. This preserves totality while keeping the two corpus-specific source
  labels distinguishable.

**Important limitation.** This mapping is a project-level operational taxonomy, not a literature-validated
psychological scale. The specification therefore requires the mapping to be frozen and documented before
training, and any resulting macro-F1 value must be interpreted as performance on this mapping rather than as
proof of stress detection in a clinical sense. The mapping's main defensibility requirement is reproducibility,
totality, and a stated rationale for every source label.

**Feature extraction**

```text
audio (16 kHz, mono)
    -> openSMILE eGeMAPSv02
    -> 88 floating-point features
```

The extraction is deterministic: the same input audio and settings must reproduce the same vector
within the tolerance specified by the acceptance criteria.

**Training**

The shipped classifier pipeline is:

```text
StandardScaler
    -> SVC(kernel="rbf", class_weight="balanced")
```

implemented as a single `sklearn.pipeline.Pipeline`. `MLPClassifier` is a comparison model only.

**Evaluation**

RAVDESS is evaluated using `GroupKFold`, with `speaker_id` supplied as the group vector. A speaker
must not appear on both sides of any fold. TESS is not pooled into this GroupKFold process; it is
scored separately as a held-out generalisation check.

**Outputs**

The ML-development side must produce:

- numeric macro-F1;
- per-class F1 for `Low`, `Moderate`, `High`;
- a 3×3 confusion matrix;
- a method note containing the corpus counts, label mapping, CV scheme, hyperparameters, seed,
  metrics, and the NFR-3 go/no-go result;
- a persisted fitted pipeline under `models/affect/` with a retrievable version identifier.

A macro-F1 below 0.70 is a valid measured result and must be reported honestly; it is not a reason
for changing the metric, leaking speakers across folds, or withholding the result.

### 0.4 Runtime detector contract

The runtime implementation must preserve the contract already used by WP-103:

```python
class ClassifierAffectDetector:
    def detect(self, audio: bytes, sample_rate: int) -> str:
        ...
```

The detector:

1. validates input before invoking the feature extractor;
2. uses the supplied sample rate rather than silently assuming one internally;
3. extracts eGeMAPSv02 features using the runtime-compatible implementation;
4. loads the versioned persisted pipeline from `models/affect/`;
5. returns exactly one of `"Low"`, `"Moderate"`, `"High"`;
6. reports affect-stage latency using the existing per-stage logging convention;
7. raises a named/defined error for invalid or unanalysable input rather than silently defaulting to
   an affect level.

`pipeline/nodes/affect.py` must not be modified to accommodate the classifier. The adapter is the
compatibility layer.

### 0.5 Explicit non-responsibilities

WP-104 does **not** own:

- Node 4's R1–R5 policy logic;
- deadline-proximity calculation;
- decision-trace schema design;
- STT, LLM, TTS, or wake-word behavior;
- the WP-103 `DevelopmentAffectDetector` scaffold behavior;
- a fabricated or predetermined affect result intended to make the policy choose a specific rule;
- the NFR-H1 overall host latency gate (WP-108 owns the latency budget);
- a runtime fallback classifier intended to conceal macro-F1 below 0.70.

---

## 1. User stories

- **As the AI/software lead (Almedejar), for G3 (today):** I need a working affect classification branch — trained, evaluated, and documented — so that DEL-02 can be marked accepted and the G3 exit condition ("the macro-F1 figure exists") is met, whatever that figure turns out to be.
- **As the AI/software lead, for the panel:** I need the macro-F1 result reported honestly, with the speaker-independent method stated, because RSK-05's mitigation is "report the method honestly," not "hit 0.70." A sub-threshold result is a legitimate finding, not a failure to deliver, provided the method is sound and documented.
- **As the same person, for WP-105/host integration:** I need the trained classifier wrapped behind the same `.detect(audio, sample_rate) -> str` contract the WP-103 stub already implements, so that swapping it into `composition/bootstrap.py` requires no change to `pipeline/nodes/affect.py` or to any code downstream of the affect node.
- **As a future panel member auditing the Policy-Consistency Audit (NFR-6):** I need every decision-trace row's `affect_level` to be one of exactly three values, always populated, traceable to a specific classifier version.
- **As the person maintaining the project schedule:** I need the deferred/at-risk items this package could not close (per-stage latency of the classifier, the exact scikit-learn version pin and the label-mapping defense) named explicitly, not silently dropped, so they can be picked up by name in W2–W4.

## 2. Acceptance criteria

Numbered; each has an observable pass/fail condition.

1. **Label mapping exists and is committed.** A document (`ml/affect/label_mapping.md` or equivalent) states the explicit mapping from RAVDESS's 8 emotion classes and TESS's 7 emotion classes onto the three stress levels `{Low, Moderate, High}`, with a one-line rationale per mapped class. *Pass:* the file exists, every source emotion label used by either corpus appears exactly once in the mapping, and every mapped-to value is one of the three allowed levels.
2. **Feature extraction runs and is deterministic.** A script (`ml/affect/extract_features.py` or equivalent) runs openSMILE eGeMAPS v02 over the prepared corpus and produces an 88-column feature table. *Pass:* running the script twice on the same audio file yields bit-identical (or floating-point-identical within `1e-9`) feature vectors.
3. **Training pipeline matches the fixed design.** The training script builds a `sklearn.pipeline.Pipeline` of exactly `StandardScaler` → `SVC(kernel="rbf", class_weight="balanced")`. A separate `MLPClassifier` run may be trained and reported only as the comparison required by `MLAlgo.md`; it is not the shipped default. *Pass:* inspecting the fitted pipeline's `named_steps` shows both stages in that order; no hand-written threshold rule is used as the classifier.
4. **Speaker-independent evaluation is used, not a random split.** Cross-validation is `GroupKFold` grouped by RAVDESS speaker ID, run over RAVDESS only; TESS is scored as a held-out generalisation check and never appears inside a `GroupKFold` fold with RAVDESS or with itself. *Pass:* the evaluation code path constructs `groups=` from speaker ID (not from `None`/row index), and the same speaker's samples never appear in both the train and test side of a fold — verifiable by asserting `set(train_speakers) & set(test_speakers) == set()` for every fold in a test.
5. **Macro-F1 is computed and reported, whatever its value.** `sklearn.metrics.f1_score(..., average="macro")` is computed over the GroupKFold predictions. *Pass:* a numeric macro-F1 value is produced and written into the method note (criterion 7) regardless of whether it clears 0.70 — a result below 0.70 is reported as a finding, not withheld or re-run until it passes.
6. **Per-class F1 and a confusion matrix are produced.** *Pass:* a confusion matrix (3×3, for `{Low, Moderate, High}`) and per-class F1 scores are saved as an artifact (image, CSV, or both) under `evidences/wp104/`.
7. **A method note exists.** *Pass:* a document under `evidences/wp104/` or `ml/affect/` states: corpora and clip counts used, the label mapping (or a link to criterion 1's file), the exact CV scheme (GroupKFold, k, grouping key), the classifier(s) and hyperparameters, the random seed, the macro-F1 and per-class F1 results, and the go/no-go outcome against the 0.70 threshold (NFR-3).
8. **The model is persisted and versioned.** The fitted `Pipeline` (scaler + classifier) is serialized with `joblib` under `models/affect/`, with a version string embedded in the filename or a sidecar metadata file. *Pass:* loading the artifact with `joblib.load(...)` reproduces the same predictions on a held-out sample as were reported in criterion 5/6, and the version string is retrievable programmatically.
9. **A production detector implements the existing contract, unchanged.** A class, `adapters/affect/classifier_detector.py::ClassifierAffectDetector` (per §0.1's structural decision — `adapters/affect.py` becomes the package `adapters/affect/`), implements `detect(self, audio, sample_rate: int) -> str`, internally running openSMILE feature extraction then the loaded joblib pipeline, and returning one of exactly `"Low"`, `"Moderate"`, `"High"`. *Pass:* `pipeline/nodes/affect.py` and `make_affect_node` are not modified; a test instantiates the new detector, passes it to `make_affect_node`, and confirms it returns a valid `DialogueState` update with no code change to that module.
10. **Wiring replaces the stub.** `composition/bootstrap.py` is updated to construct `ClassifierAffectDetector` (loading the persisted model) in place of `DevelopmentAffectDetector`, with the existing configuration boundary making the classifier the intended runtime backend once a valid artifact exists. If the artifact is missing/corrupt, the host must use the explicitly documented development fallback rather than silently substituting a fake production result. *Pass:* running the integration path with valid classifier wiring is no longer hardcoded to `"Low"`; the fallback remains identifiable in logs/config.
11. **Every existing WP-102/WP-103 test still passes unmodified.** *Pass:* `pytest tests/` run against the branch after WP-104's changes shows the same pass/fail status for every pre-existing test as before WP-104 (no pre-existing test file's assertions are altered to accommodate the new detector).
12. **New unit tests exist and pass**, split per §0.1: the label mapping is total and 3-valued (criterion 1), the feature vector shape/dtype contract (88 columns, floats), and model-artifact loading live in `tests/unit/ml_affect/`; that `ClassifierAffectDetector.detect(...)` always returns a value in `ALLOWED_AFFECT_LEVELS` for a battery of sample/edge-case inputs (criterion 15 below) lives in `tests/unit/adapters/test_affect_adapter.py`, alongside the sibling `test_llm_adapter.py` / `test_stt_adapter.py` / `test_tts_adapter.py`. *Pass:* both `pytest tests/unit/ml_affect/` and `pytest tests/unit/adapters/test_affect_adapter.py` exit 0.
13. **A new integration test exists and passes**, exercising the affect node inside the full graph (`pipeline/graph.py`) with the real detector on at least one real short audio clip, and asserting the resulting decision-trace row's `affect_level` field (§8.3 of `techdocs/SPEC.md`) is populated with a value from the allowed set. Location: `tests/integration/wp104/`. *Pass:* `pytest tests/integration/wp104/` exits 0.
14. **`requirements.txt`** **is updated** with pinned versions for `opensmile`, `scikit-learn`, and `joblib` (the latter typically ships with scikit-learn but is pinned explicitly per MLAlgo.md §6.4's "pin the exact scikit-learn version" instruction, extended here to joblib). *Pass:* `pip install -r requirements.txt --break-system-packages` succeeds in a clean environment and `import opensmile, sklearn, joblib` succeeds afterward.
15. **The detector degrades to a defined error, not a crash or silent default, on bad input.** Mirroring `DevelopmentAffectDetector`'s existing `ValueError` behaviour: `audio=None` or `sample_rate<=0` raises `ValueError` before openSMILE is invoked. Audio shorter than openSMILE's minimum analysable window is caught and raises a named exception (not a raw library traceback) rather than silently returning a default level. *Pass:* unit tests (criterion 12) exercise both cases and assert the specific exception type, not just "an exception was raised."
16. **Per-utterance classifier latency is measured and logged**, separate from and in addition to the openSMILE extraction step's own timing, so WP-108 (DEL-04, the latency budget) can slot this stage into the per-stage table without re-instrumenting it. *Pass:* a call to `ClassifierAffectDetector.detect(...)` in the integration test produces a logged duration figure (feature extraction and inference measured separately or as one combined "affect" stage — either satisfies this, but the choice must be stated in the method note per criterion 7).
17. **Deferred/at-risk items are named, not silently dropped.** The method note (criterion 7) explicitly lists: whether SVC or MLPClassifier is selected as the shipped default and why; the exact scikit-learn version pinned; and, if macro-F1 falls below 0.70, what the honest scope-down statement to the panel is (per RSK-05's mitigation and MLAlgo.md's defence framing) rather than leaving that decision implicit.

## 2.1 Implementation contract checklist

The implementation is conformant only when these boundaries remain intact:

```text
RAVDESS/TESS
    -> ml/affect/
       -> eGeMAPSv02
       -> StandardScaler
       -> SVC(RBF, balanced)
       -> GroupKFold + macro-F1 evidence
       -> models/affect/*.joblib
                         |
                         v
              adapters/affect/classifier_detector.py
                         |
                         v
                pipeline/nodes/affect.py
                         |
                         v
                    DialogueState
```

No runtime pipeline module should import `ml.affect.train`, `ml.affect.evaluate`, or any training-only
module. Runtime code consumes the persisted artifact through the adapter boundary.


## 3. Assumptions

Every one of these is a choice made here rather than asked about; each is cheap to revisit.

1. **Corpora are already available locally** (RAVDESS and TESS audio files), or their
   acquisition is a prerequisite step outside WP-104's own critical path timing (downloading
   public research corpora is not itself a scheduling risk worth flagging). `datasets/affect/`
   holds manifests/instructions, not the raw audio, per the existing scaffold README.
2. **Label mapping (8+7 emotions → 3 levels) — decided by Almedejar, superseding the earlier
   placeholder in this document.** Two candidate mappings were compared:
   - **Groupmate's mapping:** Low = {neutral, calm}; Moderate = {sad, happy, pleasant surprise, surprise}; High = {disgust, fear, surprised, angry}. **This mapping is internally inconsistent as stated** — a surprise-type label appears in both Moderate ("surprise") and High ("surprised"), with no stated rule for which corpus/wording goes where. As written it cannot satisfy criterion 1 ("every source emotion label... appears exactly once").
   - **Almedejar's mapping (adopted):** RAVDESS — Neutral→Low, Calm→Low, Happy→Moderate, Sad→Moderate, Angry→High, Fearful→High, Disgust→High, Surprised→High. TESS — Neutral→Low, Happy→Moderate, Sad→Moderate, Pleasant Surprise→Moderate, Angry→High, Fear→High, Disgust→High.
   This is the mapping this specification now assumes throughout. It resolves the groupmate's
   inconsistency by treating RAVDESS's unqualified "Surprised" and TESS's "Pleasant Surprise"
   as genuinely different labels rather than the same label spelled two ways: the "pleasant"
   qualifier in TESS signals positive valence, warranting Moderate, while RAVDESS's
   unqualified "Surprised" is treated as ambiguous/negative-leaning arousal and grouped with
   the other high-arousal, non-positive labels at High. Each corpus's full label set is covered
   exactly once (RAVDESS: 8 labels; TESS: 7 labels), satisfying criterion 1's totality
   requirement. **The one-line rationale per class that criterion 1 requires should state this
   Surprised-vs-Pleasant-Surprise distinction explicitly**, since it is the one place this
   mapping departs from treating corpora symmetrically and is the most likely point a panelist
   probes.
3. **SVC is the shipped default**, with MLPClassifier trained and reported for comparison only
   (per MLAlgo.md, both satisfy the written design; this assumes SVC ships since it is
   named first and is the lower-variance choice for \~1,440 samples).
4. **scikit-learn version**: pin to the latest stable release available on PyPI at
   implementation time (not fixed to a specific number here, since "confirm SVC vs MLP
   empirically" and "record the version" are both explicitly marked non-blocking in
   MLAlgo.md §9). Whatever version is pinned must be recorded per criterion 7/17.
5. **Random seed**: `random_state=42` fixed throughout (data split, SVC, MLPClassifier) for
   reproducibility, recorded in the method note.
6. **openSMILE invocation is via the** **`opensmile`** **Python package** (per MLAlgo.md §3's
   "practical note"), not a raw subprocess call to the SMILExtract binary.
7. **Audio sample rate**: eGeMAPS extraction assumes 16 kHz mono input, consistent with
   `config/settings.py`'s `audio_sample_rate_hz = 16000` and with RAVDESS/TESS's native
   sampling. Any corpus clips at a different native rate are resampled to 16 kHz mono before
   feature extraction, and this resampling step is documented in the method note.
8. **The config flag gating real vs. stub detector** (criterion 10) is a simple boolean/enum
   in `config/settings.py` (e.g. `affect_detector_backend: "development" | "classifier"`),
   defaulting to `"classifier"` once the model artifact exists, falling back to
   `"development"` only if no artifact is found at startup (fail-soft, logged loudly — not a
   silent fallback).
9. **This specification does not include shipping a fallback for macro-F1 < 0.70** beyond
   "report it honestly" (RSK-05's stated mitigation). No separate contingency classifier or
   rule-based fallback is scoped here; if the figure is below 0.70, WP-104 still ships the
   measured classifier (it is still the best available), and the scope-down conversation
   happens at the panel/defense level per Appendix A of the roadmap, not as new code in this
   package.
10. **Latency instrumentation format** (criterion 16) reuses whatever per-stage logging
    convention WP-102/WP-103 already established for other nodes, rather than introducing a
    new logging mechanism.

## 4. Edge cases

1. **Silence or near-silence input** — openSMILE may produce degenerate or NaN features (e.g. undefined F0/jitter with no voiced signal). The detector must not pass NaNs into the classifier silently; this is handled as a named error path (criterion 15) or, if scikit-learn's imputation is used, that choice is stated in the method note.
2. **Audio shorter than eGeMAPS's minimum frame window** — must raise a named exception, not crash with a raw shape-mismatch error from openSMILE or scikit-learn.
3. **A speaker with very few clips** landing entirely in one GroupKFold fold, producing a fold with zero support for a class — `f1_score` will emit a zero/undefined-metric warning for that class in that fold; this must be handled (e.g. `zero_division=0`) and reported transparently rather than crashing the evaluation run.
4. **TESS accidentally leaking into a RAVDESS GroupKFold split** — guarded by criterion 4's explicit assertion that RAVDESS and TESS speaker ID sets never overlap across the train/test boundary of any fold (they cannot overlap on person, but the code must not accidentally pool both corpora into one GroupKFold call, which would silently violate the RAVDESS-only evaluation design in MLAlgo.md §6.2).
5. **Model artifact missing or corrupted at host startup** — `composition/bootstrap.py`'s wiring (criterion 10) must fail loudly and fall back to `DevelopmentAffectDetector` rather than crash the whole host process, per assumption 8, since a broken affect branch should not take down Nodes 1–3.
6. **scikit-learn version mismatch between training and inference environments** — flagged explicitly in MLAlgo.md §6.4 as an "unrecoverable data-collection loss" risk; criterion 14's pin is the mitigation, not a nice-to-have.
7. **Non-16kHz or stereo input reaching the detector** (e.g. a future hardware path that changes capture settings) — the detector's `sample_rate` parameter must be honored/checked, not hardcoded to 16000 internally, so a mismatch is caught rather than silently mis-analysed.

## 5. Risks

| # Risk Severity Note  |                                                                                                                                                     |            |                                                                                                                                                                                                                                                                        |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1                     | Macro-F1 lands below 0.70                                                                                                                           | High       | This is RSK-05 verbatim. Per the roadmap this is a legitimate, expected-possible outcome, not a specification failure — but it is the single largest content risk in this package, and the panel-facing framing (criterion 17) must be ready regardless of the number. |
| 2                     | The label-mapping decision (assumption 2) is contested at defense as arbitrary                                                                      | Medium     | Mitigated by requiring a written one-line rationale per class (criterion 1), but the underlying mapping is a genuine design judgment call with no literature-derived answer cited in MLAlgo.md.                                                                        |
| 3                     | Corpus acquisition (RAVDESS/TESS download, licensing, local storage) takes longer than expected                                                     | Medium     | Sits outside WP-104's own coding critical path but blocks everything downstream if not already done; not tracked elsewhere in the roadmap by name.                                                                                                                     |
| 4                     | Given today is the G3 date, there may be no remaining schedule slack to redo training if the first mapping/split choice produces an unusable result | High       | Time-sensitive: this package's gate is not in the future, it is now, per §0.                                                                                                                                                                                           |
| 5                     | New dependencies (`opensmile`) may have platform-specific install friction (it wraps a native binary) on the team's Windows 11 host                 | Medium     | `techdocs/SPEC.md` records Host OS as Windows 11; openSMILE's Python wrapper bundling is generally fine on Windows but is unverified in this repository as of this specification.                                                                                      |
| 6                     | Latency contribution of openSMILE + classifier is currently unmeasured and NFR-H1 is already "at risk" per `techdocs/SPEC.md` §12                   | Low–Medium | WP-104 is not responsible for closing NFR-H1, but criterion 16 exists so this package does not make that gap invisible to WP-108.                                                                                                                                      |

## 6. Dependencies

- **External packages not yet in** **`requirements.txt`****:** `opensmile`, `scikit-learn`, `joblib` (see criterion 14).
- **Corpora:** RAVDESS and TESS audio files, obtained and locally available (see assumption 1 and risk 3) — not currently present in this repository's tree as inspected.
- **Existing code this package builds on, unmodified:** `pipeline/nodes/affect.py` (`make_affect_node`, `ALLOWED_AFFECT_LEVELS`), `pipeline/state.py` (`DialogueState`), `config/settings.py` (`audio_sample_rate_hz`), and the WP-103 `DevelopmentAffectDetector` contract shape it must match.
- **Existing decision documents this package must not contradict:** `techdocs/MLAlgo.md` (algorithm/library choice, already decided), `techdocs/roadmap.md` (schedule, gate, and acceptance criteria of record), `techdocs/SPEC.md` §5 (FR-H7/FR-H8), §8.3 (decision-trace schema), §11.3 (NFR-3 gate value), §12 (NFR-H1 latency status).
- **Downstream consumers depending on this package's output:** WP-105 (transport/logging, needs the affect stage's latency figure), WP-108 (DEL-04 latency budget), Node 4's policy table (already implemented in WP-103, consumes `affect_level` at runtime), the Policy-Consistency Audit (NFR-6, consumes `affect_level` from every decision-trace row).
- **Branch state:** `feature/wp-104` already exists locally with the scaffold described in §0 merged forward from `main` as of commit `297cd6d`. This specification assumes work continues on that branch (or an equivalent rebased branch), not from a clean scaffold.

## 7. Self-critique

- **The label-mapping decision (§0.3) is still the weakest-verified part of this specification**, even now that it is a decided mapping rather than a placeholder. MLAlgo.md calls this decision blocking and says it "needs to be written down explicitly and defended... before training, not after seeing results." A different mapping could plausibly move the macro-F1 result across the 0.70 threshold, meaning this one decision has an outsized effect on the number the whole package is judged by. The adopted mapping's Surprised/Pleasant-Surprise asymmetry is a defensible, stated rationale, but it is a judgment call with no literature citation behind it in MLAlgo.md — this specification records the decision and its rationale; it cannot verify the mapping is *correct*, only that it is total, unambiguous, and documented, which the groupmate's version was not.
- **This specification does not fix the exact go/no-go behavior if macro-F1 fails.** Assumption 9 deliberately keeps this out of scope as new code, but that is a judgment call: the roadmap language ("the affect claims scope down") implies some panel-facing or manuscript-facing change is expected, which is not a coding deliverable this spec covers. If that scope-down needs a code-visible flag (e.g. a "confidence disclaimer" attached to Node 4's output when the classifier is below threshold), that would need to be re-specified — it is not covered here.
- **Given §0's note that G3 is today**, a specification this size (17 acceptance criteria) may itself be a poor fit for the time actually available. This document does not attempt to triage a reduced "must-ship-today" subset versus a "can slip to W2 without endangering G3's actual exit condition" subset — the roadmap's own G3 exit condition is narrower ("Half A demonstrable end to end, and the macro-F1 figure known") than DEL-02's full acceptance criteria. A defensible reduced scope for *today specifically* would be criteria 1–8 plus 17 (the ML result and its honest write-up) with criteria 9–14, 16 (production wiring, dependency pinning, latency instrumentation) treated as immediately-following, not same-day. This specification does not make that split for the reader; it should be asked about explicitly if the time constraint is as tight as §0 suggests.
- **This specification is an acceptance contract, not training evidence.** No training run, openSMILE invocation, or scikit-learn fit is claimed by this document. The implementation phase must produce those artifacts and the measured macro-F1; this document defines what counts as conformant evidence.