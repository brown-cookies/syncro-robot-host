"""Dataset manifests and lightweight validation for WP-104 affect corpora."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv

from .label_mapping import map_label


@dataclass(frozen=True, slots=True)
class AffectRecord:
    audio_path: Path
    corpus: str
    speaker_id: str
    source_label: str
    target_label: str


def load_manifest(path: str | Path) -> list[AffectRecord]:
    """Load a canonical affect dataset manifest and validate its required columns."""
    manifest_path = Path(path)
    required = {"audio_path", "corpus", "speaker_id", "source_label", "target_label"}
    records: list[AffectRecord] = []
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise ValueError(f"Manifest missing required columns: {missing}")
        for row in reader:
            expected = map_label(row["corpus"], row["source_label"])
            if row["target_label"] != expected:
                raise ValueError(
                    f"Manifest label mismatch for {row['audio_path']!r}: "
                    f"expected {expected!r}, got {row['target_label']!r}"
                )
            records.append(
                AffectRecord(
                    audio_path=Path(row["audio_path"]),
                    corpus=row["corpus"],
                    speaker_id=row["speaker_id"],
                    source_label=row["source_label"],
                    target_label=row["target_label"],
                )
            )
    return records


def write_manifest(records: list[AffectRecord], path: str | Path) -> None:
    """Write the canonical affect dataset manifest to disk."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["audio_path", "corpus", "speaker_id", "source_label", "target_label"],
        )
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
