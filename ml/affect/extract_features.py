"""Manifest-driven eGeMAPSv02 feature extraction for WP-104."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Callable

import numpy as np

from .dataset import write_feature_alignment_sidecar
from .features import EXPECTED_FEATURE_COUNT, FeatureExtractionResult, extract_features

FEATURE_COLUMNS = tuple(
    f"feature_{index:02d}" for index in range(EXPECTED_FEATURE_COUNT))


def _load_audio(path: Path) -> tuple[np.ndarray, int]:
    """Load one WAV file as float32 samples while preserving its recorded sample rate."""
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError(
            "soundfile is required for WP-104 audio extraction") from exc
    try:
        audio, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    except Exception as exc:
        raise RuntimeError(f"Could not read audio file: {path}") from exc
    return np.asarray(audio), int(sample_rate)


def _read_manifest(manifest_path: Path) -> list[dict[str, str]]:
    """Load and validate the canonical manifest rows used by batch extraction."""
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"audio_path", "corpus",
                    "speaker_id", "source_label", "target_label"}
        if set(reader.fieldnames or ()) != required:
            raise ValueError(
                "Manifest must contain exactly the canonical five columns")
        return list(reader)


def extract_manifest_features(
    manifest_path: Path,
    audio_root: Path,
    *,
    extractor: Callable[[np.ndarray, int],
                        FeatureExtractionResult] = extract_features,
    progress_every: int = 25,
    progress_label: str | None = None,
) -> np.ndarray:
    """Extract one ordered 88-feature row for every audio record in a manifest."""
    if progress_every <= 0:
        raise ValueError("progress_every must be positive")

    records = _read_manifest(manifest_path)
    root = audio_root.resolve()
    total = len(records)
    label = progress_label or manifest_path.stem.upper()
    rows: list[np.ndarray] = []

    print(f"[{label}] Starting feature extraction: {total} files", flush=True)
    for index, record in enumerate(records, start=1):
        relative_path = Path(record["audio_path"])
        audio_path = (root / relative_path).resolve()
        if root not in audio_path.parents:
            raise ValueError(
                f"Manifest audio path escapes dataset root: {record['audio_path']}")
        if not audio_path.is_file():
            raise FileNotFoundError(
                f"Manifest audio file does not exist: {audio_path}")

        audio, sample_rate = _load_audio(audio_path)
        result = extractor(audio, sample_rate)
        if result.vector.size != EXPECTED_FEATURE_COUNT:
            raise ValueError(
                f"Expected {EXPECTED_FEATURE_COUNT} features for {audio_path}, "
                f"got {result.vector.size}"
            )
        rows.append(np.asarray(result.vector, dtype=np.float64))

        if index == 1 or index % progress_every == 0 or index == total:
            percent = (index / total * 100.0) if total else 100.0
            print(f"[{label}] {index}/{total} ({percent:6.2f}%)", flush=True)

    if not rows:
        return np.empty((0, EXPECTED_FEATURE_COUNT), dtype=np.float64)
    return np.vstack(rows)


def write_feature_table(matrix: np.ndarray, output_path: Path) -> None:
    """Write an 88-column floating-point feature matrix as a CSV file."""
    array = np.asarray(matrix)
    if array.ndim != 2 or array.shape[1] != EXPECTED_FEATURE_COUNT:
        raise ValueError(
            f"Feature matrix must have exactly {EXPECTED_FEATURE_COUNT} columns")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FEATURE_COLUMNS)
        writer.writerows(array.tolist())


def extract_corpus(manifest: Path, audio_root: Path, output: Path, *, progress_every: int) -> np.ndarray:
    """Extract and persist one corpus feature table while reporting progress to the console."""
    matrix = extract_manifest_features(
        manifest,
        audio_root,
        progress_every=progress_every,
        progress_label=manifest.stem.upper(),
    )
    write_feature_table(matrix, output)
    write_feature_alignment_sidecar(manifest, output)
    print(f"[{manifest.stem.upper()}] Wrote {matrix.shape[0]} rows to {output}", flush=True)
    return matrix


def main() -> int:
    """Extract RAVDESS first and TESS second using their canonical manifests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ravdess-root", type=Path, required=True)
    parser.add_argument("--tess-root", type=Path, required=True)
    parser.add_argument("--manifest-dir", type=Path,
                        default=Path("datasets/affect/manifests"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("datasets/features"))
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()

    if args.progress_every <= 0:
        parser.error("--progress-every must be positive")

    extract_corpus(
        args.manifest_dir / "ravdess.csv",
        args.ravdess_root,
        args.output_dir / "ravdess.csv",
        progress_every=args.progress_every,
    )
    extract_corpus(
        args.manifest_dir / "tess.csv",
        args.tess_root,
        args.output_dir / "tess.csv",
        progress_every=args.progress_every,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
