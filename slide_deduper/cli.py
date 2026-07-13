"""Command-line interface for slide-deduper."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Slide text often contains non-Latin characters (arrows like "<-", math
# symbols, bullets). Windows consoles default to a legacy codepage (cp1252)
# that can't encode them, which crashes print(). Force UTF-8 on our streams so
# output works identically across platforms.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass  # older Python or already-wrapped stream; nothing we can do safely

from . import __version__
from .inspect import inspect_pdf, print_report
from .group import group_pages, format_groups, SlideGroup, suggest_splits, format_split_suggestions
from .dedupe import dedupe_pdf, format_text_report, write_html_report


def _parse_split_spec(spec: str, groups: list[SlideGroup], method: str) -> list[SlideGroup]:
    """Split groups so that a new group *starts* at each given page number.

    Spec is a comma-separated list of 1-based physical page numbers, e.g.
    '27,53' means "page 27 begins a new slide, and page 53 begins a new
    slide" - splitting whatever groups currently contain those pages.

    This is the complement of --merge: it corrects cases where a genuinely
    new subject shares a page label with the previous slide's final build, so
    automatic grouping swallowed it.
    """
    if not spec:
        return groups

    split_at = {int(x.strip()) for x in spec.split(",") if x.strip()}

    result: list[SlideGroup] = []
    for g in groups:
        # Find split points that fall strictly inside this group.
        cuts = sorted(p for p in split_at if g.start < p <= g.end)
        if not cuts:
            result.append(g)
            continue

        boundaries = [g.start] + cuts + [g.end + 1]
        for a, b in zip(boundaries, boundaries[1:]):
            pages = [p for p in g.pages if a <= p < b]
            if pages:
                result.append(SlideGroup(pages, method, g.confidence))
    return result


def _parse_merge_spec(spec: str, groups: list[SlideGroup], method: str) -> list[SlideGroup]:
    """Apply manual corrections like '3+4,7+8+9' to merge listed slide groups.

    Numbers refer to slide-group indices (1-based) as printed in the report.
    """
    if not spec:
        return groups

    merges = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        idxs = sorted(int(x) for x in chunk.split("+"))
        merges.append(idxs)

    to_merge = {i for group in merges for i in group}
    result: list[SlideGroup] = []
    consumed: set[int] = set()

    for group in merges:
        pages: list[int] = []
        conf = 1.0
        for gi in group:
            if 1 <= gi <= len(groups):
                pages.extend(groups[gi - 1].pages)
                conf = min(conf, groups[gi - 1].confidence)
                consumed.add(gi)
        if pages:
            result.append((min(pages), SlideGroup(sorted(pages), method, conf)))

    for i, g in enumerate(groups, 1):
        if i not in to_merge:
            result.append((g.start, g))

    result.sort(key=lambda t: t[0])
    return [g for _, g in result]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="slide-deduper",
        description="Turn an incremental-build slide PDF into one final slide per group.",
    )
    p.add_argument("input", type=Path, help="source PDF")
    p.add_argument("output", type=Path, nargs="?", help="output PDF (omit for dry-run)")
    p.add_argument(
        "--method",
        choices=["auto", "bookmarks", "labels", "text", "visual", "layout"],
        default="auto",
        help="detection method (default: auto)",
    )
    p.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.85,
        metavar="0..1",
        help="similarity threshold for text/visual grouping (default: 0.85)",
    )
    p.add_argument("--report", type=Path, help="write an HTML visual review to this path")
    p.add_argument("--inspect", action="store_true", help="print full inspection and exit")
    p.add_argument("--dry-run", action="store_true", help="analyse only; write no PDF")
    p.add_argument(
        "--merge",
        default="",
        metavar="SPEC",
        help="manually merge groups, e.g. '3+4,7+8' (indices from the report)",
    )
    p.add_argument(
        "--split",
        default="",
        metavar="PAGES",
        help="start a new slide at these page numbers, e.g. '27,53' "
        "(splits groups where a new subject shares a label with the previous build)",
    )
    p.add_argument(
        "--auto-split",
        action="store_true",
        help="automatically apply the suggested title-change splits "
        "(otherwise they are only printed as suggestions)",
    )
    p.add_argument("--quiet", action="store_true", help="suppress the text report")
    p.add_argument("--version", action="version", version=f"slide-deduper {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.input.exists():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 1

    info = inspect_pdf(args.input)

    if args.inspect:
        print_report(info)
        return 0

    groups = group_pages(info, method=args.method, threshold=args.confidence_threshold)
    chosen_method = args.method if args.method != "auto" else (groups[0].method if groups else "auto")

    # Detect candidate missed boundaries (new subject inside a grouped run).
    suggestions = suggest_splits(info, groups)

    # Manual corrections. Split first (operates on page numbers, unaffected by
    # indexing), then merge (operates on the resulting group indices).
    split_spec = args.split
    if args.auto_split and suggestions:
        auto_pages = ",".join(str(p) for _, p, _ in suggestions)
        split_spec = f"{split_spec},{auto_pages}" if split_spec else auto_pages

    if split_spec:
        groups = _parse_split_spec(split_spec, groups, chosen_method)
    if args.merge:
        groups = _parse_merge_spec(args.merge, groups, chosen_method)

    dry_run = args.dry_run or args.output is None
    result = dedupe_pdf(info, groups, chosen_method, args.output, dry_run=dry_run)

    if not args.quiet:
        print(format_text_report(info, result))
        # Show suggestions only when they weren't already auto-applied.
        if suggestions and not args.auto_split:
            print(format_split_suggestions(suggestions))

    if args.report:
        write_html_report(info, result, args.report)
        if not args.quiet:
            print(f"\nHTML review written to: {args.report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())