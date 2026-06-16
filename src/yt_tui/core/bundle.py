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
