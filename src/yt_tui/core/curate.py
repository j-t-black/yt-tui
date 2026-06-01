"""Save the slides a user picked during curation.

The curation UI decides *which* candidate frames are real, unique slides; this
module just does the copying — out of the scratch working set into a tidy
destination folder, named by timestamp so they sort chronologically and line up
with the report's timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .slides import Candidate


@dataclass
class SaveResult:
    dest: Path
    saved: list[Path]
    manifest: Path


def _stamp(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}-{s:02d}"


def save_selected(selected: list[Candidate], dest: Path,
                  label: str | None = None) -> SaveResult:
    """Copy `selected` frames into `dest` as MM-SS[_label].png, write a manifest.

    Frames keep their timestamp prefix so the folder reads chronologically. An
    optional shared `label` is only a convenience; per-slide naming is the
    curator's job afterwards if they want it.
    """
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for c in sorted(selected, key=lambda x: x.seconds):
        suffix = f"_{label}" if label else ""
        out = dest / f"{_stamp(c.seconds)}{suffix}.png"
        # Guard against two frames sharing a second.
        if out.exists():
            out = dest / f"{_stamp(c.seconds)}_{c.index:03d}{suffix}.png"
        out.write_bytes(c.path.read_bytes())
        saved.append(out)

    manifest = dest / "slides.tsv"
    rows = ["file\tseconds\tmm:ss"]
    for c, out in zip(sorted(selected, key=lambda x: x.seconds), saved):
        rows.append(f"{out.name}\t{c.seconds}\t{c.seconds // 60}:{c.seconds % 60:02d}")
    manifest.write_text("\n".join(rows) + "\n")

    return SaveResult(dest=dest, saved=saved, manifest=manifest)
