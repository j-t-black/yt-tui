"""Entry point. `yt-tui` launches the TUI; subcommands run headless."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yt-tui",
        description="YouTube → transcript, report, and slide deck (terminal UI).",
    )
    parser.add_argument(
        "--reports-dir", type=Path, default=None,
        help="where reports are written (default: ~/dev/YouTube/reports)",
    )
    sub = parser.add_subparsers(dest="command")

    p_tx = sub.add_parser("transcript", help="print a cleaned transcript for a URL")
    p_tx.add_argument("url")

    p_rep = sub.add_parser("report", help="write a markdown report for a URL")
    p_rep.add_argument("url")

    p_sl = sub.add_parser("slides", help="extract slide candidates for a URL")
    p_sl.add_argument("url")
    p_sl.add_argument("--out", type=Path, default=Path("./output/slides"))
    p_sl.add_argument("--max-height", type=int, default=1080)

    args = parser.parse_args(argv)

    if args.command is None:
        from .app import run
        run(reports_dir=args.reports_dir)
        return 0

    # Headless subcommands -- handy for scripting / CI.
    from .core import ingest, report, slides, transcript

    if args.command in {"transcript", "report"}:
        meta = ingest.ingest(args.url, Path("/tmp/yt-tui/ingest"))
        clean, segs = "", []
        if meta.has_transcript:
            clean, segs = transcript.process(meta.srt_path.read_text())
        if args.command == "transcript":
            print(clean or "(no captions available)")
        else:
            md = report.build_markdown(meta, args.url, clean, segs)
            dest = args.reports_dir or Path.home() / "dev/YouTube/reports"
            path = report.write_report(md, meta, dest)
            print(f"Report saved → {path}")
        return 0

    if args.command == "slides":
        result = slides.extract(args.url, args.out, max_height=args.max_height,
                                progress=lambda m: print(f"  {m}"))
        print(f"\n{len(result['candidates'])} candidates → {args.out}")
        print("Review contact_*.png, then curate the keepers.")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
