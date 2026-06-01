"""Parse and clean YouTube auto-caption SRT files.

YouTube auto-captions use a rolling-window format: each cue repeats the previous
line plus a few new words, so the raw .srt is ~5x redundant. This module turns
that into clean, readable text plus a list of timestamped segments you can quote
from without dragging the duplication along.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 00:01:02,500 --> 00:01:05,000
_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*")


@dataclass
class Segment:
    """A single span of speech with its start time in seconds."""

    start: float
    text: str

    @property
    def mmss(self) -> str:
        m, s = divmod(int(self.start), 60)
        return f"{m}:{s:02d}"


def _parse_start_seconds(timestamp_line: str) -> float | None:
    m = _TS.match(timestamp_line)
    if not m:
        return None
    h, mins, secs, ms = (int(g) for g in m.groups())
    return h * 3600 + mins * 60 + secs + ms / 1000


def parse_srt(srt_text: str) -> list[Segment]:
    """Parse raw SRT into ordered (start, text) segments, before deduping."""
    segments: list[Segment] = []
    for block in re.split(r"\n\s*\n", srt_text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        # The block is: [index], timestamp, text...  The index line is optional
        # in converted files, so find the timestamp line rather than assuming [1].
        ts_idx = next((i for i, ln in enumerate(lines) if _TS.match(ln)), None)
        if ts_idx is None:
            continue
        start = _parse_start_seconds(lines[ts_idx])
        if start is None:
            continue
        text = " ".join(lines[ts_idx + 1 :]).strip()
        if text:
            segments.append(Segment(start=start, text=text))
    return segments


def _new_suffix(previous: str, current: str) -> str:
    """Return only the part of `current` that isn't already covered by `previous`.

    Handles the rolling-caption case where `current` is `previous` plus new words,
    and the overlap case where the tail of `previous` equals the head of `current`.
    """
    if not previous or current == previous:
        return "" if current == previous else current
    if current.startswith(previous):
        return current[len(previous) :].strip()
    # Largest suffix-of-previous == prefix-of-current overlap.
    for k in range(min(len(previous), len(current)), 0, -1):
        if previous[-k:] == current[:k]:
            return current[k:].strip()
    return current


def dedupe(segments: list[Segment]) -> list[Segment]:
    """Collapse rolling-window duplication into clean, non-repeating segments."""
    cleaned: list[Segment] = []
    last_text = ""
    for seg in segments:
        new = _new_suffix(last_text, seg.text)
        if new:
            cleaned.append(Segment(start=seg.start, text=new))
        last_text = seg.text
    return cleaned


def clean_text(segments: list[Segment]) -> str:
    """Flatten deduped segments into a single readable transcript string."""
    joined = " ".join(seg.text for seg in segments)
    return re.sub(r"\s+", " ", joined).strip()


def timestamped(segments: list[Segment], every_seconds: int = 90) -> str:
    """Readable transcript with a [m:ss] marker roughly every `every_seconds`."""
    out: list[str] = []
    last_marker = -(every_seconds + 1)
    for seg in segments:
        if seg.start - last_marker >= every_seconds:
            out.append(f"\n[{seg.mmss}] ")
            last_marker = seg.start
        out.append(seg.text + " ")
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def process(srt_text: str) -> tuple[str, list[Segment]]:
    """Convenience: raw SRT -> (clean_text, deduped_segments)."""
    deduped = dedupe(parse_srt(srt_text))
    return clean_text(deduped), deduped
