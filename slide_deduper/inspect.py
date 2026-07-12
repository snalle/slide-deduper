"""Part 1 - Inspect a PDF without modifying it.

The goal is to discover whether the original slide structure is already
stored in the file (bookmarks / page labels), so we can avoid image
comparison when a reliable signal exists.

The public entry point is :func:`inspect_pdf`, which returns a
:class:`PdfInspection` dataclass. A ``print_report`` helper reproduces the
human-readable output of the original standalone script.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class PageInfo:
    """Everything we learn about a single physical page."""

    index: int  # 0-based physical index
    label: str | None  # displayed page label, if any
    xref: int  # internal PDF object number
    text: str  # full extracted plain text
    title: str  # first non-empty line, used as a cheap "title"

    @property
    def number(self) -> int:
        """1-based physical page number (what a human sees)."""
        return self.index + 1

    @property
    def text_preview(self) -> str:
        flat = " ".join(self.text.split())
        return (flat[:100] + "...") if len(flat) > 100 else (flat or "[No extractable text]")


@dataclass
class PdfInspection:
    """Structured result of inspecting a PDF."""

    path: Path
    page_count: int
    pdf_format: str
    metadata: dict[str, str]
    bookmarks: list[tuple[int, str, int]]  # (level, title, 1-based page)
    page_label_rules: list  # raw rules from get_page_labels()
    pages: list[PageInfo] = field(default_factory=list)

    # --- derived signals -------------------------------------------------

    @property
    def has_bookmarks(self) -> bool:
        return len(self.bookmarks) > 0

    @property
    def has_page_labels(self) -> bool:
        return any(p.label for p in self.pages)

    @property
    def distinct_labels(self) -> int:
        return len({p.label for p in self.pages if p.label})

    def guess_logical_slide_count(self) -> int | None:
        """Best guess at the number of original slides, or None if unknown."""
        if self.has_bookmarks:
            # Top-level bookmarks are the most likely slide anchors.
            top = [b for b in self.bookmarks if b[0] == 1]
            return len(top) if top else len(self.bookmarks)
        if self.has_page_labels:
            return self.distinct_labels
        return None


def _extract_pages(document: fitz.Document) -> list[PageInfo]:
    pages: list[PageInfo] = []
    for i in range(document.page_count):
        page = document[i]
        text = page.get_text("text")
        title = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        try:
            label = page.get_label() or None
        except Exception:
            label = None
        pages.append(
            PageInfo(index=i, label=label, xref=page.xref, text=text, title=title)
        )
    return pages


def inspect_pdf(pdf_path: str | Path) -> PdfInspection:
    """Open a PDF read-only and gather structural information about it."""

    pdf_path = Path(pdf_path)
    document = fitz.open(pdf_path)
    try:
        metadata = {k: v for k, v in (document.metadata or {}).items() if v}
        try:
            label_rules = document.get_page_labels()
        except Exception:
            label_rules = []

        return PdfInspection(
            path=pdf_path,
            page_count=document.page_count,
            pdf_format=(document.metadata or {}).get("format", "Unknown"),
            metadata=metadata,
            bookmarks=[
                (level, title, page) for level, title, page in document.get_toc()
            ],
            page_label_rules=label_rules,
            pages=_extract_pages(document),
        )
    finally:
        document.close()


# ---------------------------------------------------------------------------
# Human-readable report (mirrors the original standalone script)
# ---------------------------------------------------------------------------

def _section(title: str) -> str:
    return "\n" + "=" * 70 + f"\n{title}\n" + "=" * 70


def format_report(info: PdfInspection) -> str:
    lines: list[str] = []

    lines.append(_section("PDF SUMMARY"))
    lines.append(f"File:           {info.path}")
    lines.append(f"Physical pages: {info.page_count}")
    lines.append(f"PDF format:     {info.pdf_format}")

    lines.append(_section("1. PDF METADATA"))
    if info.metadata:
        for key, value in info.metadata.items():
            lines.append(f"{key:15}: {value}")
    else:
        lines.append("No metadata found.")

    lines.append(_section("2. BOOKMARKS / TABLE OF CONTENTS"))
    if info.bookmarks:
        lines.append(f"Number of bookmark entries: {len(info.bookmarks)}\n")
        for level, title, page in info.bookmarks:
            indent = "  " * (level - 1)
            lines.append(f"{indent}Level {level} | PDF page {page:3} | {title}")
    else:
        lines.append("No bookmarks found.")

    lines.append(_section("3. PAGE-LABEL RULES"))
    if info.page_label_rules:
        lines.append(f"Number of page-label rules: {len(info.page_label_rules)}\n")
        for rule in info.page_label_rules:
            lines.append(str(rule))
    else:
        lines.append("No custom page-label rules found.")

    lines.append(_section("4. LABEL OF EVERY PAGE"))
    if info.has_page_labels:
        for p in info.pages:
            lines.append(f"Physical page {p.number:3} -> label: {p.label!r}")
    else:
        for p in info.pages:
            lines.append(f"Physical page {p.number:3} -> label: {p.label!r}")
        lines.append("\nNo page labels were assigned.")

    lines.append(_section("5. TEXT PREVIEW FOR EVERY PAGE"))
    for p in info.pages:
        lines.append(f"Page {p.number:3}: {p.text_preview}")

    lines.append(_section("6. INTERNAL PAGE OBJECTS"))
    for p in info.pages:
        lines.append(f"Physical page {p.number:3} -> PDF object {p.xref}")

    lines.append(_section("INITIAL INTERPRETATION"))
    lines.append(f"Physical pages:       {info.page_count}")
    lines.append(f"Bookmark entries:     {len(info.bookmarks)}")
    lines.append(f"Page-label rules:     {len(info.page_label_rules)}")
    guess = info.guess_logical_slide_count()
    lines.append("")
    if info.has_bookmarks:
        lines.append(
            f"Bookmarks present -> slide boundaries likely stored in the file "
            f"(estimated {guess} slides). Image comparison probably not needed."
        )
    elif info.has_page_labels:
        lines.append(
            f"Repeated page labels present -> group by label "
            f"(estimated {guess} distinct labels)."
        )
    else:
        lines.append(
            "No bookmarks or page labels -> slide boundaries must be detected "
            "from text and/or rendered images."
        )
    return "\n".join(lines)


def print_report(info: PdfInspection) -> None:
    print(format_report(info))
