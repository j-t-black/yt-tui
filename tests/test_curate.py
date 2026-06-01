"""Tests for saving curated slides."""

from pathlib import Path

from yt_tui.core import curate
from yt_tui.core.slides import Candidate


def _fake_frame(tmp: Path, idx: int, sec: int) -> Candidate:
    p = tmp / f"{idx:03d}_{sec // 60:02d}-{sec % 60:02d}.png"
    p.write_bytes(b"PNG" + bytes([idx]))  # stand-in content
    return Candidate(index=idx, path=p, seconds=sec, klass="slide")


def test_save_selected_names_by_timestamp_and_sorts(tmp_path):
    src = tmp_path / "candidates"
    src.mkdir()
    # Deliberately out of order to prove sorting by time.
    cands = [_fake_frame(src, 5, 130), _fake_frame(src, 1, 25), _fake_frame(src, 9, 754)]
    dest = tmp_path / "out"

    result = curate.save_selected(cands, dest)

    names = [p.name for p in result.saved]
    assert names == ["00-25.png", "02-10.png", "12-34.png"]
    assert result.manifest.exists()
    assert all(p.exists() for p in result.saved)


def test_collision_on_same_second_gets_unique_name(tmp_path):
    src = tmp_path / "c"
    src.mkdir()
    a = _fake_frame(src, 1, 60)
    b = _fake_frame(src, 2, 60)  # same second
    dest = tmp_path / "out"

    result = curate.save_selected([a, b], dest)

    assert len(result.saved) == 2
    assert len({p.name for p in result.saved}) == 2  # no overwrite
