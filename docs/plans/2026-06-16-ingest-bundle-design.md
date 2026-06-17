# yt-tui → ingester handoff: the `ingest` bundle

Date: 2026-06-16
Status: approved (design)

## Problem

Two tools, clean split of responsibility:

- **yt-tui** = the extractor. Pulls faithful source-of-truth data from a video
  (transcript, metadata, slides). No interpretation.
- **ingester** (`~/dev/jt-skills/ingester`, the `/ingest` skill) = the synthesizer.
  Captures a source, interviews the user, writes a tailored vault artifact.

Today the user runs yt-tui, then **copies the report markdown by hand** into the
`/ingest` conversation. The ingester cannot ingest a YouTube URL itself: its
`fetch.py` pulls the watch page, which is a JS shell with no real content.

## Key constraint: the ingester's input contract

Every ingester source mode (PDF, static URL, rendered, live tab) converges on a
fixed bundle that step 2 of the skill reads:

```
/tmp/ingest/<slug>/
├── extracted.md      # "# title", "> Source:", "> Fetched:", then clean body
├── metadata.json     # source_url, final_url, title, author, description,
│                     #   published, fetched_at, depth, pages[], links_external[], ...
└── raw/000-main.html # verbatim capture
```

So the highest-leverage move is **not** tidying yt-tui's `report` output — it is
teaching yt-tui to *speak this contract*, making a video a first-class source.

## Decision

**A (build now):** yt-tui emits an ingester-native bundle.
**B (tiny follow-up):** the ingester gets a "YouTube source mode" that calls it.

yt-tui stays dumb (no LLM, no batch, no cron). It just learns the contract.

## A. `yt-tui ingest <url> [--out DIR] [--no-slides]`

New headless subcommand. Default out dir `/tmp/ingest/<slug>` (mirrors `fetch.py`).
Prints the same `OK / out dir / READ <path>` summary `fetch.py` prints, so the
skill flow is identical regardless of source.

```
/tmp/ingest/<slug>/
├── extracted.md
├── metadata.json
└── raw/
    ├── 000-info.json      # verbatim yt-dlp capture (the "raw" analog)
    ├── 000-captions.srt
    └── slides/            # only when slides are kept
        ├── MM-SS.png
        └── manifest.tsv
```

### extracted.md (ingester convention)

```
# {title}

> Source: {url}
> Fetched: {iso8601 UTC}

**Channel:** {channel} · **Duration:** {dur} · **Uploaded:** {date} · **Views:** {n}

## Overview

{full description — NOT truncated; the ingester de-noises itself}

## Chapters

- **0:00** — {label}
...

## Slides

- ![](raw/slides/03-12.png) 3:12
...            # top auto-kept slides; omitted entirely when --no-slides

## Transcript

[0:00] {cleaned transcript text with periodic mm:ss markers so moments are citable}
...
```

### metadata.json

Map `VideoMeta` onto `fetch.py`'s schema so the ingester's frontmatter +
References logic works untouched. Extra YouTube keys are harmless.

```json
{
  "source_url": "<url>",
  "final_url": "<url>",
  "canonical_url": null,
  "title": "...",
  "site_name": "YouTube",
  "author": "<channel>",
  "description": "<full description>",
  "published": "<upload_date_iso>",
  "fetched_at": "<iso>",
  "depth": 0,
  "pages": [{"url": "<url>", "title": "...", "file": "raw/000-info.json",
             "words": <transcript word count>, "role": "main"}],
  "links_in_scope": [],
  "links_external": [{"text": "...", "url": "..."}],   // URLs parsed from description
  "video_id": "...",
  "duration": "...",
  "view_count": 0,
  "chapters": [ ... ]
}
```

`links_external` = URLs extracted from the description → a free bibliography for
the ingester's References section.

### Slides (on by default; `--no-slides` to skip)

`ingest` is headless, so there is no interactive curation step. It runs the
existing slides pipeline and **auto-keeps the frames the classifier tags as
slides** (the same set the TUI pre-ticks), writing them to `raw/slides/MM-SS.png`
plus `manifest.tsv`. The top N are referenced inline under `## Slides`; the full
candidate set + manifest remain for manual picking.

Trade-off: slides-on downloads the full video each run (needs ffmpeg).
`--no-slides` is the fast, network-light path (metadata + captions only).

## B. Ingester "YouTube source mode" (follow-up, ~5 lines in SKILL.md)

In the skill's capture step: if the input URL host is `youtube.com` / `youtu.be`,
run `yt-tui ingest "<URL>" --out /tmp/ingest/<slug>` instead of `fetch.py`, then
resume at step 2 (pull into context → discuss). Everything downstream is unchanged
because the bundle shape matches.

## Housekeeping

Fix the broken skill symlink: `~/.claude/skills/ingest` → `/Users/jtblack/dev/ingester`
(does not exist). Repoint to `/Users/jtblack/dev/jt-skills/ingester`. The skill may
not be loading at all right now.

## Architecture / where code lands

- `src/yt_tui/core/bundle.py` — **pure** builder: `(VideoMeta, segments, slides?)`
  → `extracted.md` string + `metadata` dict + list of files to copy. No I/O, no
  network → unit-testable.
- A thin writer (in `bundle.py` or `__main__`) that creates the dirs, copies
  `info.json` / `srt` / slide PNGs into `raw/`, and writes the two files.
- `__main__.py` — new `ingest` subparser wiring ingest → bundle → write → summary.
- Reuse existing `core/ingest.py` (metadata + captions), `core/transcript.py`
  (clean + segments), `core/slides.py` (extract + classify).

## Out of scope (YAGNI)

Batch/playlist input, scheduling/cron, any LLM in yt-tui, changes to the existing
`report` / TUI curation flows.

## Testing

- `tests/test_bundle.py`: feed a synthetic `VideoMeta` + segments to the pure
  builder; assert `extracted.md` has the `# title` / `> Source:` / `> Fetched:`
  header, the `## Overview/Chapters/Transcript` sections, mm:ss markers, and that
  `metadata.json` carries the required `fetch.py` keys + the YouTube extras.
- Description-URL extraction → `links_external` covered with a fixture description.
- No network in tests (the slides/yt-dlp paths are integration-only).
