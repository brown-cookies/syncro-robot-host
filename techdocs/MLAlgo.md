# SYNCRO — ML Algorithm and Library Decision (Affect Branch)

**Subject:** What is actually machine learning in the affect branch, which library performs it, and why
**Status:** Decision document. Written 16 August 2026.
**Supersedes nothing.** Specifies the `openSMILE eGeMAPS 88-dim -> shallow SVM/MLP -> 3 stress levels`
line in `archive/SYNCRO-panel-additions-feasibility.md` §2, `archive/SYNCRO-defense-script-v2.md` and Figures 1, 2 and 5.

---

## 1. The question this document answers

The proposal names the affect branch as `eGeMAPS -> SVM/MLP -> three levels`. That phrase compresses
two very different kinds of computation into one arrow, which produces a recurring confusion:

> *Do we need a machine-learning algorithm to compute jitter, shimmer and loudness?*

**No.** Jitter and loudness are measurements, not predictions. Nothing about them is learned. The
machine learning in SYNCRO begins only after those measurements exist, when the 88 numbers must be
mapped onto a stress level.

This document draws that line precisely, because getting it wrong in either direction is costly. If
the team believes feature extraction needs ML, it will reach for a training framework it does not
need. If the team believes the classifier is "just a formula", it will skip the validation that the
macro-F1 go/no-go criterion depends on.

---

## 2. The two stages are different kinds of computation

```
raw audio  ->  [ Stage 1: openSMILE ]  ->  88 floats  ->  [ Stage 2: scikit-learn ]  ->  3 levels
                  deterministic DSP                            trained classifier
                     NOT machine learning                        IS machine learning
```

| | Stage 1 — feature extraction | Stage 2 — classification |
|:--|:--|:--|
| Tool | openSMILE (eGeMAPS v02) | scikit-learn |
| Kind | Deterministic signal processing | Supervised learning |
| Trained? | No | Yes |
| Reproducible? | Bit-identical on the same waveform | Depends on the fitted model + random seed |
| Answers | *What does the voice sound like?* | *Does that sound like stress?* |
| Hardware | CPU only, 0 GB VRAM | CPU only, 0 GB VRAM |

The single sentence that resolves the confusion: **openSMILE measures, scikit-learn decides.**

---

## 3. Stage 1 — openSMILE, and why no ML is involved

eGeMAPS (extended Geneva Minimalistic Acoustic Parameter Set) is a fixed, published list of 88
acoustic descriptors. Each one is a closed-form computation over the waveform:

| Feature | How it is computed | Learned? |
|:--|:--|:--|
| F0 (pitch) | Autocorrelation / cepstral peak picking per frame | No |
| Jitter | Mean absolute deviation between consecutive F0 period lengths | No |
| Shimmer | The same measure applied to peak amplitude instead of period | No |
| Loudness | RMS energy mapped to an auditory (sone) scale | No |
| HNR | Ratio of harmonic to noise energy in the spectrum | No |
| Spectral slope, alpha ratio, Hammarberg index | FFT band-energy ratios | No |
| MFCC 1–4 | Discrete cosine transform of the log mel spectrum | No |

Run the same audio file through openSMILE twice and the 88 values are identical. There is no model
file, no training set, no random seed. **Training a model to produce jitter would be an error, not
an upgrade** — it would introduce estimation variance into a quantity that can be computed exactly.

This is also why eGeMAPS is the right feature set for a project with no GPU headroom: it was designed
specifically so that prosodic affect work does not require a large learned speech encoder.

**Practical note.** The `opensmile` Python package wraps the C++ binary and returns a pandas
DataFrame of the 88 features. It feeds scikit-learn directly with no glue code.

---

## 4. Stage 2 — scikit-learn, and why it is required

The 88-dim vector is meaningless until something maps it to a stress level. That mapping cannot be
derived from first principles — there is no equation from jitter to stress — so it must be learned
from labelled data. **This is the machine learning in SYNCRO, and it is the only machine learning in
SYNCRO outside the LLM itself.**

```python
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC                    # or sklearn.neural_network.MLPClassifier

clf = Pipeline([
    ("scale", StandardScaler()),               # eGeMAPS dims differ by orders of magnitude
    ("svm",   SVC(kernel="rbf", class_weight="balanced")),
])
```

`StandardScaler` is not optional. eGeMAPS mixes Hz, dB, dimensionless ratios and percentages; an RBF
kernel on unscaled inputs is dominated by whichever dimension happens to have the largest numeric
range.

`MLPClassifier` is the "MLP" named in the proposal figures. At 88 inputs and 3 classes, scikit-learn's
implementation is the correct size for the job — see §5.

**Dropping scikit-learn is not an option that preserves the design.** Without it there is no stress
level, therefore no Node 4 override, therefore no primary thesis contribution.

### 4.1 The rejected alternative: hand-written thresholds

A rule table over raw feature values (`if jitter > x and loudness > y: stressed`) needs no library and
no training. It should not be used:

- There is nothing to cross-validate, so the **macro-F1 >= 0.70 go/no-go criterion becomes
  unmeasurable** — the criterion is the branch's entire empirical defence.
- It contradicts "shallow SVM/MLP" in Figures 1, 2 and 5, the extension-point map, and the defense
  script.
- A panelist reads hand-tuned thresholds as an admission that the affect branch is decorative.

---

## 5. Library decision: scikit-learn, not PyTorch

| Criterion | scikit-learn | PyTorch | Winner |
|:--|:--|:--|:--|
| Fit for ~4k samples x 88 features | Designed for this regime | Overfits before it beats an RBF SVM | sklearn |
| Install footprint | ~30 MB | 2–3 GB, pulls CUDA runtime | sklearn |
| VRAM cost | 0 GB, CPU by construction | Contends with Ollama unless forced to CPU | sklearn |
| Inference latency | Microseconds on 88 floats | Import and tensor overhead for no gain | sklearn |
| Already in the written design | Yes ("shallow SVM/MLP") | No — six figures and docs would need editing | sklearn |
| Other stack components needing it | — | None | sklearn |

**The VRAM argument is decisive on its own.** `decisions/syncro-costestimate-15k-revision1.md` §3.1 budgets 6.5–7.4 GB of
8 GB with openSMILE at 0 GB, leaving 0.6–1.5 GB of margin. scikit-learn keeps that row at zero.

**The dependency argument is close behind.** faster-whisper runs on CTranslate2, Piper on onnxruntime,
Ollama on llama.cpp. **None of the existing stack needs PyTorch.** Adding it for a 3-class classifier
would introduce the project's single heaviest dependency to serve its single lightest component.

### 5.1 The one case where PyTorch would be correct

Only if eGeMAPS were abandoned entirely and a speech encoder — wav2vec2, HuBERT, WavLM — were
fine-tuned end-to-end on raw audio. `archive/SYNCRO-mock-panel-QA.md` D4 already rejects that path on two
grounds: no training data for a Filipino cohort, and GPU contention with the 7–8B model on the same
host. Since that path is closed, PyTorch has no role.

---

## 6. Training and evaluation plan

### 6.1 Data and label mapping

| Corpus | Clips | Speakers | Emotion classes |
|:--|---:|---:|---:|
| RAVDESS (speech) | 1,440 | 24 (12 M / 12 F) | 8 |
| TESS | 2,800 | **2** | 7 |

**The 8-and-7 emotion labels must be collapsed to 3 stress levels, and that mapping is a design
decision the proposal has not yet recorded.** It needs to be written down explicitly and defended,
because it determines the class balance and therefore the achievable macro-F1. Fix it before training,
not after seeing results.

### 6.2 Speaker-independent splits — mandatory

Use `GroupKFold` grouped by speaker ID, never a plain stratified or random split.

Both corpora have few speakers with many clips each. A random split places the same speaker on both
sides of the fold, and the classifier scores well by recognising voices rather than stress. That
inflation lands directly on the macro-F1 >= 0.70 criterion, which is the one number the branch is
judged by.

**TESS carries a specific risk: it has only two speakers.** Speaker-independent cross-validation is
not meaningful within TESS alone. The workable arrangement is to run GroupKFold over RAVDESS's 24
speakers and treat TESS as a held-out generalisation check rather than folding it into training. A
TESS-heavy training set will learn two voices.

### 6.3 Metric and go/no-go

- Primary metric: `f1_score(y_true, y_pred, average="macro")`.
- Criterion: **macro-F1 >= 0.70** or the affect claims scope down, per the defense script.
- Macro-averaging is the right choice given the label collapse in §6.1 will produce imbalanced
  classes; pair it with `class_weight="balanced"` at fit time.
- Report the per-class F1 alongside the macro figure. `archive/SYNCRO-mock-panel-QA.md` D-block commits to
  "defensible per-class F1", so the per-class breakdown must exist.

### 6.4 Persistence and versioning

- Persist with `joblib`; the fitted `Pipeline` carries the scaler, so the scaler is never re-fitted
  at inference.
- Stamp a classifier version string into the artifact. Figure 5's decision trace already records
  `stress level - classifier version`, so the trace has a field expecting it.
- **Pin the exact scikit-learn version in requirements.** Pickled estimators do not reliably load
  across minor versions, and an unloadable model mid-study is an unrecoverable data-collection loss.

---

## 7. Dependency footprint

```
opensmile        # eGeMAPS v02 extraction, CPU
scikit-learn     # SVC / MLPClassifier, StandardScaler, GroupKFold, macro-F1
joblib           # ships with scikit-learn; model persistence
```

Approximately 30 MB beyond openSMILE, CPU-only, zero GPU contention. This is the complete affect
stack. It does not change the software-stack row in `decisions/syncro-costestimate-15k-revision1.md` §2.1 in cost terms —
everything here is open source and free.

---

## 8. Panel defence notes

**"Why scikit-learn — isn't that too simple?"** The answer is already in D4: eGeMAPS exists precisely
so that a shallow classifier suffices. The stronger framing is that ML is spent only where the mapping
is genuinely unknown. Jitter is a measurement, so learning it would add error; stress from jitter is
unknown, so it is learned.

**"You already have a GPU — why not fine-tune a speech model?"** §5.1. Note that the absence of
PyTorch from the requirements file makes this a deliberate architectural choice rather than a
convenience, and it is easier to defend for exactly that reason.

**"Acted emotion, real workplace stress."** Unchanged from the existing D1 answer — this document does
not address the acted-versus-naturalistic validity gap, which remains the branch's principal
limitation and is handled in `archive/SYNCRO-mock-panel-QA.md`.

---

## 9. Open items

| # | Item | Owner | Blocking? |
|---:|:--|:--|:--|
| 1 | Write down the 8/7-emotion -> 3-stress-level mapping explicitly (§6.1) | Team | Yes — blocks training |
| 2 | Decide RAVDESS-train / TESS-holdout split versus pooling (§6.2) | Team | Yes — blocks the F1 figure |
| 3 | Confirm SVC versus MLPClassifier empirically; report both | Team | No — either satisfies the written design |
| 4 | Record the chosen scikit-learn version once training begins (§6.4) | Team | No, but do it before deployment |
