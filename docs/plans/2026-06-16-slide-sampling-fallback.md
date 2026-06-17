# Slide Sampling Fallback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When ffmpeg scene detection returns almost no candidates (crossfade /
animated / scrolling decks), fall back to interval frame sampling + conservative
perceptual-hash dedupe so every *distinct* on-screen slide is captured without
redundant copies.

**Architecture:** Add `sample_frames` to `core/slides.py` parallel to
`detect_and_classify`, plus pure Pillow helpers (`_ahash`, `_hamming`,
`dedupe_by_hash`). `extract()` runs scene detection first and falls back to
`sample_frames` when the candidate count is below `min_candidates`. The fallback
replaces the thin set; contact sheets / manifest / the `ingest` bundle are
unchanged. Dedupe is keep-on-doubt: it never drops a frame that differs in the
content region.

**Tech Stack:** Python 3.10+, Pillow (already a dependency), ffmpeg (via
subprocess, as existing code does), pytest.

**Reference:** design doc `docs/plans/2026-06-16-slide-sampling-fallback-design.md`.

Run tests with `.venv/bin/python -m pytest` (pytest lives in the project venv).

---

## Task 1: `dedupe_by_hash` — conservative keep-on-doubt (pure)

**Files:**
- Modify: `src/yt_tui/core/slides.py`
- Test: `tests/test_slides.py` (create)

**Step 1: Write the failing test**

```python
"""Tests for slide sampling + dedupe helpers."""

from yt_tui.core import slides


def test_dedupe_by_hash_collapses_identical_run():
    # four identical frames then a clearly different one
    hashes = [0b0000, 0b0000, 0b0000, 0b1111]
    assert slides.dedupe_by_hash(hashes, threshold=1) == [0, 3]


def test_dedupe_by_hash_keeps_all_distinct():
    hashes = [0b0000, 0b0011, 0b1100, 0b1111]  # each >1 bit from the last kept
    assert slides.dedupe_by_hash(hashes, threshold=1) == [0, 1, 2, 3]


def test_dedupe_by_hash_keep_on_doubt_boundary():
    # distance exactly == threshold is a duplicate (drop); > threshold is kept
    assert slides.dedupe_by_hash([0b000, 0b001], threshold=1) == [0]      # dist 1 == thr → drop
    assert slides.dedupe_by_hash([0b000, 0b011], threshold=1) == [0, 1]   # dist 2 > thr → keep


def test_dedupe_by_hash_compares_against_last_kept_not_previous():
    # slow drift: each step is 1 bit from the prior frame but accumulates;
    # comparing to last *kept* keeps frames once drift exceeds threshold.
    hashes = [0b0000, 0b0001, 0b0011, 0b0111]
    assert slides.dedupe_by_hash(hashes, threshold=1) == [0, 2, 3]


def test_dedupe_by_hash_empty():
    assert slides.dedupe_by_hash([], threshold=6) == []
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_slides.py -v`
Expected: FAIL — `AttributeError: module 'yt_tui.core.slides' has no attribute 'dedupe_by_hash'`.

**Step 3: Write minimal implementation** (append to `slides.py`)

```python
def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


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
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_slides.py -v`
Expected: PASS (5 tests).

**Step 5: Commit**

```bash
git add src/yt_tui/core/slides.py tests/test_slides.py
git commit -m "feat(slides): conservative keep-on-doubt frame dedupe"
```

---

## Task 2: `_ahash` — center-crop average hash (Pillow)

**Files:**
- Modify: `src/yt_tui/core/slides.py`
- Test: `tests/test_slides.py`

**Step 1: Write the failing test** (append)

```python
from PIL import Image


def _solid(tmp_path, name, color, size=(200, 200)):
    p = tmp_path / name
    Image.new("RGB", size, color).save(p)
    return p


def test_ahash_identical_images_zero_distance(tmp_path):
    a = _solid(tmp_path, "a.png", (123, 200, 50))
    b = _solid(tmp_path, "b.png", (123, 200, 50))
    assert slides._hamming(slides._ahash(a), slides._ahash(b)) == 0


def test_ahash_distinguishes_structured_images(tmp_path):
    # left-half-white vs right-half-white: differ in the center region
    left = Image.new("L", (200, 200), 0)
    for x in range(100):
        for y in range(200):
            left.putpixel((x, y), 255)
    lp = tmp_path / "left.png"; left.save(lp)
    rp = tmp_path / "right.png"; left.transpose(Image.FLIP_LEFT_RIGHT).save(rp)
    assert slides._hamming(slides._ahash(lp), slides._ahash(rp)) > 10


def test_ahash_ignores_top_banner(tmp_path):
    # identical content region, different top strip → still near-zero distance
    base = Image.new("RGB", (200, 200), (10, 20, 180))
    a = base.copy(); b = base.copy()
    for x in range(200):           # paint only b's top 15% a different colour
        for y in range(30):
            b.putpixel((x, y), (255, 0, 0))
    ap = tmp_path / "a.png"; a.save(ap)
    bp = tmp_path / "b.png"; b.save(bp)
    assert slides._hamming(slides._ahash(ap), slides._ahash(bp)) <= 2
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_slides.py -k ahash -v`
Expected: FAIL — `AttributeError: ... '_ahash'`.

**Step 3: Write minimal implementation** (append to `slides.py`; add `from PIL import Image` to the imports at the top)

```python
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
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_slides.py -v`
Expected: PASS (8 tests).

**Step 5: Commit**

```bash
git add src/yt_tui/core/slides.py tests/test_slides.py
git commit -m "feat(slides): center-crop average hash (ignores banner/captions)"
```

---

## Task 3: `sample_frames` — interval sample + dedupe (I/O)

**Files:**
- Modify: `src/yt_tui/core/slides.py`

This task is ffmpeg/IO-bound and verified by integration (Task 5), matching the
existing un-unit-tested IO functions in this module. No new unit test.

**Step 1: Write the implementation** (append to `slides.py`)

```python
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
```

**Step 2: Smoke-import to catch syntax/name errors**

Run: `.venv/bin/python -c "from yt_tui.core import slides; print(slides.sample_frames)"`
Expected: prints `<function sample_frames at ...>`.

**Step 3: Commit**

```bash
git add src/yt_tui/core/slides.py
git commit -m "feat(slides): sample_frames fallback for videos with no hard cuts"
```

---

## Task 4: Wire the fallback into `extract()` + `--sample-interval` CLI

**Files:**
- Modify: `src/yt_tui/core/slides.py` (the `extract` function, ~line 184)
- Modify: `src/yt_tui/__main__.py` (slides parser line 30; ingest parser line 38;
  the `slides` and `ingest` dispatch branches)

**Step 1: Update `extract` signature + body**

Change the signature to add `interval` and `min_candidates`:

```python
def extract(url_or_file: str, outdir: Path, max_height: int = 1080,
            threshold: float = 0.3, interval: int = 15, min_candidates: int = 5,
            progress: ProgressFn | None = None) -> dict:
```

Then, immediately after the `candidates = detect_and_classify(...)` line, insert
the fallback:

```python
    candidates = detect_and_classify(video, outdir, threshold, progress)
    if len(candidates) < min_candidates:
        _log(progress, f"only {len(candidates)} scene cuts found; "
                       f"falling back to interval sampling")
        candidates = sample_frames(video, outdir, interval, progress)
```

(Leave the `build_contact_sheets` / `write_manifest` / return dict unchanged.)

**Step 2: Add `--sample-interval` to the CLI**

In `__main__.py`, after line 30 (`p_sl.add_argument("--max-height", ...)`):

```python
    p_sl.add_argument("--sample-interval", type=int, default=15,
                      help="fallback frame sampling interval in seconds")
```

After line 38 (`p_ing.add_argument("--max-height", ...)`):

```python
    p_ing.add_argument("--sample-interval", type=int, default=15,
                       help="fallback frame sampling interval in seconds")
```

**Step 3: Pass the flag through both dispatch branches**

In the `slides` branch, update the `slides.extract(...)` call:

```python
        result = slides.extract(args.url, args.out, max_height=args.max_height,
                                interval=args.sample_interval,
                                progress=lambda m: print(f"  {m}"))
```

In the `ingest` branch, update the `slides_mod.extract(...)` call:

```python
            res = slides_mod.extract(args.url, Path("/tmp/yt-tui/slides"),
                                     max_height=args.max_height,
                                     interval=args.sample_interval,
                                     progress=lambda m: print(f"  {m}"))
```

**Step 4: Verify nothing regressed + CLI parses**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (13 prior + 8 new slides tests = 21).

Run: `.venv/bin/python -m yt_tui ingest --help`
Expected: usage shows `--sample-interval`.

**Step 5: Commit**

```bash
git add src/yt_tui/core/slides.py src/yt_tui/__main__.py
git commit -m "feat(slides): auto-fallback to sampling when scene detection is thin"
```

---

## Task 5: Integration verification on the cached video

**Files:** none (verification only).

The 33-min test video is already downloaded at `/tmp/yt-tui/slides/video.mp4`, so
this is fast and needs no network.

**Step 1: Run the full ingest at default resolution**

Run:
```bash
.venv/bin/python -m yt_tui ingest "https://www.youtube.com/watch?v=fPL_L7uSo9w" \
  --out /tmp/ingest/slidetest2
```
Expected: progress shows "falling back to interval sampling" then "N distinct
slides kept"; summary prints `slides : N kept` (N roughly 30–50, **not** 0).

**Step 2: Confirm the bundle now contains slides**

Run:
```bash
ls /tmp/ingest/slidetest2/raw/slides | wc -l
grep -c "raw/slides/" /tmp/ingest/slidetest2/extracted.md
```
Expected: both > 0 and equal; a `## Slides` section is present in `extracted.md`.

**Step 3: Eyeball a spread for legibility and dedupe quality**

Open a few saved slides (e.g. first, middle, last) and confirm they are distinct,
legible content slides — not 50 near-identical copies, not transition cards only.

**Step 4: Done**

No commit (verification only). Report the slide count and a sample to the user.

---

## Done criteria

- `.venv/bin/python -m pytest -q` green (21 tests).
- `yt-tui ingest <crossfade-talk>` produces a bundle with a non-empty
  `raw/slides/` and a `## Slides` section, where before it produced none.
- Hard-cut videos still use scene detection (fallback only fires below
  `min_candidates`).
