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


from PIL import Image


def _solid(tmp_path, name, color, size=(200, 200)):
    p = tmp_path / name
    Image.new("RGB", size, color).save(p)
    return p


def test_ahash_identical_images_zero_distance(tmp_path):
    a = _solid(tmp_path, "a.png", (123, 200, 50))
    b = _solid(tmp_path, "b.png", (123, 200, 50))
    assert slides._hamming(slides._ahash(a), slides._ahash(b)) == 0


def test_ahash_distinguishes_structured_images(tmp_path):
    # left-half-white vs right-half-white: differ in the center region
    left = Image.new("L", (200, 200), 0)
    for x in range(100):
        for y in range(200):
            left.putpixel((x, y), 255)
    lp = tmp_path / "left.png"; left.save(lp)
    rp = tmp_path / "right.png"; left.transpose(Image.FLIP_LEFT_RIGHT).save(rp)
    assert slides._hamming(slides._ahash(lp), slides._ahash(rp)) > 10


def test_ahash_ignores_top_banner(tmp_path):
    # identical content region, different top strip → still near-zero distance
    base = Image.new("RGB", (200, 200), (10, 20, 180))
    a = base.copy(); b = base.copy()
    for x in range(200):           # paint only b's top 15% a different colour
        for y in range(30):
            b.putpixel((x, y), (255, 0, 0))
    ap = tmp_path / "a.png"; a.save(ap)
    bp = tmp_path / "b.png"; b.save(bp)
    assert slides._hamming(slides._ahash(ap), slides._ahash(bp)) <= 2
