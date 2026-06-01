"""The Textual TUI.

Layout: a URL input at the top, an action bar, a metadata panel on the left, and
a scrolling log on the right. Long-running work (yt-dlp, ffmpeg) runs in threaded
*workers* so the UI never freezes; workers talk back to the UI via
`call_from_thread`, which is the safe way to touch widgets from another thread.

If you're learning Textual, the three things to notice are:
  1. `compose()` declares the widget tree once.
  2. `@on(Button.Pressed, "#id")` wires an event to a handler.
  3. `@work(thread=True)` moves blocking code off the UI thread.
"""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static

from .core import ingest, report, slides, transcript
from .core.report import slugify
from .screens import CurationScreen


class YtTui(App):
    """Turn a YouTube URL into a transcript, a report, and a slide deck."""

    CSS = """
    Screen { layout: vertical; }
    #url { dock: top; margin: 1 2 0 2; }
    #actions { dock: top; height: 3; margin: 0 2; }
    #actions Button { margin: 0 1 0 0; }
    #body { height: 1fr; margin: 1 2; }
    #meta { width: 42; border: round $accent; padding: 1; margin: 0 1 0 0; }
    #log { border: round $secondary; padding: 0 1; }
    .muted { color: $text-muted; }
    """

    BINDINGS = [("q", "quit", "Quit"), ("ctrl+l", "clear_log", "Clear log")]

    def __init__(self, reports_dir: Path | None = None) -> None:
        super().__init__()
        self.reports_dir = reports_dir or Path.home() / "dev/YouTube/reports"
        self.meta: ingest.VideoMeta | None = None
        self.clean_text: str = ""
        self.segments: list[transcript.Segment] = []

    # -- UI ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(placeholder="Paste a YouTube URL and press Enter…", id="url")
        with Horizontal(id="actions"):
            yield Button("Fetch", id="fetch", variant="primary")
            yield Button("Write report", id="report", disabled=True)
            yield Button("Extract slides", id="slides", disabled=True)
        with Horizontal(id="body"):
            with VerticalScroll(id="meta"):
                yield Static("No video loaded.", id="meta-content", classes="muted")
            yield RichLog(id="log", highlight=True, wrap=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "yt-tui"
        self.sub_title = "YouTube → transcript · report · slides"
        self.log_line("[dim]Ready. Paste a URL and hit Fetch (or Enter).[/dim]")

    # -- helpers (always called on the UI thread) ----------------------------
    def log_line(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)

    def set_buttons(self, *, busy: bool) -> None:
        has_meta = self.meta is not None
        self.query_one("#fetch", Button).disabled = busy
        self.query_one("#report", Button).disabled = busy or not has_meta
        self.query_one("#slides", Button).disabled = busy or not has_meta

    def render_meta(self) -> None:
        m = self.meta
        if not m:
            return
        panel = self.query_one("#meta-content", Static)
        panel.remove_class("muted")
        transcript_state = "✓ transcript" if m.has_transcript else "✗ no captions"
        panel.update(
            f"[b]{m.title}[/b]\n\n"
            f"[dim]Channel[/dim]  {m.channel}\n"
            f"[dim]Length[/dim]   {m.duration_string}\n"
            f"[dim]Date[/dim]     {m.upload_date_iso}\n"
            f"[dim]Views[/dim]    {m.view_count:,}\n"
            f"[dim]Chapters[/dim] {len(m.chapters)}\n"
            f"[dim]Captions[/dim] {transcript_state}\n"
        )

    # -- events --------------------------------------------------------------
    @on(Input.Submitted, "#url")
    def _on_enter(self) -> None:
        self._fetch()

    @on(Button.Pressed, "#fetch")
    def _on_fetch(self) -> None:
        self._fetch()

    @on(Button.Pressed, "#report")
    def _on_report(self) -> None:
        if self.meta:
            self.set_buttons(busy=True)
            self.write_report_worker()

    @on(Button.Pressed, "#slides")
    def _on_slides(self) -> None:
        if self.meta:
            self.set_buttons(busy=True)
            self.extract_slides_worker()

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def _fetch(self) -> None:
        url = self.query_one("#url", Input).value.strip()
        if not url:
            self.log_line("[red]Enter a URL first.[/red]")
            return
        self.set_buttons(busy=True)
        self.log_line(f"[cyan]Fetching[/cyan] {url}")
        self.fetch_worker(url)

    # -- workers (run off the UI thread) -------------------------------------
    @work(thread=True, exclusive=True)
    def fetch_worker(self, url: str) -> None:
        workdir = Path("/tmp/yt-tui") / "ingest"
        try:
            meta = ingest.ingest(url, workdir)
        except ingest.IngestError as e:
            self.call_from_thread(self.log_line, f"[red]{e}[/red]")
            self.call_from_thread(self.set_buttons, busy=False)
            return

        clean, segs = "", []
        if meta.has_transcript:
            clean, segs = transcript.process(meta.srt_path.read_text())

        def finish() -> None:
            self.meta, self.clean_text, self.segments = meta, clean, segs
            self.render_meta()
            words = len(clean.split())
            self.log_line(f"[green]Loaded[/green] “{meta.title}”")
            if meta.has_transcript:
                self.log_line(f"[dim]Transcript cleaned: {words:,} words, "
                              f"{len(segs)} segments[/dim]")
            else:
                self.log_line("[yellow]No captions — metadata only.[/yellow]")
            self.set_buttons(busy=False)

        self.call_from_thread(finish)

    @work(thread=True, exclusive=True)
    def write_report_worker(self) -> None:
        assert self.meta
        url = self.query_one("#url", Input).value.strip()
        md = report.build_markdown(self.meta, url, self.clean_text, self.segments)
        path = report.write_report(md, self.meta, self.reports_dir)
        self.call_from_thread(self.log_line, f"[green]Report saved[/green] → {path}")
        self.call_from_thread(self.set_buttons, busy=False)

    @work(thread=True, exclusive=True)
    def extract_slides_worker(self) -> None:
        assert self.meta
        url = self.query_one("#url", Input).value.strip()
        outdir = Path("/tmp/yt-tui") / "slides" / self.meta.video_id

        def progress(msg: str) -> None:
            self.call_from_thread(self.log_line, f"[dim]slides:[/dim] {msg}")

        try:
            result = slides.extract(url, outdir, progress=progress)
        except slides.SlideError as e:
            self.call_from_thread(self.log_line, f"[red]{e}[/red]")
            self.call_from_thread(self.set_buttons, busy=False)
            return

        n = len(result["candidates"])
        n_slide = sum(c.klass == "slide" for c in result["candidates"])
        self.call_from_thread(
            self.log_line,
            f"[green]Extracted[/green] {n} candidates ({n_slide} look like slides). "
            "Opening curation…",
        )
        self.call_from_thread(self._open_curation, result["candidates"])

    # -- curation -----------------------------------------------------------
    def _open_curation(self, candidates: list[slides.Candidate]) -> None:
        """Push the curation screen (must run on the UI thread)."""
        if not candidates:
            self.log_line("[yellow]No slide candidates found.[/yellow]")
            self.set_buttons(busy=False)
            return
        title = self.meta.title if self.meta else "video"
        default_dest = self.reports_dir / f"{slugify(title)} - slides"
        self.push_screen(CurationScreen(candidates, default_dest), self._on_curated)

    def _on_curated(self, result) -> None:
        """Callback when the curation screen is dismissed."""
        if result is None:
            self.log_line("[dim]Curation cancelled — candidates left in /tmp.[/dim]")
        else:
            self.log_line(
                f"[green]Saved {len(result.saved)} slide(s)[/green] → {result.dest}"
            )
        self.set_buttons(busy=False)


def run(reports_dir: Path | None = None) -> None:
    YtTui(reports_dir=reports_dir).run()
