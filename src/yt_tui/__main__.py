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

    p_ing = sub.add_parser("ingest", help="write an ingester bundle for a URL")
    p_ing.add_argument("url")
    p_ing.add_argument("--out", type=Path, default=None,
                       help="bundle dir (default: /tmp/ingest/<slug>)")
    p_ing.add_argument("--no-slides", action="store_true",
                       help="skip slide extraction (faster; no video download)")
    p_ing.add_argument("--max-height", type=int, default=1080)

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

    if args.command == "ingest":
        from datetime import datetime, timezone
        from .core import bundle, slides as slides_mod
        from .core.report import slugify

        meta = ingest.ingest(args.url, Path("/tmp/yt-tui/ingest"))
        clean, segs = "", []
        if meta.has_transcript:
            clean, segs = transcript.process(meta.srt_path.read_text())

        kept = []
        if not args.no_slides:
            res = slides_mod.extract(args.url, Path("/tmp/yt-tui/slides"),
                                     max_height=args.max_height,
                                     progress=lambda m: print(f"  {m}"))
            kept = [c for c in res["candidates"] if c.klass == "slide"]

        out = args.out or Path("/tmp/ingest") / slugify(meta.title)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        result = bundle.write_bundle(meta, args.url, segs, kept, fetched_at, out)

        print(f"\nOK  {meta.title}")
        print(f"    out dir : {result['out_dir']}")
        print(f"    slides  : {len(kept)} kept" if kept else "    slides  : skipped")
        print(f"    READ    : {result['extracted_md']}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
