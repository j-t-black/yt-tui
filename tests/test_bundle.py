"""Tests for the ingester bundle builder."""

from yt_tui.core import bundle
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
