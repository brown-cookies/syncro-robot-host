"""Build the canonical WP-104 manifests from local RAVDESS and TESS corpora."""

from __future__ import annotations

import argparse
from pathlib import Path
import re

from ml.affect.dataset import AffectRecord, write_manifest
from ml.affect.label_mapping import map_label

RAVDESS_FILENAME = re.compile(
    r"^(?P<modality>03)-(?P<vocal_channel>01)-(?P<emotion>\d{2})-"
    r"(?P<intensity>\d{2})-(?P<statement>\d{2})-(?P<repetition>\d{2})-"
    r"(?P<actor>\d{2})\.wav$",
    re.IGNORECASE,
)
TESS_FILENAME = re.compile(
    r"^(?P<speaker>YAF|OAF)_(?P<word>[^_]+)_(?P<emotion>.+)\.wav$",
    re.IGNORECASE,
)
RAVDESS_EMOTIONS = {
    "01": "neutral",
    "02": "calm",
    "03": "happy",
    "04": "sad",
    "05": "angry",
    "06": "fearful",
    "07": "disgust",
    "08": "surprised",
}
RAVDESS_SPEAKERS = {f"Actor_{index:02d}" for index in range(1, 25)}


def build_ravdess_records(root: str | Path) -> list[AffectRecord]:
    """Parse the official RAVDESS actor directories into canonical manifest records."""
    base = Path(root).resolve()
    records: list[AffectRecord] = []
    for actor_dir in sorted(base.glob("Actor_*")):
        if not actor_dir.is_dir():
            continue
        speaker_id = actor_dir.name.removeprefix("Actor_")
        if actor_dir.name not in RAVDESS_SPEAKERS:
            raise ValueError(
                f"Unexpected RAVDESS speaker directory: {actor_dir.name}")
        for audio_path in sorted(actor_dir.glob("*.wav")):
            match = RAVDESS_FILENAME.match(audio_path.name)
            if match is None:
                raise ValueError(
                    f"Unrecognised RAVDESS filename: {audio_path}")
            if match.group("actor") != speaker_id:
                raise ValueError(
                    "RAVDESS speaker mismatch between directory and filename: "
                    f"{audio_path}"
                )
            source_label = RAVDESS_EMOTIONS.get(match.group("emotion"))
            if source_label is None:
                raise ValueError(
                    f"Unsupported RAVDESS emotion code: {audio_path.name}")
            records.append(
                AffectRecord(
                    audio_path=audio_path.relative_to(base),
                    corpus="ravdess",
                    speaker_id=speaker_id,
                    source_label=source_label,
                    target_label=map_label("ravdess", source_label),
                )
            )
    return records


def build_tess_records(root: str | Path) -> list[AffectRecord]:
    """Parse TESS speaker-prefixed filenames into canonical manifest records."""
    base = Path(root).resolve()
    records: list[AffectRecord] = []
    for audio_path in sorted(base.glob("*.wav")):
        match = TESS_FILENAME.match(audio_path.name)
        if match is None:
            raise ValueError(f"Unrecognised TESS filename: {audio_path}")
        source_label = " ".join(match.group(
            "emotion").replace("_", " ").split()).lower()
        if source_label == "ps":
            source_label = "pleasant surprise"
        records.append(
            AffectRecord(
                audio_path=audio_path.relative_to(base),
                corpus="tess",
                speaker_id=match.group("speaker").upper(),
                source_label=source_label,
                target_label=map_label("tess", source_label),
            )
        )
    return records


def main() -> int:
    """Run the manifest-building command for both WP-104 corpora."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ravdess-root", type=Path, required=True)
    parser.add_argument("--tess-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("datasets/affect/manifests"))
    args = parser.parse_args()

    ravdess = build_ravdess_records(args.ravdess_root)
    tess = build_tess_records(args.tess_root)
    write_manifest(ravdess, args.output_dir / "ravdess.csv")
    write_manifest(tess, args.output_dir / "tess.csv")

    print(
        f"RAVDESS: {len(ravdess)} records, "
        f"{len({record.speaker_id for record in ravdess})} speakers, "
        f"{len({record.source_label for record in ravdess})} source labels"
    )
    print(
        f"TESS: {len(tess)} records, "
        f"{len({record.speaker_id for record in tess})} speakers, "
        f"{len({record.source_label for record in tess})} source labels"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
