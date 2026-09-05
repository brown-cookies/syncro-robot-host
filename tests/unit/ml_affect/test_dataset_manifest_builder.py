from __future__ import annotations

from pathlib import Path

import pytest

from ml.affect.dataset import load_manifest
from scripts.build_affect_manifests import build_ravdess_records, build_tess_records


def test_build_ravdess_records_parses_filename_metadata(tmp_path: Path) -> None:
    root = tmp_path / "datasets/affect/RAVDESS"
    actor = root / "Actor_01"
    actor.mkdir(parents=True)
    path = actor / "03-01-05-02-01-01-01.wav"
    path.touch()

    records = build_ravdess_records(root, tmp_path)

    assert len(records) == 1
    assert records[0].speaker_id == "01"
    assert records[0].source_label == "angry"
    assert records[0].target_label == "High"


def test_build_ravdess_records_rejects_actor_directory_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "RAVDESS"
    actor = root / "Actor_01"
    actor.mkdir(parents=True)
    (actor / "03-01-05-02-01-01-02.wav").touch()
    wrong = root / "Actor_02" / "03-01-05-02-01-01-02.wav"
    wrong.parent.mkdir()
    wrong.touch()

    with pytest.raises(ValueError, match="actor directory mismatch"):
        build_ravdess_records(root, tmp_path)


def test_build_tess_records_parses_speaker_and_pleasant_surprise(tmp_path: Path) -> None:
    root = tmp_path / "datasets/affect/TESS"
    root.mkdir(parents=True)
    path = root / "YAF_back_ps.wav"
    path.touch()

    records = build_tess_records(root, tmp_path)

    assert len(records) == 1
    assert records[0].speaker_id == "YAF"
    assert records[0].source_label == "pleasant surprise"
    assert records[0].target_label == "Moderate"


def test_written_manifest_round_trips_with_validator(tmp_path: Path) -> None:
    root = tmp_path / "TESS"
    root.mkdir(parents=True)
    (root / "OAF_back_angry.wav").touch()
    output = tmp_path / "tess.csv"

    from ml.affect.dataset import write_manifest

    records = build_tess_records(root, tmp_path)
    write_manifest(records, output)

    loaded = load_manifest(output)
    assert loaded == records
