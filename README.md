# slide-deduper

Lecture and conference slide decks are often exported to PDF with every
animation step ("build") as a separate page: a slide with three bullets that
appear one at a time becomes three near-identical PDF pages. Studying from
such a file means paging through the same slide over and over.

`slide-deduper` collapses each run of build-up pages down to its final,
fully-built version — turning, for example, an 81-page export of 21 slides
into a clean 21-page PDF.

Kept pages are **copied directly** from the source, so they retain their exact
original quality — nothing is re-rendered or re-compressed.

## Install

```bash
pip install pymupdf
pip install -e .          # exposes the `slide-deduper` command
```

Requires Python 3.10+. The only dependency is [PyMuPDF](https://pymupdf.readthedocs.io/).

## Quick start

```bash
# 1. See what's in the file and how it would be grouped (writes nothing)
slide-deduper lecture.pdf --dry-run

# 2. Produce the cleaned deck
slide-deduper lecture.pdf lecture-final.pdf

# 3. Same, with an HTML review page showing kept vs dropped pages
slide-deduper lecture.pdf lecture-final.pdf --report review.html
```

The rule for arguments is simple: the **first path is the input**, the
**second path is the output**. Omit the second path (or pass `--dry-run`) to
analyse without writing anything.

## How it works

The tool runs in three layers:

**1. Inspect** (`inspect.py`) opens the PDF read-only and gathers page count,
metadata, bookmarks, page labels, per-page text, and internal object numbers.
It reports whether slide boundaries are already stored in the file, so slower
image comparison can be skipped when a reliable signal exists.

**2. Group** (`group.py`) assigns pages to slide groups using the first
method that applies, in order of reliability:

| Method      | Signal used                                              |
|-------------|----------------------------------------------------------|
| `bookmarks` | each bookmark destination starts a new slide             |
| `labels`    | consecutive pages sharing a logical page label           |
| `text`      | a page whose text is an *expansion* of the previous one  |
| `visual`    | rendered page N+1 preserves N's ink while adding more     |

Each group keeps its **last** page — the fully built-up version. `--method
auto` (the default) prefers structural signals (bookmarks, labels) and falls
back to content signals (text, visual) when the structure is missing or
unreliable.

**3. Dedupe** (`dedupe.py`) copies the kept pages into a new PDF and produces
a text report plus an optional HTML visual review.

## Handling messy real-world files

Real exported decks break naive assumptions. `slide-deduper` was hardened
against three failure modes found on actual lecture PDFs:

- **Sparse "section" bookmarks.** A deck may carry only a few top-level
  bookmarks (e.g. 3 chapter headings in an 81-page file). Trusting these as
  slide boundaries would collapse dozens of pages into a few huge groups.
  Bookmarks that are implausibly sparse for the page count are rejected, and
  grouping falls through to a content-based method.

- **Merged decks with broken bookmarks.** When several lectures are
  concatenated into one PDF, bookmark destinations can collapse to page 0.
  These are detected and ignored.

- **Beamer page-number footers.** A footer like `Author (SDU)  AI  3 / 43`
  changes its number on every build page, which would otherwise make two
  builds of one slide look different and split them. Such `N / M` footers are
  stripped before text comparison.

- **Non-Latin characters in slide text.** Slides often contain arrows (`←`),
  math symbols, or other Unicode. Console output is forced to UTF-8 so these
  don't crash the tool on Windows terminals, whose legacy default encoding
  (cp1252) can't represent them.

- **Exact-duplicate pages.** Some exporters emit the fully-built slide more
  than once (e.g. a Beamer overlay that repeats its final frame). When such
  duplicates straddle a page-label boundary, the label detector would keep two
  copies. A post-grouping pass detects adjacent groups whose boundary pages
  have identical text and merges them, so only one copy survives.

## Manual correction

Automatic grouping recovers the slide structure the PDF *declares*.
Occasionally an author's own numbering merges what a reader considers distinct
slides — for example, a genuinely new subject placed on the same page label as
the previous slide's final build. Two overrides handle this, in both
directions:

```bash
# Split: start a new slide at the given page numbers
slide-deduper lecture.pdf out.pdf --split 27,53

# Merge: combine over-split groups by their report index
slide-deduper lecture.pdf out.pdf --merge "3+4,7+8"
```

### Suggested boundaries

You don't have to find the split points by eye. When a page inside a group has
a title that differs sharply from the page before it, the tool prints it as a
candidate:

```
Possible missed slide boundaries (title changes inside a group):
  group 9: page 27 looks like a new slide - 'Task Environment Specification'
  group 13: page 53 looks like a new slide - 'Agent Types Overview'
To apply all: --split 27,53
```

Suggestions are printed but **not** applied automatically, so the reliable
label-based default is never silently overridden. Copy the suggested `--split`,
or let the tool apply its own suggestions with `--auto-split`.

Titles are compared by *word overlap* rather than character similarity, so two
headings that share a common word but cover different topics — e.g.
"Evaluating Algorithms" vs "Uninformed Search Algorithms" — are still
recognised as a boundary, while genuine continuations ("Proof" → "Proof
continued") are not.

## Validation

Tested on real lecture decks, comparing the recovered slide count against
ground truth (the deck's own slide numbering):

| Deck                       | Pages | Method  | Auto slides | With corrections | True count |
|----------------------------|------:|---------|------------:|-----------------:|-----------:|
| L2: Intelligent Agents     |    81 | labels  |          21 |   23 (`--split`) |         23 |
| L3: Search                 |    41 | labels  |          20 |   22 (`--split`) |         22 |
| L4: Search II              |    81 | labels  |          30 | 36 (`--auto-split`) |      36 |
| L5: Search III             |    49 | labels  |          17 | — (none needed)  |         17 |
| Combined lectures (merged) |   670 | text    |         368 |                — |          — |

*(Add your own rows: run `--dry-run` on a deck whose slide numbering gives a
known count, and compare.)*

The Intelligent Agents deck is the illustrative case: the PDF's page labels
declare 21 slides, and automatic detection recovers exactly that. Two of those
"slides" actually contain a topic change the author placed under one label;
`--split` (suggested automatically) separates them for the reader's 23.

Search II is the most demanding case: it combines incremental builds, topic
changes hidden under shared labels, *and* exact-duplicate frames. With a single
`--auto-split`, the output matches a hand-labelled ground truth exactly — every
one of the 36 kept pages agrees. Search III sits at the other end: a
straightforward deck that automatic detection handles correctly with no
corrections at all. Each deck above drove a specific fix documented under
"Handling messy real-world files".

## All options

| Flag                     | Purpose                                                   |
|--------------------------|-----------------------------------------------------------|
| `--method`               | `auto` (default), `bookmarks`, `labels`, `text`, `visual` |
| `--confidence-threshold` | similarity cutoff for text/visual grouping (0–1)          |
| `--report FILE.html`     | write a grouped thumbnail review, kept vs dropped         |
| `--inspect`              | print the full structural inspection and exit             |
| `--dry-run`              | analyse only; write no PDF                                 |
| `--split PAGES`          | start a new slide at these page numbers, e.g. `27,53`     |
| `--auto-split`           | apply the suggested title-change splits automatically     |
| `--merge SPEC`           | combine groups by report index, e.g. `3+4,7+8`            |
| `--quiet`                | suppress the text report                                  |

## Tests

```bash
pytest tests/                    # with pytest installed
python3 tests/test_grouping.py   # no dependencies beyond the package
```

The suite covers each detection method, the three real-world regressions
above, manual `--split`, and the boundary suggester.

## Scope

Deliberately focused on presentation PDFs with incremental builds. It is *not*
a general PDF editor or a generic duplicate-file finder — keeping the scope
narrow is what lets the detection heuristics stay reliable.