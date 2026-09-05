"""Fixed WP-104 corpus-to-affect mapping.

The mapping is deliberately data-driven and immutable at runtime so evaluation
cannot silently change labels after seeing model performance.
"""

from __future__ import annotations

ALLOWED_LEVELS = ("Low", "Moderate", "High")

RAVDESS_LABEL_MAP: dict[str, str] = {
    "neutral": "Low",
    "calm": "Low",
    "happy": "Moderate",
    "sad": "Moderate",
    "angry": "High",
    "fearful": "High",
    "disgust": "High",
    "surprised": "High",
}

TESS_LABEL_MAP: dict[str, str] = {
    "neutral": "Low",
    "happy": "Moderate",
    "sad": "Moderate",
    "pleasant surprise": "Moderate",
    "angry": "High",
    "fear": "High",
    "disgust": "High",
}


def map_label(corpus: str, source_label: str) -> str:
    """Map a source emotion label to the fixed three-level affect taxonomy."""
    normalized_corpus = corpus.strip().lower()
    normalized_label = " ".join(source_label.strip().lower().split())
    mapping = {
        "ravdess": RAVDESS_LABEL_MAP,
        "tess": TESS_LABEL_MAP,
    }.get(normalized_corpus)
    if mapping is None:
        raise ValueError(f"Unsupported affect corpus: {corpus!r}")
    try:
        return mapping[normalized_label]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported {normalized_corpus.upper()} source label: {source_label!r}"
        ) from exc


def validate_mappings() -> None:
    """Validate that all configured source emotion labels map to allowed affect levels."""
    for corpus, mapping in (("RAVDESS", RAVDESS_LABEL_MAP), ("TESS", TESS_LABEL_MAP)):
        if len(mapping) != len(set(mapping)):
            raise AssertionError(f"Duplicate source labels in {corpus} mapping")
        invalid = set(mapping.values()) - set(ALLOWED_LEVELS)
        if invalid:
            raise AssertionError(f"Invalid target levels in {corpus}: {sorted(invalid)}")


validate_mappings()
