# Slide sampling fallback — Design

**Problem.** `slides.py` extracts slide candidates via ffmpeg scene detection
(`select='gt(scene,0.3)'`), which only fires on **hard cuts**. Talks that use
crossfade transitions, a continuously-animated banner, or a slowly-scrolling
document produce near-zero scene scores (observed: max 2.76 on a 0–100 scale
across a full 33-min talk), so scene detection returns **0 candidates** and the
on-screen content — often the most citable technical material — is lost entirely.
This surfaced when `yt-tui ingest` on such a video produced a transcript-only
bundle with no slides.

**Goal.** When scene detection comes back nearly empty, fall back to capturing
the screen by **interval sampling**, then remove redundant near-duplicate frames
so every *distinct* slide is kept without bloating the output with copies.

## Decisions

- **Trigger:** automatic. Run scene detection first; if it yields fewer than
  `min_candidates` (default 5) candidates, fall back to interval sampling. Hard-cut
  videos are unaffected; no new behaviour for the common case.
- **Completeness over rate-cutting:** sample thoroughly (default every 15s). The
  bundle-size problem is *redundancy* (one slide captured many times), not genuine
  content volume — so the lever is dedupe, not a lower sample rate. Lowering the
  rate to shrink output would trade away short-lived content; we don't do that.
- **Conservative dedupe (keep-on-doubt):** drop a frame only when it is
  near-identical to the last kept frame in the content region. Any real difference
  → keep both. Failure mode is "kept a couple extra near-dupes," never "lost a
  slide."
- **No new dependencies:** dedupe uses Pillow (already a dependency), not extra
  ffmpeg passes.

## Architecture

A new `sample_frames` in `slides.py`, parallel to `detect_and_classify`. `extract()`
gains `interval: int = 15` and `min_candidates: int = 5`:

```
candidates = detect_and_classify(video, outdir, threshold, progress)
if len(candidates) < min_candidates:        # thin → crossfade / animated / scroll
    candidates = sample_frames(video, outdir, interval, progress)
sheets = build_contact_sheets(candidates, outdir, progress=progress)   # unchanged
manifest = write_manifest(candidates, outdir)                          # unchanged
```

The fallback **replaces** the thin candidate set (no index collisions). The
keep/fallback decision is a one-line pure helper, unit-testable.

### `sample_frames(video, outdir, interval_seconds=15, progress=None) -> list[Candidate]`

1. Clear prior PNGs from `candidates_dir` / `slides_dir` so discarded
   scene-detection frames don't pollute contact sheets.
2. ffmpeg `-vf "fps=1/{interval},showinfo"` → one frame per interval into
   `candidates_dir`; parse `pts_time` from showinfo stderr for real source
   timestamps (same parsing `detect_and_classify` uses).
3. Dedupe (below) over the sampled frames in time order.
4. Name each kept frame `{i:03d}_{mm}-{ss}.png` (existing convention), copy into
   `slides_dir`, and mark `klass="slide"` — in sampling mode every kept frame is a
   slide candidate. The brightness heuristic (`slide if g>=130 or g<=25`) is
   skipped: it wrongly rejects mid-tone (e.g. blue-gradient) slides as "stage," and
   the fallback only fires on all-screen, no-camera videos where there is no stage
   shot to filter out.

### Dedupe (pure, Pillow)

- `_ahash(image_path, crop_box) -> int`: open with PIL, crop to the **center
  content region** (drop top ~15% banner + bottom ~8% caption/progress strip),
  resize to 16×16 grayscale, average hash → 256-bit int. Crop is for *comparison
  only*; the saved PNG is always the full frame.
- `_hamming(a, b) -> int`: popcount of XOR.
- `dedupe_by_hash(hashes: list[int], threshold: int = 6) -> list[int]`: pure. Walk
  in order, keep the first frame, then keep a frame iff its Hamming distance from
  the **last kept** hash `> threshold`. Returns the indices to keep.

## Data flow (fallback path)

video.mp4 → ffmpeg interval sample → raw frames + timestamps → PIL aHash per frame
→ `dedupe_by_hash` → kept indices → named/copied Candidates (klass="slide") →
contact sheets + manifest (unchanged) → `ingest` keeps `klass=="slide"` → bundle
`raw/slides/`.

## CLI

`slides` and `ingest` subcommands gain `--sample-interval` (default 15).
`min_candidates` and the dedupe `threshold` stay internal defaults (not flags) to
avoid knob sprawl; revisit if real videos need tuning.

## Testing

- **Unit (pure, no ffmpeg):**
  - `dedupe_by_hash`: identical run collapses to one; all-distinct kept; keep-on-doubt
    boundary (distance == threshold → drop; > threshold → keep).
  - `_ahash` / `_hamming` on tiny generated PIL images: identical → distance 0;
    inverted → large distance.
- **Integration (manual, fast — video already cached at `/tmp/yt-tui/slides/video.mp4`):**
  re-run `yt-tui ingest` on the test video, confirm `raw/slides/` holds ~30–50
  distinct slides (down from 0), eyeball a spread for legibility.

## Out of scope

- Tuning the brightness classifier for mid-tone slides in the scene-detection path.
- Speaker/stage filtering in sampling mode (the trigger correlates with no-camera
  videos).
- Cropping the saved frames (only comparison crops; we keep full frames).
