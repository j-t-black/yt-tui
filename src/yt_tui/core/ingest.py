"""Fetch video metadata and auto-captions via yt-dlp (no video download)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class IngestError(RuntimeError):
    pass


@dataclass
class VideoMeta:
    video_id: str
    title: str
    channel: str
    duration_string: str
    upload_date: str  # YYYYMMDD
    view_count: int
    description: str
    chapters: list[dict] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    info_json_path: Path | None = None
    srt_path: Path | None = None

    @property
    def upload_date_iso(self) -> str:
        d = self.upload_date
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d

    @property
    def has_transcript(self) -> bool:
        return self.srt_path is not None and self.srt_path.exists()


def check_yt_dlp() -> bool:
    return _which("yt-dlp")


def _which(binary: str) -> bool:
    from shutil import which

    return which(binary) is not None


def ingest(url: str, workdir: Path, sub_lang: str = "en") -> VideoMeta:
    """Download metadata + auto-captions for `url` into `workdir`. No media."""
    if not check_yt_dlp():
        raise IngestError("yt-dlp not found. Install with: brew install yt-dlp")

    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "--write-info-json",
        "--write-auto-subs",
        "--sub-lang",
        sub_lang,
        "--convert-subs",
        "srt",
        "--skip-download",
        "-o",
        "%(id)s.%(ext)s",
        "-P",
        str(workdir),
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise IngestError(f"yt-dlp failed:\n{proc.stderr.strip()}")

    info_files = list(workdir.glob("*.info.json"))
    if not info_files:
        raise IngestError("yt-dlp produced no .info.json")
    info_path = info_files[0]
    info = json.loads(info_path.read_text())

    srt_files = list(workdir.glob(f"*.{sub_lang}.srt")) or list(workdir.glob("*.srt"))
    srt_path = srt_files[0] if srt_files else None

    return VideoMeta(
        video_id=info.get("id", ""),
        title=info.get("title", "Untitled"),
        channel=info.get("channel") or info.get("uploader", ""),
        duration_string=info.get("duration_string", ""),
        upload_date=info.get("upload_date", ""),
        view_count=info.get("view_count", 0),
        description=info.get("description", ""),
        chapters=info.get("chapters") or [],
        tags=(info.get("tags") or [])[:15],
        info_json_path=info_path,
        srt_path=srt_path,
    )
