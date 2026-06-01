"""The slide-curation screen.

After extraction we have a few dozen candidate frames. Scene detection over-
captures (camera cuts, demo motion, animated build-ups), so a human still has to
pick the genuinely unique slides. This screen makes that a keyboard-driven pass
instead of opening a folder of PNGs:

  left   — a checklist of candidates (pre-ticked for the ones auto-classed "slide")
  right  — a live preview of the highlighted frame
  bottom — where to save the kept slides

Inline preview uses `textual-image`, which renders real graphics in capable
terminals (iTerm2, Kitty, Ghostty…) and falls back to unicode half-blocks
elsewhere. If the import isn't available at all, press `o` to open the frame in
the system viewer instead.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, SelectionList, Static
from textual.widgets.selection_list import Selection

from .core import curate
from .core.slides import Candidate

try:
    from textual_image.widget import Image as TImage
    HAS_INLINE_IMAGE = True
except Exception:  # pragma: no cover - depends on optional dep
    HAS_INLINE_IMAGE = False


class CurationScreen(ModalScreen):
    """Pick which candidate frames are real slides, then save them."""

    CSS = """
    CurationScreen { align: center middle; }
    #panel { width: 96%; height: 92%; border: round $accent; padding: 1; }
    #cols { height: 1fr; }
    #picker { width: 40; border-right: solid $secondary; padding: 0 1 0 0; }
    #picker SelectionList { height: 1fr; }
    #preview-pane { padding: 0 0 0 2; }
    #caption { height: 1; color: $text-muted; }
    #preview { height: 1fr; }
    #save-row { height: 3; margin-top: 1; }
    #dest { width: 1fr; margin-right: 1; }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
        Binding("o", "open_external", "Open in viewer"),
        Binding("a", "all", "All"),
        Binding("z", "none", "None"),
    ]

    def __init__(self, candidates: list[Candidate], default_dest: Path) -> None:
        super().__init__()
        self.candidates = candidates
        self.by_index = {c.index: c for c in candidates}
        self.default_dest = default_dest

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="panel"):
            n_slide = sum(c.klass == "slide" for c in self.candidates)
            yield Label(
                f"[b]Curate slides[/b] — {len(self.candidates)} candidates, "
                f"{n_slide} pre-selected. Space toggles · ↑↓ preview · Ctrl+S saves."
            )
            with Horizontal(id="cols"):
                with Vertical(id="picker"):
                    yield SelectionList[int](
                        *[
                            Selection(
                                f"{c.mmss.replace('-', ':')}  {c.klass}",
                                c.index,
                                c.klass == "slide",
                            )
                            for c in self.candidates
                        ],
                        id="list",
                    )
                with Vertical(id="preview-pane"):
                    yield Static("", id="caption")
                    if HAS_INLINE_IMAGE:
                        yield TImage(id="preview")
                    else:
                        yield Static(
                            "[dim]Inline preview unavailable — press [b]o[/b] to "
                            "open the highlighted frame in your system viewer.[/dim]",
                            id="preview",
                        )
            with Horizontal(id="save-row"):
                yield Input(value=str(self.default_dest), id="dest",
                            placeholder="Destination folder")
                yield Button("Save", id="save", variant="success")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#list", SelectionList).focus()
        if self.candidates:
            self._show(self.candidates[0])

    # -- preview -------------------------------------------------------------
    def _show(self, c: Candidate) -> None:
        self.query_one("#caption", Static).update(
            f"frame {c.index:03d} · {c.mmss.replace('-', ':')} · {c.klass} · {c.path.name}"
        )
        if HAS_INLINE_IMAGE:
            self.query_one("#preview", TImage).image = str(c.path)

    @on(SelectionList.SelectionHighlighted, "#list")
    def _on_highlight(self, event: SelectionList.SelectionHighlighted) -> None:
        c = self.by_index.get(event.selection.value)
        if c:
            self._show(c)

    # -- actions -------------------------------------------------------------
    def action_all(self) -> None:
        self.query_one("#list", SelectionList).select_all()

    def action_none(self) -> None:
        self.query_one("#list", SelectionList).deselect_all()

    def action_open_external(self) -> None:
        idx = self.query_one("#list", SelectionList).highlighted
        if idx is None:
            return
        c = self.candidates[idx]
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen([opener, str(c.path)])
        except OSError:
            self.app.bell()

    @on(Button.Pressed, "#cancel")
    def _cancel_btn(self) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def _save_btn(self) -> None:
        self.action_save()

    def action_save(self) -> None:
        chosen_values = self.query_one("#list", SelectionList).selected
        chosen = [self.by_index[v] for v in chosen_values]
        if not chosen:
            self.notify("Nothing selected.", severity="warning")
            return
        dest = Path(self.query_one("#dest", Input).value.strip()).expanduser()
        result = curate.save_selected(chosen, dest)
        self.dismiss(result)
