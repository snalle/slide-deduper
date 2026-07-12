"""Tests for slide-deduper's grouping and dedupe logic.

The tool's job is to take a slide PDF where each animation step ("build") is a
separate page, and collapse each run of build-up pages down to its final,
fully-built page. These tests check that each detection method finds the right
slide boundaries, and that manual corrections behave.

Most tests share one synthetic deck built by ``_make_deck`` (see its docstring
for the exact layout). It is deliberately tiny but exercises the three shapes
that matter: a multi-build slide, a shorter multi-build slide, and a single
non-build slide.

Run:  python3 -m pytest tests/      (with pytest installed)
  or: python3 tests/test_grouping.py  (no dependencies beyond the package)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF, used here only to synthesise test PDFs

# Allow running this file directly (python tests/test_grouping.py) by putting
# the project root on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from slide_deduper.inspect import inspect_pdf
from slide_deduper.group import (
    group_by_bookmarks,
    group_by_text,
    group_by_visual,
    group_pages,
)
from slide_deduper.dedupe import dedupe_pdf


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _add(doc, title, bullets):
    """Append one page: a title plus a list of bullet lines.

    Adding more bullets on a later page with the same title simulates one
    animation step of an incremental-build slide.
    """
    page = doc.new_page(width=720, height=540)
    page.insert_text((60, 80), title, fontsize=28)
    y = 150
    for b in bullets:
        page.insert_text((80, y), "\u2022 " + b, fontsize=18)
        y += 40


def _make_deck(path: Path, with_bookmarks: bool = False):
    """Build the shared 6-page test deck representing 3 logical slides.

    Physical pages -> logical slides:
        pages 1-3  "Introduction"  bullets grow  A -> A,B -> A,B,C   (3 builds)
        pages 4-5  "Methodology"   bullets grow  Step1 -> Step1,Step2 (2 builds)
        page  6    "Conclusion"    single page, no build

    So the correct result is always 3 groups, keeping the last (most complete)
    page of each: pages 3, 5, and 6.

    When ``with_bookmarks`` is set, a bookmark is placed at the FIRST page of
    each logical slide (1, 4, 6) - i.e. the structure the detectors must
    recover. This lets one fixture drive both the structural-signal tests
    (bookmarks) and the content-signal tests (text, visual): the text and
    visual detectors ignore bookmarks and must infer the same boundaries from
    the growing bullet lists alone.
    """
    doc = fitz.open()
    _add(doc, "Introduction", ["A"])
    _add(doc, "Introduction", ["A", "B"])
    _add(doc, "Introduction", ["A", "B", "C"])
    _add(doc, "Methodology", ["Step 1"])
    _add(doc, "Methodology", ["Step 1", "Step 2"])
    _add(doc, "Conclusion", ["Done"])
    if with_bookmarks:
        # PyMuPDF TOC entries: [level, title, 1-based start page].
        doc.set_toc([[1, "Introduction", 1], [1, "Methodology", 4], [1, "Conclusion", 6]])
    doc.save(path)
    doc.close()


# The one correct grouping of the shared deck, as (start, end, keep) triples of
# 1-based physical page numbers. Every detection method should reproduce this.
EXPECTED = [(1, 3, 3), (4, 5, 5), (6, 6, 6)]


def _check(groups):
    """Assert ``groups`` matches EXPECTED exactly (count and each boundary)."""
    assert len(groups) == 3, f"expected 3 groups, got {len(groups)}"
    for g, (s, e, k) in zip(groups, EXPECTED):
        # start/end delimit the build run; keep is the page we retain (the last).
        assert (g.start, g.end, g.keep) == (s, e, k), f"{g} != {(s, e, k)}"


# ---------------------------------------------------------------------------
# One test per detection method: each must recover the same 3-slide structure
# ---------------------------------------------------------------------------

def test_bookmarks():
    """Bookmarks at each slide's first page define the boundaries directly."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        _make_deck(p, with_bookmarks=True)
        _check(group_by_bookmarks(inspect_pdf(p)))


def test_text():
    """With no bookmarks, grouping must be inferred from text.

    Each build repeats the previous page's bullets and adds more, so a page's
    words are a superset of the previous page's - that "expansion" is what the
    text detector keys on to decide two pages are the same slide.
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        _make_deck(p)  # no bookmarks
        _check(group_by_text(inspect_pdf(p)))


def test_visual():
    """With no bookmarks, grouping must be inferred from rendered images.

    A build preserves the previous page's pixels and adds ink (the new
    bullet), so the visual detector treats it as the same slide. This checks
    the image-based path reaches the same answer as the text path.
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        _make_deck(p)  # no bookmarks
        _check(group_by_visual(inspect_pdf(p)))


def test_auto_prefers_bookmarks():
    """'auto' must pick the most reliable available signal.

    When bookmarks exist, auto should use them (method == 'bookmarks') rather
    than falling through to the content-based detectors.
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        _make_deck(p, with_bookmarks=True)
        groups = group_pages(inspect_pdf(p), method="auto")
        assert groups[0].method == "bookmarks"
        _check(groups)


# ---------------------------------------------------------------------------
# Regression tests: each pins a bug found on real lecture decks
# ---------------------------------------------------------------------------

def test_sparse_bookmarks_rejected():
    """A handful of bookmarks in a large deck are section headings, not slides.

    Real decks exported from PowerPoint/Beamer sometimes carry only a few
    top-level bookmarks (e.g. 3 chapter headings in an 81-page deck). Trusting
    them as slide boundaries would collapse dozens of pages into a few huge
    groups. The detector must reject such implausibly-sparse bookmarks (here:
    3 bookmarks / 81 pages) and return None so grouping falls through to a
    content-based method.
    """
    from slide_deduper.inspect import PdfInspection, PageInfo
    from slide_deduper.group import group_by_bookmarks

    # 81 blank pages with 3 section bookmarks at pages 1, 27, 53.
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
    assert group_by_bookmarks(info) is None  # rejected as too sparse


def test_duplicate_pages_merged():
    """Exact-duplicate pages straddling a label boundary collapse to one slide.

    Some exporters emit the final built slide more than once. Here pages 2 and 3
    are identical but carry different labels ("B" then "C"), so the label
    detector puts them in separate groups. The duplicate-merge pass must detect
    the identical boundary pages and merge them, keeping only the later copy.
    """
    from slide_deduper.inspect import PdfInspection, PageInfo
    from slide_deduper.group import group_pages

    #      page: 1        2                3                4
    #     label: A        B                C                D
    #      text: intro    Repeated slide   Repeated slide   outro
    texts = ["Intro", "Repeated slide", "Repeated slide", "Outro"]
    labels = ["A", "B", "C", "D"]
    pages = [
        PageInfo(index=i, label=labels[i], xref=i, text=texts[i], title=texts[i])
        for i in range(4)
    ]
    info = PdfInspection(
        path=Path("x"), page_count=4, pdf_format="", metadata={},
        bookmarks=[], page_label_rules=["x"], pages=pages,
    )
    keeps = [g.keep for g in group_pages(info, method="labels")]
    # Labels alone give one group per page: keeps [1, 2, 3, 4]. Pages 2 and 3
    # are identical duplicates, so they merge into one slide (keep 3); pages 1
    # and 4 are distinct. Result: [1, 3, 4].
    assert keeps == [1, 3, 4]
    assert 2 not in keeps  # the earlier duplicate is dropped


def test_beamer_footer_does_not_split_builds():
    """A changing 'N / M' page-number footer must not break build grouping.

    Beamer decks print a footer like "Author (SDU)  AI  3 / 43" whose number
    changes on every page. Naively, that changing number makes two builds of
    one slide look like different pages and splits them. The text detector
    strips such footers before comparing, so the two builds below (same title,
    growing bullets, only the footer number differs) must stay a single group.
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        doc = fitz.open()
        # Two builds of ONE slide; only the footer's "i / 43" differs between them.
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
        assert groups[0].keep == 2  # keep the fully-built second page


# ---------------------------------------------------------------------------
# Manual correction
# ---------------------------------------------------------------------------

def test_suggest_splits_finds_title_change():
    """suggest_splits flags a new-subject page hidden inside a shared-label run.

    Two cases are checked, both inside one shared-label group:
    - a sharply different title ("Remarks" -> "Task Environment Specification")
    - titles that share a trailing word but are still different topics
      ("Evaluating Algorithms" -> "Uninformed Search Algorithms"). This second
      case is why title similarity is measured by word overlap, not characters:
      the shared word "Algorithms" would fool a character-level comparison.
    """
    from slide_deduper.inspect import PdfInspection, PageInfo
    from slide_deduper.group import group_by_labels, suggest_splits

    titles = [
        "Remarks", "Remarks", "Task Environment Specification",
        "Evaluating Algorithms", "Uninformed Search Algorithms",
    ]
    pages = [
        PageInfo(index=i, label="9", xref=i, text=titles[i], title=titles[i])
        for i in range(len(titles))
    ]
    info = PdfInspection(
        path=Path("x"), page_count=len(titles), pdf_format="", metadata={},
        bookmarks=[], page_label_rules=["x"], pages=pages,
    )
    groups = group_by_labels(info)
    suggestions = suggest_splits(info, groups)
    flagged_pages = [page for _, page, _ in suggestions]
    # Page 3 (Task Environment) and page 5 (Uninformed Search) are new topics.
    assert 3 in flagged_pages
    assert 5 in flagged_pages


def test_manual_split_starts_new_group():
    """--split must force a new slide even when pages share a page label.

    Occasionally a genuinely new subject shares a logical page label with the
    previous slide's final build (seen on a real deck: pages 19-27 all labelled
    "9", but 27 was a new topic). Automatic grouping correctly follows the
    label and merges them; --split lets the user override by naming the page
    where a new slide should start.

    Here all four pages share label "9" (one group by default). Splitting at
    page 4 must yield two groups - pages 1-3 (keep 3) and page 4 (keep 4).
    """
    from slide_deduper.inspect import PdfInspection, PageInfo
    from slide_deduper.group import group_by_labels
    from slide_deduper.cli import _parse_split_spec

    pages = [
        PageInfo(index=i, label="9", xref=i, text="", title="") for i in range(4)
    ]
    info = PdfInspection(
        path=Path("x"), page_count=4, pdf_format="", metadata={},
        bookmarks=[], page_label_rules=["x"], pages=pages,
    )
    groups = group_by_labels(info)
    assert [g.keep for g in groups] == [4]  # shared label -> single group

    split = _parse_split_spec("4", groups, "labels")
    assert [g.keep for g in split] == [3, 4]  # split into 1-3 and 4


# ---------------------------------------------------------------------------
# End-to-end: the produced PDF actually contains the kept pages
# ---------------------------------------------------------------------------

def test_output_pdf_has_one_page_per_slide():
    """Full pipeline: grouping -> written PDF has exactly one page per slide.

    Beyond checking the grouping, this verifies the writer copies the right
    pages: 3 slides kept, pages 1/2/4 (the intermediate builds) removed, and
    the output PDF is exactly 3 pages long.
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "deck.pdf"
        out = Path(d) / "final.pdf"
        _make_deck(p, with_bookmarks=True)
        info = inspect_pdf(p)
        groups = group_pages(info, method="auto")
        result = dedupe_pdf(info, groups, "auto", out, dry_run=False)
        assert result.kept_count == 3
        assert result.removed_pages == [1, 2, 4]  # the non-final builds
        assert fitz.open(out).page_count == 3


# ---------------------------------------------------------------------------
# Minimal runner so the suite works without pytest installed.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("\nAll tests passed.")