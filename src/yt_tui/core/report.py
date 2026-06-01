"""Assemble a markdown report from metadata + cleaned transcript."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .ingest import VideoMeta
from .transcript import Segment


def slugify(title: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:max_len].rstrip("-") or "video"


def _chapters_or_segments(meta: VideoMeta, segments: list[Segment]) -> list[tuple[str, str]]:
    """Return (timestamp, label) rows, preferring real chapter markers."""
    if meta.chapters:
        rows = []
        for ch in meta.chapters:
            sec = int(ch.get("start_time", 0))
            rows.append((f"{sec // 60}:{sec % 60:02d}", ch.get("title", "")))
        return rows
    # Otherwise sample the transcript every ~10% of its length.
    if not segments:
        return []
    step = max(1, len(segments) // 10)
    return [(s.mmss, s.text[:80] + "...") for s in segments[::step]]


def build_markdown(meta: VideoMeta, url: str, clean: str,
                   segments: list[Segment], content_type: str = "other") -> str:
    today = date.today().isoformat()
    tags = ", ".join(["youtube", *meta.tags[:6]])
    lines = [
        "---",
        f"created: {today}",
        "type: youtube-report",
        f"url: {url}",
        f"video_id: {meta.video_id}",
        f"channel: {meta.channel}",
        f"duration: {meta.duration_string}",
        f"upload_date: {meta.upload_date_iso}",
        f"content_type: {content_type}",
        f"tags: [{tags}]",
        "---",
        "",
        f"# {meta.title}",
        "",
        f"**Channel:** {meta.channel} · **Duration:** {meta.duration_string} · "
        f"**Uploaded:** {meta.upload_date_iso} · **Views:** {meta.view_count:,}",
        "",
        "## Overview",
        "",
        (meta.description.strip().split("\n\n")[0][:600] if meta.description
         else "_No description available._"),
        "",
        "## Sections",
        "",
    ]
    for ts, label in _chapters_or_segments(meta, segments):
        lines.append(f"- **{ts}** — {label}")
    lines += [
        "",
        "## Transcript (cleaned)",
        "",
        clean if clean else "_No transcript available._",
        "",
        "## Source",
        "",
        f"- {url}",
        "",
    ]
    return "\n".join(lines)


def write_report(markdown: str, meta: VideoMeta, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"{date.today().isoformat()}-{slugify(meta.title)}.md"
    path = dest_dir / name
    path.write_text(markdown)
    return path
