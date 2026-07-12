# slide-deduper

Lecture and conference slide decks are often exported to PDF with every
animation step ("build") as a separate page: a slide with three bullets that
appear one at a time becomes three near-identical PDF pages. `slide-deduper`
collapses each such run of build-up pages down to the final, fully-built
version — so an 81-page export of 21 slides becomes a clean 21-page PDF.

Pages are **copied directly** from the source, so the kept pages keep their
exact original quality (no re-rendering).

## Install

```bash
pip install pymupdf
pip install -e .          # exposes the `slide-deduper` command
```

## Usage

```bash
# Analyse only (dry run) — omit the output path
slide-deduper lecture.pdf --dry-run

# Produce a cleaned deck
slide-deduper lecture.pdf lecture-final.pdf

# Full-featured run
slide-deduper input.pdf output.pdf \
  --method auto \
  --report report.html \
  --confidence-threshold 0.85
```

Inspect the structure only (Part 1):

```bash
slide-deduper lecture.pdf --inspect
```

## How it works

The tool runs in three layers:

1. **Inspect** (`inspect.py`) — opens the PDF read-only and gathers page
   count, metadata, bookmarks, page labels, per-page text and internal
   object numbers. It reports whether slide boundaries are already stored in
   the file, so image comparison can be skipped when possible.

2. **Group** (`group.py`) — assigns pages to slide groups using the first
   method that applies, in order of reliability:

   | Method      | Signal used                                             |
   |-------------|---------------------------------------------------------|
   | `bookmarks` | each bookmark destination starts a new slide            |
   | `labels`    | consecutive pages sharing a logical page label          |
   | `text`      | a page whose text is an *expansion* of the previous one |
   | `visual`    | rendered page N+1 preserves N's ink while adding more    |

   Each group keeps its **last** page. `--method auto` prefers structural
   signals (bookmarks, labels) and falls back to content signals (text,
   visual).

3. **Dedupe** (`dedupe.py`) — copies the kept pages into a new PDF and
   produces a text report plus an optional HTML visual review.

## Options

| Flag                       | Purpose                                             |
|----------------------------|-----------------------------------------------------|
| `--method`                 | `auto` (default), `bookmarks`, `labels`, `text`, `visual` |
| `--confidence-threshold`   | similarity cutoff for text/visual grouping (0–1)    |
| `--report report.html`     | write a grouped thumbnail review, kept vs dropped   |
| `--inspect`                | print the full inspection and exit                  |
| `--dry-run`                | analyse only; write no PDF                           |
| `--merge "3+4,7+8"`        | manually merge groups by their report index         |
| `--quiet`                  | suppress the text report                             |

## Manual correction

If auto-grouping splits or merges a slide wrongly, read the group indices
from the report and fix them with `--merge`. For example, if groups 3 and 4
are really one slide:

```bash
slide-deduper input.pdf output.pdf --merge "3+4"
```

Low-confidence groups are flagged in both the text report and the HTML
review so you know where to look.

## Tests

```bash
python3 tests/test_grouping.py      # or: pytest tests/
```

## Scope

Focused on presentation PDFs with incremental builds. It is deliberately not
a general PDF editor or a generic duplicate-file finder.
