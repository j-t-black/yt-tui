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
