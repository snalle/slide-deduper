"""slide-deduper: turn an incremental-build slide PDF into one final slide per group."""

from __future__ import annotations

__version__ = "0.1.0"

from .inspect import PdfInspection, inspect_pdf
from .group import SlideGroup, group_pages
from .dedupe import DedupeResult, dedupe_pdf

__all__ = [
    "__version__",
    "PdfInspection",
    "inspect_pdf",
    "SlideGroup",
    "group_pages",
    "DedupeResult",
    "dedupe_pdf",
]
