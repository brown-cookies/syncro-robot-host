"""Verify canonical WP-104 manifests against the fixed dataset contract."""

from __future__ import annotations

import argparse
from pathlib import Path

from ml.affect.dataset import verify_manifest


def verify_manifest_pair(
    ravdess_manifest: str | Path,
    tess_manifest: str | Path,
    *,
    ravdess_audio_root: str | Path | None = None,
    tess_audio_root: str | Path | None = None,
) -> None:
    """Verify both corpus manifests and optionally confirm their referenced WAV files exist."""
    ravdess = verify_manifest(
        ravdess_manifest,
        expected_corpus="ravdess",
        require_audio_files=ravdess_audio_root is not None,
        audio_root=ravdess_audio_root,
    )
    tess = verify_manifest(
        tess_manifest,
        expected_corpus="tess",
        require_audio_files=tess_audio_root is not None,
        audio_root=tess_audio_root,
    )
    print(
        f"RAVDESS: PASS — {ravdess.record_count} records, "
        f"{ravdess.speaker_count} speakers, {ravdess.source_label_count} source labels, "
        f"targets={ravdess.target_label_counts}"
    )
    print(
        f"TESS: PASS — {tess.record_count} records, "
        f"{tess.speaker_count} speakers, {tess.source_label_count} source labels, "
        f"targets={tess.target_label_counts}"
    )


def main() -> int:
    """Run the command-line verification for the canonical RAVDESS and TESS manifests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ravdess-manifest", type=Path, default=Path("datasets/affect/manifests/ravdess.csv"))
    parser.add_argument("--tess-manifest", type=Path, default=Path("datasets/affect/manifests/tess.csv"))
    parser.add_argument("--ravdess-root", type=Path, default=None)
    parser.add_argument("--tess-root", type=Path, default=None)
    args = parser.parse_args()

    verify_manifest_pair(
        args.ravdess_manifest,
        args.tess_manifest,
        ravdess_audio_root=args.ravdess_root,
        tess_audio_root=args.tess_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
