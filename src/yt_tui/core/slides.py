"""Extract unique slides/figures from a (presentation) video.

Auto-captions never contain the slide infographics -- diagrams, rubrics, tables,
charts, demo screenshots -- which for talks are often the most citable artifacts.

Pipeline: download -> ffmpeg scene detection (with real timestamps) -> classify
each candidate frame as slide-vs-stage by brightness -> build contact sheets for
review. Scene detection over-captures (camera cuts to the speaker, motion inside
live demos), so the final curation -- picking the genuinely unique slides -- is
left to a human (or Claude) looking at the contact sheets. This module gets you
from a 75-minute video down to a few dozen labelled candidates cheaply.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Callable

from PIL import Image

ProgressFn = Callable[[str], None]


class SlideError(RuntimeError):
    pass


@dataclass
class Candidate:
    index: int
    path: Path
    seconds: int
    klass: str  # "slide" | "stage"

    @property
    def mmss(self) -> str:
        m, s = divmod(self.seconds, 60)
        return f"{m:02d}-{s:02d}"


_PTS = re.compile(r"pts_time:([0-9.]+)")


def _log(progress: ProgressFn | None, msg: str) -> None:
    if progress:
        progress(msg)


def _require(binary: str) -> None:
    if which(binary) is None:
        raise SlideError(f"{binary} not found on PATH")


def download_video(url: str, dest: Path, max_height: int = 1080,
                   progress: ProgressFn | None = None) -> Path:
    _require("yt-dlp")
    _log(progress, f"downloading video (<= {max_height}p)...")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "-f", f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]",
        "--merge-output-format", "mp4",
        "-o", str(dest),
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SlideError(f"download failed:\n{proc.stderr.strip()}")
    return dest


def _mean_gray(frame: Path) -> int:
    """Average luminance 0-255: downscale the frame to a single gray pixel."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(frame),
         "-vf", "scale=1:1,format=gray", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    return proc.stdout[0] if proc.stdout else 0


def detect_and_classify(video: Path, outdir: Path, threshold: float = 0.3,
                        progress: ProgressFn | None = None) -> list[Candidate]:
    """Scene-detect candidate frames, timestamp and classify each one.

    Classification is a heuristic, not truth: stage/speaker shots tend to sit at
    mid brightness (tinted by venue lighting); real slides are either bright
    (white background) or distinctly dark (title/section/demo screenshots). We
    keep the bright and dark tails as slides and treat the mid band as stage. If
    the lighting is unusual the caller can still review every candidate.
    """
    _require("ffmpeg")
    candidates_dir = outdir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    # showinfo only prints pts_time at -loglevel info, so capture stderr here.
    _log(progress, f"scene detection (threshold {threshold})...")
    raw_pattern = str(candidates_dir / "_raw_%04d.png")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video),
         "-vf", f"select='gt(scene,{threshold})',showinfo,scale=1920:-1",
         "-vsync", "vfr", raw_pattern],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SlideError(f"scene detection failed:\n{proc.stderr.strip()[-500:]}")

    pts = [float(x) for x in _PTS.findall(proc.stderr)]
    raw_frames = sorted(candidates_dir.glob("_raw_*.png"))

    candidates: list[Candidate] = []
    slides_dir = outdir / "slides"
    slides_dir.mkdir(exist_ok=True)
    _log(progress, f"classifying {len(raw_frames)} frames...")
    for i, raw in enumerate(raw_frames):
        sec = int(pts[i]) if i < len(pts) else 0
        m, s = divmod(sec, 60)
        named = candidates_dir / f"{i:03d}_{m:02d}-{s:02d}.png"
        raw.rename(named)
        g = _mean_gray(named)
        klass = "slide" if (g >= 130 or g <= 25) else "stage"
        if klass == "slide":
            (slides_dir / named.name).write_bytes(named.read_bytes())
        candidates.append(Candidate(index=i, path=named, seconds=sec, klass=klass))

    n_slides = sum(c.klass == "slide" for c in candidates)
    _log(progress, f"{len(candidates)} candidates, {n_slides} classified as slides")
    return candidates


def build_contact_sheets(candidates: list[Candidate], outdir: Path,
                         per_sheet: int = 25, cols: int = 5,
                         progress: ProgressFn | None = None) -> list[Path]:
    """Tile slide candidates into review grids (ffmpeg tile -- no ImageMagick dep).

    Frame filenames are not labelled (this ffmpeg may lack drawtext); the returned
    manifest / candidate list carries index -> timestamp instead.
    """
    _require("ffmpeg")
    # Fall back to all candidates if the colour filter kept almost nothing.
    slides = [c for c in candidates if c.klass == "slide"]
    review = slides if len(slides) >= 4 else candidates
    review = sorted(review, key=lambda c: c.index)

    sheets: list[Path] = []
    rows = (per_sheet + cols - 1) // cols
    tmp = outdir / "_sheet_tmp"
    for n, start in enumerate(range(0, len(review), per_sheet), start=1):
        if tmp.exists():
            for f in tmp.iterdir():
                f.unlink()
        tmp.mkdir(exist_ok=True)
        for j, c in enumerate(review[start:start + per_sheet]):
            (tmp / f"{j:03d}.png").write_bytes(c.path.read_bytes())
        sheet = outdir / f"contact_{n:02d}.png"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-pattern_type", "glob", "-i", str(tmp / "*.png"),
             "-vf", f"scale=460:259,tile={cols}x{rows}:margin=5:padding=3:color=white",
             "-frames:v", "1", str(sheet), "-y"],
            capture_output=True,
        )
        sheets.append(sheet)
        _log(progress, f"contact sheet {n} ({len(review[start:start+per_sheet])} frames)")
    if tmp.exists():
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()
    return sheets


def write_manifest(candidates: list[Candidate], outdir: Path) -> Path:
    path = outdir / "manifest.tsv"
    lines = ["index\tfile\tseconds\tmm:ss\tclass"]
    for c in candidates:
        m, s = divmod(c.seconds, 60)
        lines.append(f"{c.index}\t{c.path.name}\t{c.seconds}\t{m}:{s:02d}\t{c.klass}")
    path.write_text("\n".join(lines) + "\n")
    return path


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _ahash(frame: Path, hash_size: int = 16) -> int:
    """Average hash of a frame's center content region (top 15% / bottom 8%
    cropped out to ignore animated banners and caption strips). Returns a
    `hash_size**2`-bit int. Comparison-only — callers still keep the full frame.
    """
    with Image.open(frame) as im:
        w, h = im.size
        crop = im.crop((0, int(h * 0.15), w, int(h * 0.92)))
        small = crop.convert("L").resize((hash_size, hash_size), Image.BILINEAR)
    px = list(small.getdata())
    avg = sum(px) / len(px)
    bits = 0
    for i, p in enumerate(px):
        if p >= avg:
            bits |= 1 << i
    return bits


def dedupe_by_hash(hashes: list[int], threshold: int = 6) -> list[int]:
    """Indices to keep: the first frame, then any frame whose Hamming distance
    from the last *kept* hash exceeds `threshold`. Keep-on-doubt — a frame is
    dropped only when it is within `threshold` bits of the last kept frame.
    """
    kept: list[int] = []
    last: int | None = None
    for i, h in enumerate(hashes):
        if last is None or _hamming(h, last) > threshold:
            kept.append(i)
            last = h
    return kept


def sample_frames(video: Path, outdir: Path, interval_seconds: int = 15,
                  progress: ProgressFn | None = None) -> list[Candidate]:
    """Fallback when scene detection is empty: sample one frame every
    `interval_seconds`, drop consecutive near-duplicates (content-region aHash),
    and return the survivors as slide candidates. Used for crossfade / animated /
    scrolling decks that have no hard cuts.
    """
    _require("ffmpeg")
    candidates_dir = outdir / "candidates"
    slides_dir = outdir / "slides"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    slides_dir.mkdir(exist_ok=True)
    # Clear any thin scene-detection output so it can't pollute contact sheets.
    for d in (candidates_dir, slides_dir):
        for f in d.glob("*.png"):
            f.unlink()

    _log(progress, f"sampling one frame every {interval_seconds}s...")
    raw_pattern = str(candidates_dir / "_raw_%04d.png")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video),
         "-vf", f"fps=1/{interval_seconds},showinfo,scale=1920:-1",
         "-vsync", "vfr", raw_pattern],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SlideError(f"frame sampling failed:\n{proc.stderr.strip()[-500:]}")

    pts = [float(x) for x in _PTS.findall(proc.stderr)]
    raw_frames = sorted(candidates_dir.glob("_raw_*.png"))
    if not raw_frames:
        return []

    _log(progress, f"deduping {len(raw_frames)} sampled frames...")
    hashes = [_ahash(f) for f in raw_frames]
    keep = dedupe_by_hash(hashes)

    candidates: list[Candidate] = []
    for new_i, raw_i in enumerate(keep):
        sec = int(pts[raw_i]) if raw_i < len(pts) else raw_i * interval_seconds
        m, s = divmod(sec, 60)
        named = candidates_dir / f"{new_i:03d}_{m:02d}-{s:02d}.png"
        raw_frames[raw_i].rename(named)
        (slides_dir / named.name).write_bytes(named.read_bytes())
        candidates.append(Candidate(index=new_i, path=named, seconds=sec, klass="slide"))

    for leftover in candidates_dir.glob("_raw_*.png"):   # dropped duplicates
        leftover.unlink()
    _log(progress, f"{len(candidates)} distinct slides kept (from {len(raw_frames)} samples)")
    return candidates


def extract(url_or_file: str, outdir: Path, max_height: int = 1080,
            threshold: float = 0.3, progress: ProgressFn | None = None) -> dict:
    """Full pipeline. Returns paths to the working set for the curation step."""
    outdir.mkdir(parents=True, exist_ok=True)
    if re.match(r"^https?://", url_or_file):
        video = download_video(url_or_file, outdir / "video.mp4", max_height, progress)
    else:
        video = Path(url_or_file)
        if not video.exists():
            raise SlideError(f"file not found: {video}")

    candidates = detect_and_classify(video, outdir, threshold, progress)
    sheets = build_contact_sheets(candidates, outdir, progress=progress)
    manifest = write_manifest(candidates, outdir)
    _log(progress, "done -- review the contact sheets, then curate the keepers")
    return {
        "video": video,
        "candidates": candidates,
        "contact_sheets": sheets,
        "manifest": manifest,
        "slides_dir": outdir / "slides",
        "candidates_dir": outdir / "candidates",
    }
