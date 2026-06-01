# yt-tui

A terminal UI for turning YouTube videos into clean transcripts, tailored markdown
reports, and extracted slide decks — built with [Textual](https://textual.textualize.io/).

Auto-captions give you the words; they don't give you the *slides*. For talks and
lectures the diagrams, rubrics, tables and demo screenshots are often the most
useful thing in the video. `yt-tui` pulls all three: transcript, report, and the
slide figures (via scene detection + a guided curation step).

## Features

- **Ingest** — metadata + auto-captions via `yt-dlp`, no full download.
- **Transcript** — cleans YouTube's redundant rolling-window captions into readable text.
- **Report** — a markdown report with frontmatter, sections (using chapter markers), and the cleaned transcript.
- **Slides** — downloads the video, scene-detects candidate frames with real timestamps, auto-classifies slide-vs-stage by brightness, then opens an in-TUI **curation screen**: a checklist of candidates with a live image preview, so you keep the real slides and save them — named by timestamp — without leaving the terminal.

## Requirements

- Python ≥ 3.10
- [`ffmpeg`](https://ffmpeg.org/) on your `PATH` (for slide extraction) — `brew install ffmpeg`
- `yt-dlp` is installed automatically as a dependency.

## Install

```bash
cd yt-tui
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

Launch the TUI:

```bash
yt-tui
```

Paste a URL, hit **Fetch**, then **Write report** or **Extract slides**. Long jobs
run in background workers so the UI stays responsive; progress streams to the log pane.

**Extract slides** runs the pipeline and then opens the curation screen:

- left — a checklist of candidate frames, pre-ticked for the ones auto-classed as slides
- right — a live preview of the highlighted frame (real inline graphics in iTerm2 / Kitty / Ghostty; unicode half-blocks elsewhere; press `o` to open in the system viewer)
- `space` toggle · `↑↓` preview · `a` all · `z` none · `Ctrl+S` save · `Esc` cancel

Saved slides land in `<reports-dir>/<title> - slides/`, named `MM-SS.png`.

### Headless subcommands

Handy for scripting:

```bash
yt-tui transcript "https://youtube.com/watch?v=..."     # print cleaned transcript
yt-tui report     "https://youtube.com/watch?v=..."     # write a markdown report
yt-tui slides     "https://youtube.com/watch?v=..." --out ./output/slides
```

After `slides`, open the `contact_*.png` grids it produced, pick the genuinely
unique slides (scene detection over-captures camera cuts and demo motion), and
copy the keepers out with descriptive `MM-SS_topic.png` names. `manifest.tsv` maps
every candidate frame to its timestamp.

## Layout

```
src/yt_tui/
├── app.py            # the Textual TUI
├── screens.py        # the slide-curation modal screen
├── __main__.py       # CLI entry (TUI + headless subcommands)
└── core/             # UI-independent logic
    ├── ingest.py     # yt-dlp metadata + captions
    ├── transcript.py # SRT parse + rolling-caption dedupe
    ├── report.py     # markdown assembly
    ├── slides.py     # scene detection + classification + contact sheets
    └── curate.py     # save the picked slides, named by timestamp
```

## Tests

```bash
pytest
```

## License

MIT
