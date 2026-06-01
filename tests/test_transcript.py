"""Tests for the SRT parsing + rolling-caption dedupe."""

from yt_tui.core import transcript

# A miniature version of YouTube's rolling auto-caption format: each cue repeats
# the previous text and tacks on a few new words.
ROLLING_SRT = """\
1
00:00:01,000 --> 00:00:02,000
Hello and welcome

2
00:00:02,000 --> 00:00:03,000
Hello and welcome to the show

3
00:00:03,000 --> 00:00:05,000
to the show today we

4
00:00:05,000 --> 00:00:07,000
today we talk about agents
"""


def test_parse_extracts_segments_with_times():
    segs = transcript.parse_srt(ROLLING_SRT)
    assert len(segs) == 4
    assert segs[0].start == 1.0
    assert segs[2].start == 3.0


def test_dedupe_removes_rolling_overlap():
    clean, _ = transcript.process(ROLLING_SRT)
    # Each phrase should appear exactly once, in order, with no duplication.
    assert clean == "Hello and welcome to the show today we talk about agents"
    assert clean.count("Hello and welcome") == 1
    assert clean.count("to the show") == 1


def test_mmss_formatting():
    seg = transcript.Segment(start=125.0, text="x")
    assert seg.mmss == "2:05"


def test_empty_input_is_safe():
    clean, segs = transcript.process("")
    assert clean == ""
    assert segs == []
