"""Tests for the ingester bundle builder."""

import json as _json

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
