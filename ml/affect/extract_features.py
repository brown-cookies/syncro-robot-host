"""CLI scaffold for deterministic eGeMAPSv02 feature extraction."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from .features import extract_features


def main() -> int:
    """Run the command-line entry point for this module."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="CSV output path")
    args = parser.parse_args()

    try:
        import soundfile as sf
    except ImportError as exc:
        raise SystemExit("soundfile is required by this CLI") from exc

    audio, sample_rate = sf.read(args.audio, dtype="float32", always_2d=False)
    result = extract_features(np.asarray(audio), sample_rate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([f"feature_{i:02d}" for i in range(result.vector.size)])
        writer.writerow(result.vector.tolist())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
