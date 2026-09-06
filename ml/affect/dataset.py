"""Dataset manifest loading and contract validation for WP-104."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import csv
from pathlib import Path
from typing import Iterable, Sequence

from .label_mapping import (
    ALLOWED_LEVELS,
    RAVDESS_LABEL_MAP,
    TESS_LABEL_MAP,
    map_label,
)

MANIFEST_COLUMNS = (
    "audio_path",
    "corpus",
    "speaker_id",
    "source_label",
    "target_label",
)
EXPECTED_COUNTS = {
    "ravdess": {"records": 1440, "speakers": 24, "source_labels": 8},
    "tess": {"records": 2800, "speakers": 2, "source_labels": 7},
}
EXPECTED_SOURCE_LABELS = {
    "ravdess": frozenset(RAVDESS_LABEL_MAP),
    "tess": frozenset(TESS_LABEL_MAP),
}


@dataclass(frozen=True, slots=True)
class AffectRecord:
    """Represent one canonical corpus record used by the WP-104 ML pipeline."""

    audio_path: Path
    corpus: str
    speaker_id: str
    source_label: str
    target_label: str


@dataclass(frozen=True, slots=True)
class ManifestVerification:
    """Capture the contract checks performed against one corpus manifest."""

    corpus: str
    record_count: int
    speaker_count: int
    source_label_count: int
    target_label_counts: dict[str, int]


def load_manifest(path: str | Path) -> list[AffectRecord]:
    """Load a canonical affect dataset manifest and validate its row-level contract."""
    manifest_path = Path(path)
    records: list[AffectRecord] = []
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_manifest_columns(reader.fieldnames, manifest_path)
        for row_number, row in enumerate(reader, start=2):
            _validate_manifest_row(row, row_number, manifest_path)
            records.append(
                AffectRecord(
                    audio_path=Path(row["audio_path"]),
                    corpus=row["corpus"].strip().lower(),
                    speaker_id=row["speaker_id"].strip(),
                    source_label=_normalise_source_label(row["source_label"]),
                    target_label=row["target_label"].strip(),
                )
            )
    return records


def verify_manifest(
    path: str | Path,
    *,
    expected_corpus: str,
    require_audio_files: bool = False,
    audio_root: str | Path | None = None,
) -> ManifestVerification:
    """Verify that a corpus manifest satisfies the fixed WP-104 dataset contract."""
    corpus = expected_corpus.strip().lower()
    if corpus not in EXPECTED_COUNTS:
        raise ValueError(
            f"Unsupported corpus for verification: {expected_corpus!r}")

    records = load_manifest(path)
    expected = EXPECTED_COUNTS[corpus]

    if not records:
        raise ValueError(f"{corpus.upper()} manifest is empty")

    corpora = {record.corpus for record in records}
    if corpora != {corpus}:
        raise ValueError(
            f"{corpus.upper()} manifest contains unexpected corpora: {sorted(corpora)}"
        )

    source_labels = {record.source_label for record in records}
    expected_labels = EXPECTED_SOURCE_LABELS[corpus]
    if source_labels != expected_labels:
        missing = sorted(expected_labels - source_labels)
        unexpected = sorted(source_labels - expected_labels)
        raise ValueError(
            f"{corpus.upper()} source-label set mismatch; missing={missing}, unexpected={unexpected}"
        )

    if len(records) != expected["records"]:
        raise ValueError(
            f"{corpus.upper()} record count mismatch: expected {expected['records']}, got {len(records)}"
        )

    speakers = {record.speaker_id for record in records}
    if len(speakers) != expected["speakers"]:
        raise ValueError(
            f"{corpus.upper()} speaker count mismatch: expected {expected['speakers']}, got {len(speakers)}"
        )

    if len(source_labels) != expected["source_labels"]:
        raise AssertionError(
            "Source-label count does not match the fixed contract")

    paths = [record.audio_path.as_posix() for record in records]
    duplicates = _duplicates(paths)
    if duplicates:
        raise ValueError(
            f"{corpus.upper()} manifest contains duplicate audio paths: {duplicates[:5]}")

    if require_audio_files:
        if audio_root is None:
            raise ValueError(
                "audio_root is required when require_audio_files=True")
        _verify_audio_files(records, Path(audio_root))

    target_counts = Counter(record.target_label for record in records)
    if set(target_counts) - set(ALLOWED_LEVELS):
        raise ValueError(
            f"{corpus.upper()} manifest contains invalid target levels: {sorted(set(target_counts) - set(ALLOWED_LEVELS))}"
        )

    return ManifestVerification(
        corpus=corpus,
        record_count=len(records),
        speaker_count=len(speakers),
        source_label_count=len(source_labels),
        target_label_counts={label: target_counts.get(
            label, 0) for label in ALLOWED_LEVELS},
    )


def write_manifest(records: Iterable[AffectRecord], path: str | Path) -> None:
    """Write canonical affect dataset records using the fixed manifest schema."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MANIFEST_COLUMNS))
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "audio_path": str(record.audio_path),
                    "corpus": record.corpus,
                    "speaker_id": record.speaker_id,
                    "source_label": record.source_label,
                    "target_label": record.target_label,
                }
            )


def _validate_manifest_columns(fieldnames: Sequence[str] | None, path: Path) -> None:
    """Ensure a manifest exposes exactly the columns defined by the WP-104 contract."""
    if fieldnames is None:
        raise ValueError(f"Manifest has no header: {path}")
    actual = tuple(fieldnames)
    missing = sorted(set(MANIFEST_COLUMNS) - set(actual))
    extra = sorted(set(actual) - set(MANIFEST_COLUMNS))
    if actual != MANIFEST_COLUMNS or missing or extra:
        raise ValueError(
            f"Manifest columns mismatch for {path}: expected {list(MANIFEST_COLUMNS)}, got {fieldnames}"
        )


def _validate_manifest_row(row: dict[str, str], row_number: int, path: Path) -> None:
    """Validate required values and fixed label mappings for one manifest row."""
    for column in MANIFEST_COLUMNS:
        if not row.get(column, "").strip():
            raise ValueError(
                f"Manifest row {row_number} has an empty {column!r}: {path}")

    corpus = row["corpus"].strip().lower()
    if corpus not in EXPECTED_COUNTS:
        raise ValueError(
            f"Unsupported corpus {row['corpus']!r} at row {row_number}")

    source_label = _normalise_source_label(row["source_label"])
    expected = map_label(corpus, source_label)
    if row["target_label"].strip() != expected:
        raise ValueError(
            f"Manifest label mismatch at row {row_number}: expected {expected!r}, got {row['target_label']!r}"
        )

    if Path(row["audio_path"]).is_absolute():
        raise ValueError(
            f"Manifest audio_path must be relative at row {row_number}")

    if Path(row["audio_path"]).suffix.lower() != ".wav":
        raise ValueError(
            f"Manifest audio_path must reference a WAV file at row {row_number}")


def _normalise_source_label(source_label: str) -> str:
    """Normalize source emotion spelling without changing the fixed corpus mapping."""
    return " ".join(source_label.strip().lower().split())


def _duplicates(values: Iterable[str]) -> list[str]:
    """Find repeated manifest values while preserving the first repeated occurrences."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _verify_audio_files(records: Iterable[AffectRecord], audio_root: Path) -> None:
    """Confirm that every manifest path resolves to a local WAV file when requested."""
    missing = [str(audio_root / record.audio_path)
               for record in records if not (audio_root / record.audio_path).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Manifest references {len(missing)} missing audio files; first examples: {missing[:5]}"
        )
