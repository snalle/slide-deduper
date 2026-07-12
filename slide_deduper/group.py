"""Part 2 - Group physical pages that belong to the same original slide.

Detection methods, tried in order of reliability:

1. bookmarks       - each bookmark destination starts a new slide.
2. labels          - consecutive pages sharing a logical page label.
3. text            - a page whose text is a superset (expanded build) of
                     the previous page's text.
4. visual          - render pages and check whether page N+1 mostly
                     preserves page N while adding ink (incremental build).

Every group keeps the LAST page (the fully built-up version).
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from difflib import SequenceMatcher

from .inspect import PdfInspection, PageInfo


@dataclass
class SlideGroup:
    """A run of consecutive physical pages forming one final slide."""

    pages: list[int]  # 1-based physical page numbers, in order
    method: str  # which detector produced this grouping
    confidence: float = 1.0  # 0..1, how sure we are of the boundary

    @property
    def start(self) -> int:
        return self.pages[0]

    @property
    def end(self) -> int:
        return self.pages[-1]

    @property
    def keep(self) -> int:
        """The page to keep: the last (most complete) page in the group."""
        return self.pages[-1]

    def __str__(self) -> str:
        span = f"{self.start}" if self.start == self.end else f"{self.start}-{self.end}"
        return f"PDF pages {span} -> keep page {self.keep}"


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

# Matches Beamer-style navigation footers such as "3 / 43" or "12/73" that
# change on every build page and would otherwise defeat text comparison.
_FOOTER_PAGENUM = re.compile(r"\b\d+\s*/\s*\d+\b")


def _strip_footer_noise(text: str) -> str:
    """Remove per-page counters that change between builds of the same slide.

    Currently strips "N / M" page indicators. Kept deliberately narrow so it
    doesn't accidentally erase real content like fractions in formulas — those
    are far rarer than slide-number footers in presentation decks, but if a
    deck uses many inline fractions this is the knob to revisit.
    """
    return _FOOTER_PAGENUM.sub(" ", text)


def _normalize(text: str) -> str:
    return " ".join(_strip_footer_noise(text).lower().split())


def _tokens(text: str) -> set[str]:
    return set(_normalize(text).split())


def _is_expansion(prev: PageInfo, curr: PageInfo, threshold: float) -> tuple[bool, float]:
    """Is ``curr`` an expanded build of ``prev``?

    True when they share the same title and ``prev``'s words are largely a
    subset of ``curr``'s words (content was added, not replaced).

    Returns (is_expansion, similarity_score).
    """
    prev_title = _normalize(prev.title)
    curr_title = _normalize(curr.title)

    # Different, non-empty titles almost always mean a genuinely new slide.
    if prev_title and curr_title and prev_title != curr_title:
        title_sim = SequenceMatcher(None, prev_title, curr_title).ratio()
        if title_sim < 0.75:
            return False, title_sim

    prev_tokens = _tokens(prev.text)
    curr_tokens = _tokens(curr.text)

    if not prev_tokens:
        # Empty previous page: treat identical-title blank builds as same slide.
        same_title = bool(prev_title) and prev_title == curr_title
        return same_title, 1.0 if same_title else 0.0

    kept = prev_tokens & curr_tokens
    coverage = len(kept) / len(prev_tokens)  # how much of prev survives in curr
    grew = len(curr_tokens) >= len(prev_tokens)

    is_exp = coverage >= threshold and grew
    return is_exp, coverage


# ---------------------------------------------------------------------------
# Detection methods
# ---------------------------------------------------------------------------

def group_by_bookmarks(info: PdfInspection) -> list[SlideGroup] | None:
    if not info.has_bookmarks:
        return None

    # Use top-level bookmarks if present, else all of them.
    top = [b for b in info.bookmarks if b[0] == 1]
    marks = top or info.bookmarks

    starts = sorted({page for _, _, page in marks if 1 <= page <= info.page_count})
    if not starts:
        return None
    if starts[0] != 1:
        starts = [1] + starts

    # Plausibility guard. Bookmarks are only slide boundaries if there are
    # roughly as many of them as there are slides. A handful of bookmarks in a
    # large deck almost always marks *sections*, not slides, and trusting them
    # collapses dozens of pages into a few huge groups. Heuristic: reject when
    # the average pages-per-group is implausibly high (i.e. each "slide" would
    # span many pages). Real incremental builds rarely exceed ~15 pages.
    avg_pages_per_group = info.page_count / len(starts)
    if len(starts) < 3 or avg_pages_per_group > 12:
        return None

    groups: list[SlideGroup] = []
    for i, start in enumerate(starts):
        end = (starts[i + 1] - 1) if i + 1 < len(starts) else info.page_count
        groups.append(
            SlideGroup(pages=list(range(start, end + 1)), method="bookmarks")
        )
    return groups


def group_by_labels(info: PdfInspection) -> list[SlideGroup] | None:
    if not info.has_page_labels:
        return None

    groups: list[SlideGroup] = []
    run = [info.pages[0]]
    for prev, curr in zip(info.pages, info.pages[1:]):
        if curr.label is not None and curr.label == prev.label:
            run.append(curr)
        else:
            groups.append(
                SlideGroup(pages=[p.number for p in run], method="labels")
            )
            run = [curr]
    groups.append(SlideGroup(pages=[p.number for p in run], method="labels"))
    return groups


def group_by_text(info: PdfInspection, threshold: float = 0.85) -> list[SlideGroup]:
    groups: list[SlideGroup] = []
    run = [info.pages[0]]
    run_conf = 1.0
    for prev, curr in zip(info.pages, info.pages[1:]):
        is_exp, score = _is_expansion(prev, curr, threshold)
        if is_exp:
            run.append(curr)
            run_conf = min(run_conf, score)
        else:
            groups.append(
                SlideGroup([p.number for p in run], "text", round(run_conf, 3))
            )
            run = [curr]
            run_conf = 1.0
    groups.append(SlideGroup([p.number for p in run], "text", round(run_conf, 3)))
    return groups


def group_by_visual(
    info: PdfInspection,
    threshold: float = 0.85,
    dpi: int = 72,
) -> list[SlideGroup]:
    """Group by rendered-image similarity.

    Heuristic for an incremental build: render both pages to grayscale at
    the same size and check what fraction of the earlier page's dark pixels
    are still dark on the next page (preservation), while the next page has
    at least as much ink (growth).
    """
    import fitz

    doc = fitz.open(info.path)
    try:
        rendered: list[tuple[bytes, int, int]] = []
        for i in range(doc.page_count):
            pix = doc[i].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
            rendered.append((pix.samples, pix.width, pix.height))
    finally:
        doc.close()

    def dark_mask(sample: tuple[bytes, int, int], thresh: int = 200) -> tuple[frozenset[int], int]:
        data, w, h = sample
        dark = {i for i, v in enumerate(data) if v < thresh}
        return frozenset(dark), w * h

    groups: list[SlideGroup] = []
    run = [info.pages[0]]
    run_conf = 1.0
    prev_mask, prev_size = dark_mask(rendered[0])

    for idx in range(1, len(info.pages)):
        curr_mask, curr_size = dark_mask(rendered[idx])

        if prev_size != curr_size or not prev_mask:
            preserved = 0.0
        else:
            preserved = len(prev_mask & curr_mask) / len(prev_mask)
        grew = len(curr_mask) >= len(prev_mask) * 0.98

        if preserved >= threshold and grew and prev_size == curr_size:
            run.append(info.pages[idx])
            run_conf = min(run_conf, preserved)
        else:
            groups.append(
                SlideGroup([p.number for p in run], "visual", round(run_conf, 3))
            )
            run = [info.pages[idx]]
            run_conf = 1.0
        prev_mask, prev_size = curr_mask, curr_size

    groups.append(SlideGroup([p.number for p in run], "visual", round(run_conf, 3)))
    return groups


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_METHODS = ("bookmarks", "labels", "text", "visual")


def group_pages(
    info: PdfInspection,
    method: str = "auto",
    threshold: float = 0.85,
) -> list[SlideGroup]:
    """Group pages using the chosen method, or auto-select the best one."""

    if method not in _METHODS + ("auto",):
        raise ValueError(f"Unknown method {method!r}; choose from {_METHODS} or 'auto'.")

    if method == "bookmarks":
        return group_by_bookmarks(info) or [
            SlideGroup([p.number], "bookmarks", 0.0) for p in info.pages
        ]
    if method == "labels":
        return group_by_labels(info) or [
            SlideGroup([p.number], "labels", 0.0) for p in info.pages
        ]
    if method == "text":
        return group_by_text(info, threshold)
    if method == "visual":
        return group_by_visual(info, threshold)

    # auto: prefer structural signals, fall back to content signals.
    return (
        group_by_bookmarks(info)
        or group_by_labels(info)
        or group_by_text(info, threshold)
    )


def format_groups(groups: list[SlideGroup]) -> str:
    lines = []
    for i, g in enumerate(groups, 1):
        conf = "" if g.confidence >= 0.999 else f"  (confidence {g.confidence:.2f})"
        lines.append(f"Slide group {i}: {g}{conf}")
    return "\n".join(lines)


def suggest_splits(
    info: PdfInspection,
    groups: list[SlideGroup],
    title_similarity: float = 0.5,
) -> list[tuple[int, int, str]]:
    """Find pages that likely start a new slide despite being grouped.

    Some decks put a genuinely new subject on the same page label (or otherwise
    let it group with the previous slide's final build). Those pages have a
    title that differs sharply from the page before them. This scans inside
    each multi-page group and flags such internal title changes as *candidate*
    split points - it does not modify the grouping.

    Returns a list of (group_index, page_number, new_title) tuples, where
    group_index is 1-based (matching the report) and page_number is where a
    new slide probably begins. Feed the page numbers to --split to apply them.

    ``title_similarity`` is the cutoff below which two consecutive titles count
    as "different"; lower = more conservative (fewer suggestions).
    """
    by_page = {p.number: p for p in info.pages}
    suggestions: list[tuple[int, int, str]] = []

    for gi, group in enumerate(groups, 1):
        if len(group.pages) < 2:
            continue
        for prev_pg, curr_pg in zip(group.pages, group.pages[1:]):
            prev = by_page.get(prev_pg)
            curr = by_page.get(curr_pg)
            if not prev or not curr:
                continue
            prev_title = _normalize(prev.title)
            curr_title = _normalize(curr.title)
            if not prev_title or not curr_title:
                continue
            sim = SequenceMatcher(None, prev_title, curr_title).ratio()
            if sim < title_similarity:
                suggestions.append((gi, curr_pg, curr.title.strip()))
    return suggestions


def format_split_suggestions(suggestions: list[tuple[int, int, str]]) -> str:
    """Render split suggestions as a short, copy-pasteable hint block."""
    if not suggestions:
        return ""
    lines = ["", "Possible missed slide boundaries (title changes inside a group):"]
    for gi, page, title in suggestions:
        preview = title if len(title) <= 50 else title[:50] + "..."
        lines.append(f"  group {gi}: page {page} looks like a new slide - {preview!r}")
    pages = ",".join(str(p) for _, p, _ in suggestions)
    lines.append(f"To apply all: --split {pages}")
    return "\n".join(lines)
