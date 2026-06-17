# yt-tui ingest bundle — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `yt-tui ingest <url>` subcommand that writes an ingester-native bundle (`extracted.md` + `metadata.json` + `raw/`) so a YouTube video becomes a first-class source for the `/ingest` skill.

**Architecture:** A new **pure** module `core/bundle.py` turns `(VideoMeta, segments, kept-slides, fetched_at)` into an `extracted.md` string and a `metadata` dict (no I/O, fully unit-testable). A thin `write_bundle` writer does the filesystem work (dirs, copy `info.json`/`srt`/slide PNGs, write the two files). `__main__.py` wires `ingest` → existing `core.ingest` + `core.transcript` + `core.slides` → `bundle` → summary. Slides are ON by default (`--no-slides` opts out). Two out-of-repo follow-ups: a YouTube branch in the ingester SKILL.md and a symlink fix.

**Tech Stack:** Python 3.10+, stdlib only (`json`, `re`, `datetime`, `pathlib`), pytest. Reuses `yt-dlp`/`ffmpeg` only through existing modules.

**Reference:** design doc `docs/plans/2026-06-16-ingest-bundle-design.md`.

---

## Task 1: Description → external links (pure)

**Files:**
- Create: `src/yt_tui/core/bundle.py`
- Test: `tests/test_bundle.py`

**Step 1: Write the failing test**

```python
"""Tests for the ingester bundle builder."""

from yt_tui.core import bundle


def test_extract_description_links_finds_urls_and_dedupes():
    desc = (
        "My talk slides: https://example.com/slides\n"
        "Follow me https://example.com/me and again https://example.com/slides"
    )
    links = bundle.extract_description_links(desc)
    urls = [l["url"] for l in links]
    assert urls == ["https://example.com/slides", "https://example.com/me"]
    assert all(set(l.keys()) == {"text", "url"} for l in links)


def test_extract_description_links_empty():
    assert bundle.extract_description_links("") == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_bundle.py -v`
Expected: FAIL with `AttributeError: module 'yt_tui.core.bundle' has no attribute 'extract_description_links'` (after creating an empty `bundle.py`, else ImportError).

**Step 3: Write minimal implementation**

```python
"""Build an ingester-native bundle (extracted.md + metadata.json + raw/) from a video.

Pure builders here have no I/O so they unit-test cleanly; `write_bundle` does the
filesystem work. The output matches what the `/ingest` skill's fetch.py emits, so a
YouTube video drops into the same downstream flow as any web page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .ingest import VideoMeta
from .transcript import Segment, timestamped

_URL_RE = re.compile(r"https?://[^\s<>()]+")


def extract_description_links(description: str) -> list[dict]:
    """Pull URLs out of a video description, in order, deduped → [{text, url}]."""
    seen: set[str] = set()
    out: list[dict] = []
    for url in _URL_RE.findall(description or ""):
        url = url.rstrip(".,);")
        if url in seen:
            continue
        seen.add(url)
        out.append({"text": url, "url": url})
    return out
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_bundle.py -v`
Expected: PASS (2 tests).

**Step 5: Commit**

```bash
git add src/yt_tui/core/bundle.py tests/test_bundle.py
git commit -m "feat(bundle): extract external links from description"
```

---

## Task 2: `build_extracted_md` — header, overview, chapters, transcript (pure)

**Files:**
- Modify: `src/yt_tui/core/bundle.py`
- Test: `tests/test_bundle.py`

**Step 1: Write the failing test**

```python
from yt_tui.core.ingest import VideoMeta
from yt_tui.core.transcript import Segment


def _meta(**kw) -> VideoMeta:
    base = dict(
        video_id="abc123", title="My Great Talk", channel="Confy",
        duration_string="12:34", upload_date="20260601", view_count=1234,
        description="Intro para.\n\nMore detail. See https://example.com/x",
        chapters=[{"start_time": 0, "title": "Intro"},
                  {"start_time": 90, "title": "Body"}],
        tags=["python"],
    )
    base.update(kw)
    return VideoMeta(**base)


def test_build_extracted_md_has_header_and_sections():
    segs = [Segment(0.0, "Hello there."), Segment(100.0, "Now the body.")]
    md = bundle.build_extracted_md(
        _meta(), "https://youtu.be/abc123", segs,
        slide_rows=[], fetched_at="2026-06-16T00:00:00+00:00",
    )
    assert md.startswith("# My Great Talk\n")
    assert "> Source: https://youtu.be/abc123" in md
    assert "> Fetched: 2026-06-16T00:00:00+00:00" in md
    assert "**Channel:** Confy" in md
    assert "## Overview" in md
    assert "Intro para." in md                      # full description, not truncated
    assert "## Chapters" in md
    assert "- **0:00** — Intro" in md
    assert "- **1:30** — Body" in md
    assert "## Transcript" in md
    assert "[0:00]" in md and "Hello there." in md
    assert "## Slides" not in md                    # no slides passed


def test_build_extracted_md_handles_missing_transcript_and_chapters():
    md = bundle.build_extracted_md(
        _meta(chapters=[], description=""), "https://youtu.be/x", [],
        slide_rows=[], fetched_at="2026-06-16T00:00:00+00:00",
    )
    assert "_No transcript available._" in md
    assert "## Chapters" not in md                  # omitted when no chapters
    assert "_No description available._" in md
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_bundle.py -k extracted_md -v`
Expected: FAIL with `AttributeError: ... has no attribute 'build_extracted_md'`.

**Step 3: Write minimal implementation** (append to `bundle.py`)

```python
def _chapter_rows(meta: VideoMeta) -> list[tuple[str, str]]:
    rows = []
    for ch in meta.chapters:
        sec = int(ch.get("start_time", 0))
        rows.append((f"{sec // 60}:{sec % 60:02d}", ch.get("title", "")))
    return rows


def build_extracted_md(meta: VideoMeta, url: str, segments: list[Segment],
                       slide_rows: list[tuple[str, str]],
                       fetched_at: str) -> str:
    """Render the ingester's extracted.md: title, Source/Fetched, then body.

    `slide_rows` is (display_mmss, relative_png_path); empty omits the section.
    """
    lines = [
        f"# {meta.title}",
        "",
        f"> Source: {url}",
        f"> Fetched: {fetched_at}",
        "",
        f"**Channel:** {meta.channel} · **Duration:** {meta.duration_string} · "
        f"**Uploaded:** {meta.upload_date_iso} · **Views:** {meta.view_count:,}",
        "",
        "## Overview",
        "",
        meta.description.strip() if meta.description else "_No description available._",
        "",
    ]
    chapters = _chapter_rows(meta)
    if chapters:
        lines += ["## Chapters", ""]
        lines += [f"- **{ts}** — {label}" for ts, label in chapters]
        lines.append("")
    if slide_rows:
        lines += ["## Slides", ""]
        lines += [f"- ![]({path}) {disp}" for disp, path in slide_rows]
        lines.append("")
    body = timestamped(segments) if segments else "_No transcript available._"
    lines += ["## Transcript", "", body, ""]
    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_bundle.py -v`
Expected: PASS (all tests so far).

**Step 5: Commit**

```bash
git add src/yt_tui/core/bundle.py tests/test_bundle.py
git commit -m "feat(bundle): render extracted.md from video metadata + transcript"
```

---

## Task 3: `build_metadata` — fetch.py schema + youtube extras (pure)

**Files:**
- Modify: `src/yt_tui/core/bundle.py`
- Test: `tests/test_bundle.py`

**Step 1: Write the failing test**

```python
def test_build_metadata_has_fetchpy_keys_and_youtube_extras():
    segs = [Segment(0.0, "two words")]
    meta = bundle.build_metadata(
        _meta(), "https://youtu.be/abc123", segs,
        fetched_at="2026-06-16T00:00:00+00:00",
    )
    # fetch.py contract keys the ingester relies on:
    for key in ("source_url", "final_url", "canonical_url", "title", "site_name",
                "author", "description", "published", "fetched_at", "depth",
                "pages", "links_in_scope", "links_external"):
        assert key in meta, key
    assert meta["site_name"] == "YouTube"
    assert meta["author"] == "Confy"
    assert meta["published"] == "2026-06-01"
    assert meta["depth"] == 0
    assert meta["pages"][0]["role"] == "main"
    assert meta["pages"][0]["words"] == 2
    assert meta["links_external"] == [{"text": "https://example.com/x",
                                       "url": "https://example.com/x"}]
    # youtube extras:
    assert meta["video_id"] == "abc123"
    assert meta["view_count"] == 1234
    assert meta["chapters"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_bundle.py -k metadata -v`
Expected: FAIL with `AttributeError: ... 'build_metadata'`.

**Step 3: Write minimal implementation** (append to `bundle.py`)

```python
def build_metadata(meta: VideoMeta, url: str, segments: list[Segment],
                   fetched_at: str) -> dict:
    """Map VideoMeta onto fetch.py's metadata schema (+ harmless youtube extras)."""
    words = sum(len(s.text.split()) for s in segments)
    return {
        "source_url": url,
        "final_url": url,
        "canonical_url": None,
        "title": meta.title,
        "site_name": "YouTube",
        "author": meta.channel,
        "description": meta.description,
        "published": meta.upload_date_iso,
        "fetched_at": fetched_at,
        "depth": 0,
        "pages": [{"url": url, "title": meta.title,
                   "file": "raw/000-info.json", "words": words, "role": "main"}],
        "links_in_scope": [],
        "links_external": extract_description_links(meta.description),
        "video_id": meta.video_id,
        "duration": meta.duration_string,
        "view_count": meta.view_count,
        "chapters": meta.chapters,
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_bundle.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/yt_tui/core/bundle.py tests/test_bundle.py
git commit -m "feat(bundle): build metadata.json in fetch.py's schema"
```

---

## Task 4: `write_bundle` — filesystem writer (I/O)

**Files:**
- Modify: `src/yt_tui/core/bundle.py`
- Test: `tests/test_bundle.py`

**Step 1: Write the failing test**

```python
import json as _json


def test_write_bundle_lays_out_files_and_copies_raw(tmp_path):
    # fake the yt-dlp artifacts VideoMeta points at
    info = tmp_path / "abc123.info.json"
    info.write_text('{"id": "abc123"}')
    srt = tmp_path / "abc123.en.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nhi\n")
    meta = _meta(info_json_path=info, srt_path=srt)

    # one kept slide (Candidate-like): reuse the real Candidate
    from yt_tui.core.slides import Candidate
    frame = tmp_path / "000_03-12.png"
    frame.write_bytes(b"PNG")
    kept = [Candidate(index=0, path=frame, seconds=192, klass="slide")]

    out = tmp_path / "ingest" / "my-great-talk"
    result = bundle.write_bundle(
        meta, "https://youtu.be/abc123",
        [Segment(0.0, "hi there")], kept,
        fetched_at="2026-06-16T00:00:00+00:00", out_dir=out,
    )

    assert (out / "extracted.md").exists()
    md = (out / "extracted.md").read_text()
    assert "## Slides" in md and "raw/slides/03-12.png" in md
    md_json = _json.loads((out / "metadata.json").read_text())
    assert md_json["video_id"] == "abc123"
    assert (out / "raw" / "000-info.json").read_text() == '{"id": "abc123"}'
    assert (out / "raw" / "000-captions.srt").exists()
    assert (out / "raw" / "slides" / "03-12.png").read_bytes() == b"PNG"
    assert result["extracted_md"] == out / "extracted.md"
    assert result["out_dir"] == out


def test_write_bundle_no_slides(tmp_path):
    info = tmp_path / "x.info.json"; info.write_text("{}")
    meta = _meta(info_json_path=info, srt_path=None)
    out = tmp_path / "o"
    bundle.write_bundle(meta, "https://youtu.be/x", [], [],
                        fetched_at="2026-06-16T00:00:00+00:00", out_dir=out)
    assert not (out / "raw" / "slides").exists()
    assert "## Slides" not in (out / "extracted.md").read_text()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_bundle.py -k write_bundle -v`
Expected: FAIL with `AttributeError: ... 'write_bundle'`.

**Step 3: Write minimal implementation** (append to `bundle.py`)

```python
def write_bundle(meta: VideoMeta, url: str, segments: list[Segment],
                 kept_slides: list, fetched_at: str, out_dir: Path) -> dict:
    """Write extracted.md + metadata.json + raw/ for the ingester. Returns paths."""
    raw = out_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    if meta.info_json_path and meta.info_json_path.exists():
        (raw / "000-info.json").write_bytes(meta.info_json_path.read_bytes())
    if meta.srt_path and meta.srt_path.exists():
        (raw / "000-captions.srt").write_bytes(meta.srt_path.read_bytes())

    slide_rows: list[tuple[str, str]] = []
    if kept_slides:
        sdir = raw / "slides"
        sdir.mkdir(exist_ok=True)
        for c in sorted(kept_slides, key=lambda x: x.seconds):
            name = f"{c.seconds // 60:02d}-{c.seconds % 60:02d}.png"
            dest = sdir / name
            if dest.exists():
                name = f"{c.seconds // 60:02d}-{c.seconds % 60:02d}_{c.index:03d}.png"
                dest = sdir / name
            dest.write_bytes(c.path.read_bytes())
            slide_rows.append((f"{c.seconds // 60}:{c.seconds % 60:02d}",
                               f"raw/slides/{name}"))

    md = build_extracted_md(meta, url, segments, slide_rows, fetched_at)
    metadata = build_metadata(meta, url, segments, fetched_at)
    (out_dir / "extracted.md").write_text(md)
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    return {"out_dir": out_dir, "extracted_md": out_dir / "extracted.md"}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_bundle.py -v`
Expected: PASS (all bundle tests).

**Step 5: Commit**

```bash
git add src/yt_tui/core/bundle.py tests/test_bundle.py
git commit -m "feat(bundle): write_bundle lays out extracted.md/metadata.json/raw"
```

---

## Task 5: Wire the `ingest` subcommand

**Files:**
- Modify: `src/yt_tui/__main__.py:19-63` (subparsers + dispatch)

**Step 1: Add the subparser** (after the `slides` parser block, before `args = parser.parse_args(argv)`):

```python
    p_ing = sub.add_parser("ingest", help="write an ingester bundle for a URL")
    p_ing.add_argument("url")
    p_ing.add_argument("--out", type=Path, default=None,
                       help="bundle dir (default: /tmp/ingest/<slug>)")
    p_ing.add_argument("--no-slides", action="store_true",
                       help="skip slide extraction (faster; no video download)")
    p_ing.add_argument("--max-height", type=int, default=1080)
```

**Step 2: Add the dispatch branch** (after the `slides` branch, before `return 1`):

```python
    if args.command == "ingest":
        from datetime import datetime, timezone
        from .core import bundle, slides as slides_mod
        from .core.report import slugify

        meta = ingest.ingest(args.url, Path("/tmp/yt-tui/ingest"))
        clean, segs = "", []
        if meta.has_transcript:
            clean, segs = transcript.process(meta.srt_path.read_text())

        kept = []
        if not args.no_slides:
            res = slides_mod.extract(args.url, Path("/tmp/yt-tui/slides"),
                                     max_height=args.max_height,
                                     progress=lambda m: print(f"  {m}"))
            kept = [c for c in res["candidates"] if c.klass == "slide"]

        out = args.out or Path("/tmp/ingest") / slugify(meta.title)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        result = bundle.write_bundle(meta, args.url, segs, kept, fetched_at, out)

        print(f"\nOK  {meta.title}")
        print(f"    out dir : {result['out_dir']}")
        print(f"    slides  : {len(kept)} kept" if kept else "    slides  : skipped")
        print(f"    READ    : {result['extracted_md']}")
        return 0
```

**Step 3: Manual smoke test** (network — run once by hand, not in CI):

Run: `yt-tui ingest "https://www.youtube.com/watch?v=<a short talk>" --no-slides`
Expected: prints `OK / out dir / READ`; `cat /tmp/ingest/<slug>/extracted.md` shows the
`# title`, `> Source:`, `## Overview/Chapters/Transcript` sections; `metadata.json` is valid JSON with `site_name: "YouTube"`.

Then verify the full suite is green:
Run: `pytest -q`
Expected: all pass (8 prior + new bundle tests).

**Step 4: Commit**

```bash
git add src/yt_tui/__main__.py
git commit -m "feat: add 'yt-tui ingest' subcommand (slides on by default)"
```

---

## Task 6: Update README usage

**Files:**
- Modify: `README.md` (Headless subcommands section, ~line 52-64)

**Step 1:** Add an `ingest` entry to the headless subcommands block and one sentence
explaining it writes an ingester bundle to `/tmp/ingest/<slug>` (slides on by default,
`--no-slides` to skip).

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document 'yt-tui ingest' subcommand"
```

---

## Task 7 (out-of-repo): Ingester YouTube source mode

**Files:**
- Modify: `/Users/jtblack/dev/jt-skills/ingester/SKILL.md` (Workflow step 1)

Add a bullet to the capture step: if the input URL host is `youtube.com`/`youtu.be`,
run `yt-tui ingest "<URL>" --out /tmp/ingest/<slug>` instead of `fetch.py`/render, then
resume at step 2. Note in REFERENCE.md that YouTube is a source mode backed by yt-tui.
Commit in that repo separately.

## Task 8 (out-of-repo): Fix the skill symlink

```bash
ln -sfn /Users/jtblack/dev/jt-skills/ingester ~/.claude/skills/ingest
ls -l ~/.claude/skills/ingest          # verify it resolves
```

(Confirm with the user first — it changes how the skill loads.)

---

## Done criteria

- `pytest -q` green, including new `tests/test_bundle.py`.
- `yt-tui ingest <url>` produces a bundle the ingester reads without modification.
- `/ingest <youtube-url>` works end-to-end after Task 7 + 8.
