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
