"""Part 3 core - produce the reduced PDF and reports.

Pages are copied directly from the source document, so quality is preserved
exactly (no re-rendering).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import fitz

from .inspect import PdfInspection
from .group import SlideGroup


@dataclass
class DedupeResult:
    method: str
    total_pages: int
    kept_pages: list[int]  # 1-based
    removed_pages: list[int]  # 1-based
    groups: list[SlideGroup]
    output_path: Path | None  # None in dry-run

    @property
    def removed_count(self) -> int:
        return len(self.removed_pages)

    @property
    def kept_count(self) -> int:
        return len(self.kept_pages)


def compute_result(
    info: PdfInspection,
    groups: list[SlideGroup],
    method: str,
    output_path: Path | None,
) -> DedupeResult:
    kept = [g.keep for g in groups]
    kept_set = set(kept)
    removed = [p for p in range(1, info.page_count + 1) if p not in kept_set]
    return DedupeResult(
        method=method,
        total_pages=info.page_count,
        kept_pages=kept,
        removed_pages=removed,
        groups=groups,
        output_path=output_path,
    )


def write_reduced_pdf(info: PdfInspection, result: DedupeResult, output_path: Path) -> None:
    """Copy the kept pages, in order, into a new PDF."""
    src = fitz.open(info.path)
    out = fitz.open()
    try:
        for page_number in result.kept_pages:  # 1-based
            idx = page_number - 1
            out.insert_pdf(src, from_page=idx, to_page=idx)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out.save(output_path, garbage=4, deflate=True)
    finally:
        out.close()
        src.close()


def dedupe_pdf(
    info: PdfInspection,
    groups: list[SlideGroup],
    method: str,
    output_path: str | Path | None,
    dry_run: bool = False,
) -> DedupeResult:
    out_path = Path(output_path) if output_path else None
    result = compute_result(info, groups, method, None if dry_run else out_path)
    if not dry_run and out_path is not None:
        write_reduced_pdf(info, result, out_path)
    return result


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def format_text_report(info: PdfInspection, result: DedupeResult) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("SLIDE-DEDUPER REPORT")
    lines.append("=" * 70)
    lines.append(f"Source:            {info.path}")
    lines.append(f"Detection method:  {result.method}")
    lines.append(f"Original pages:    {result.total_pages}")
    lines.append(f"Final slides:      {result.kept_count}")
    lines.append(f"Pages removed:     {result.removed_count}")
    if result.output_path:
        lines.append(f"Output:            {result.output_path}")
    else:
        lines.append("Output:            (dry run - nothing written)")
    lines.append("")
    lines.append("Groups:")
    for i, g in enumerate(result.groups, 1):
        flag = "" if g.confidence >= 0.85 else "  <-- LOW CONFIDENCE, review"
        conf = "" if g.confidence >= 0.999 else f"  (conf {g.confidence:.2f})"
        lines.append(f"  {i:3}. {g}{conf}{flag}")
    lines.append("")
    lines.append(
        "Removed pages: "
        + (", ".join(map(str, result.removed_pages)) if result.removed_pages else "none")
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML visual review
# ---------------------------------------------------------------------------

def write_html_report(
    info: PdfInspection,
    result: DedupeResult,
    report_path: Path,
    dpi: int = 90,
) -> None:
    """Render a thumbnail per page, grouped, marking kept vs removed."""
    import base64

    doc = fitz.open(info.path)
    try:
        thumbs: dict[int, str] = {}
        for i in range(doc.page_count):
            pix = doc[i].get_pixmap(dpi=dpi)
            thumbs[i + 1] = base64.b64encode(pix.tobytes("png")).decode("ascii")
    finally:
        doc.close()

    kept = set(result.kept_pages)

    cards = []
    for i, g in enumerate(result.groups, 1):
        low = g.confidence < 0.85
        page_html = []
        for p in g.pages:
            is_kept = p in kept
            badge = "KEEP" if is_kept else "drop"
            cls = "keep" if is_kept else "drop"
            page_html.append(
                f'<figure class="{cls}">'
                f'<img src="data:image/png;base64,{thumbs[p]}" alt="page {p}"/>'
                f'<figcaption>Page {p} <span class="badge {cls}">{badge}</span></figcaption>'
                f"</figure>"
            )
        header = (
            f"Slide {i} &middot; pages {g.start}-{g.end} &middot; "
            f"keep {g.keep} &middot; {html.escape(g.method)}"
            + (f" &middot; conf {g.confidence:.2f}" if g.confidence < 0.999 else "")
        )
        cards.append(
            f'<section class="group{" low" if low else ""}">'
            f"<h2>{header}{' &#9888; review' if low else ''}</h2>"
            f'<div class="pages">{"".join(page_html)}</div>'
            f"</section>"
        )

    doc_title = html.escape(str(info.path.name))
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>slide-deduper review &mdash; {doc_title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         margin: 0; padding: 2rem; background: #0f1115; color: #e7e9ee; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 .25rem; }}
  .meta {{ color: #9aa2b1; margin-bottom: 2rem; font-size: .9rem; }}
  .group {{ border: 1px solid #262a33; border-radius: 12px; padding: 1rem 1.25rem;
           margin-bottom: 1.25rem; background: #161922; }}
  .group.low {{ border-color: #b4791f; background: #1d1710; }}
  .group h2 {{ font-size: .95rem; font-weight: 600; margin: 0 0 .75rem; color: #c9d1e0; }}
  .pages {{ display: flex; gap: .75rem; flex-wrap: wrap; }}
  figure {{ margin: 0; width: 180px; }}
  figure img {{ width: 100%; border-radius: 6px; display: block;
               border: 2px solid transparent; }}
  figure.keep img {{ border-color: #3fb950; }}
  figure.drop img {{ opacity: .45; }}
  figcaption {{ font-size: .78rem; color: #9aa2b1; margin-top: .35rem;
               display: flex; justify-content: space-between; align-items: center; }}
  .badge {{ font-size: .68rem; padding: .1rem .4rem; border-radius: 4px; font-weight: 700; }}
  .badge.keep {{ background: #12351c; color: #3fb950; }}
  .badge.drop {{ background: #2a2a2a; color: #888; }}
</style></head><body>
<h1>slide-deduper review</h1>
<div class="meta">{doc_title} &middot; method: {html.escape(result.method)} &middot;
 {result.total_pages} pages &rarr; {result.kept_count} slides
 ({result.removed_count} removed)</div>
{"".join(cards)}
</body></html>"""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(page, encoding="utf-8")
