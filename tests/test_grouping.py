"""Tests for slide-deduper grouping and dedupe logic.

Run:  python3 -m pytest tests/   (or)   python3 tests/test_grouping.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from slide_deduper.inspect import inspect_pdf
from slide_deduper.group import (
    group_by_bookmarks,
    group_by_text,
    group_by_visual,
    group_pages,
)
from slide_deduper.dedupe import dedupe_pdf


def _add(doc, title, bullets):
    page = doc.new_page(width=720, height=540)
    page.insert_text((60, 80), title, fontsize=28)
    y = 150
    for b in bullets:
        page.insert_text((80, y), "\u2022 " + b, fontsize=18)
        y += 40


def _make_deck(path: Path, with_bookmarks: bool = False):
    doc = fitz.open()
    _add(doc, "Introduction", ["A"])
    _add(doc, "Introduction", ["A", "B"])
    _add(doc, "Introduction", ["A", "B", "C"])
    _add(doc, "Methodology", ["Step 1"])
    _add(doc, "Methodology", ["Step 1", "Step 2"])
    _add(doc, "Conclusion", ["Done"])
    if with_bookmarks:
        doc.set_toc([[1, "Introduction", 1], [1, "Methodology", 4], [1, "Conclusion", 6]])
    doc.save(path)
    doc.close()


EXPECTED = [(1, 3, 3), (4, 5, 5), (6, 6, 6)]  # (start, end, keep)


def _check(groups):
    assert len(groups) == 3, f"expected 3 groups, got {len(groups)}"
    for g, (s, e, k) in zip(groups, EXPECTED):
        assert (g.start, g.end, g.keep) == (s, e, k), f"{g} != {(s, e, k)}"


def test_bookmarks():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        _make_deck(p, with_bookmarks=True)
        _check(group_by_bookmarks(inspect_pdf(p)))


def test_text():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        _make_deck(p)
        _check(group_by_text(inspect_pdf(p)))


def test_visual():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        _make_deck(p)
        _check(group_by_visual(inspect_pdf(p)))


def test_auto_prefers_bookmarks():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        _make_deck(p, with_bookmarks=True)
        groups = group_pages(inspect_pdf(p), method="auto")
        assert groups[0].method == "bookmarks"
        _check(groups)


def test_sparse_bookmarks_rejected():
    """Few bookmarks in a large deck are sections, not slides - must be ignored."""
    from slide_deduper.inspect import PdfInspection, PageInfo
    from slide_deduper.group import group_by_bookmarks

    pages = [PageInfo(index=i, label=None, xref=i, text="", title="") for i in range(81)]
    info = PdfInspection(
        path=Path("x"),
        page_count=81,
        pdf_format="",
        metadata={},
        bookmarks=[(1, "A", 1), (1, "B", 27), (1, "C", 53)],
        page_label_rules=[],
        pages=pages,
    )
    assert group_by_bookmarks(info) is None


def test_beamer_footer_does_not_split_builds():
    """Pages that build up but carry a changing 'N / M' footer stay grouped."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        doc = fitz.open()
        # Two builds of one slide, each with a different page-number footer.
        for i, body in enumerate([["Point one"], ["Point one", "Point two"]], start=3):
            page = doc.new_page(width=720, height=540)
            page.insert_text((60, 80), "Entailment", fontsize=24)
            y = 150
            for b in body:
                page.insert_text((80, y), "\u2022 " + b, fontsize=16)
                y += 40
            page.insert_text((70, 510), f"Author (SDU)  AI  {i} / 43", fontsize=9)
        doc.save(p)
        doc.close()

        groups = group_by_text(inspect_pdf(p))
        assert len(groups) == 1, f"footer split a build: {[str(g) for g in groups]}"
        assert groups[0].keep == 2


def test_output_pdf_has_one_page_per_slide():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        out = Path(d) / "final.pdf"
        _make_deck(p, with_bookmarks=True)
        info = inspect_pdf(p)
        groups = group_pages(info, method="auto")
        result = dedupe_pdf(info, groups, "auto", out, dry_run=False)
        assert result.kept_count == 3
        assert result.removed_pages == [1, 2, 4]
        assert fitz.open(out).page_count == 3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("\nAll tests passed.")