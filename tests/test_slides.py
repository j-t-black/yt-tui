"""Tests for slide sampling + dedupe helpers."""

from yt_tui.core import slides


def test_dedupe_by_hash_collapses_identical_run():
    # four identical frames then a clearly different one
    hashes = [0b0000, 0b0000, 0b0000, 0b1111]
    assert slides.dedupe_by_hash(hashes, threshold=1) == [0, 3]


def test_dedupe_by_hash_keeps_all_distinct():
    hashes = [0b0000, 0b0011, 0b1100, 0b1111]  # each >1 bit from the last kept
    assert slides.dedupe_by_hash(hashes, threshold=1) == [0, 1, 2, 3]


def test_dedupe_by_hash_keep_on_doubt_boundary():
    # distance exactly == threshold is a duplicate (drop); > threshold is kept
    assert slides.dedupe_by_hash([0b000, 0b001], threshold=1) == [0]      # dist 1 == thr → drop
    assert slides.dedupe_by_hash([0b000, 0b011], threshold=1) == [0, 1]   # dist 2 > thr → keep


def test_dedupe_by_hash_compares_against_last_kept_not_previous():
    # slow drift: each step is 1 bit from the prior frame but accumulates;
    # comparing to last *kept* keeps frames once drift exceeds threshold.
    hashes = [0b0000, 0b0001, 0b0011, 0b0111]
    # comparing to last *kept* keeps index 2 (dist 2 from kept 0b0000) but drops
    # index 1 and 3 (each only 1 bit from the last kept); previous-frame
    # comparison would instead drop index 2, so [0, 2] proves last-kept logic.
    assert slides.dedupe_by_hash(hashes, threshold=1) == [0, 2]


def test_dedupe_by_hash_empty():
    assert slides.dedupe_by_hash([], threshold=6) == []
