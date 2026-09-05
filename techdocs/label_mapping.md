# WP-104 Affect Label Mapping

The classifier target taxonomy is fixed to `Low`, `Moderate`, and `High`. The mapping is an
operational modelling choice for this project; it is **not** a clinical stress label.

| Corpus | Source emotion | Target | Rationale |
|---|---|---|---|
| RAVDESS | Neutral | Low | Lowest-arousal baseline in the corpus. |
| RAVDESS | Calm | Low | Explicit low-arousal counterpart to higher-arousal emotions. |
| RAVDESS | Happy | Moderate | Non-baseline emotion with potentially substantial activation. |
| RAVDESS | Sad | Moderate | Negative valence without being treated as an acute high-arousal anchor. |
| RAVDESS | Angry | High | High-arousal negative state used as a High anchor. |
| RAVDESS | Fearful | High | Acute high-arousal negative state. |
| RAVDESS | Disgust | High | High-arousal negative state in the operational taxonomy. |
| RAVDESS | Surprised | High | Treated as an unqualified high-arousal state; distinct from TESS `pleasant surprise`. |
| TESS | Neutral | Low | Lowest-arousal baseline in the corpus. |
| TESS | Happy | Moderate | Non-baseline activation placed in the middle class. |
| TESS | Sad | Moderate | Negative valence without the acute high-arousal grouping used for High. |
| TESS | Pleasant Surprise | Moderate | Positive/pleasant qualifier distinguishes it from the RAVDESS `Surprised` label. |
| TESS | Angry | High | High-arousal negative state. |
| TESS | Fear | High | Acute high-arousal negative state. |
| TESS | Disgust | High | High-arousal negative state. |

RAVDESS is the primary speaker-independent training/evaluation corpus. TESS is held out for
external/generalisation checking and must never be folded into RAVDESS `GroupKFold` evaluation.
