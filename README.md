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
| `layout`    | compares text lines to tell *adding* from *replacing* (opt-in) |

Each group keeps its **last** page — the fully built-up version. `--method
auto` (the default) prefers structural signals (bookmarks, labels) and falls
back to content signals (text, visual) when the structure is missing or
unreliable.

**3. Dedupe** (`dedupe.py`) copies the kept pages into a new PDF and produces
a text report plus an optional HTML visual review.

## Handling messy real-world files

Real exported decks break naive assumptions. `slide-deduper` was hardened
against a series of failure modes found on actual lecture PDFs:

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

- **Blank slides.** An accidental empty frame is dropped rather than kept — it
  is never a real slide, and it otherwise confuses content detection by looking
  like all content was suddenly removed (the layout method reads that as a new
  slide). "Blank" is judged carefully: a page counts as empty only if it has no
  text, no images, and no meaningful drawing — a full-page white background
  rectangle (how some tools encode an empty slide) is ignored, while a genuine
  image-only diagram slide is kept.

## The layout method: adding vs. replacing

The default methods answer one question: "does the next page keep most of the
previous one and grow?" That works for **cumulative** builds, where each step
adds content. It fails for **parallel** builds, where a slide shows two
alternative versions of the same base — e.g. a constraint-graph slide whose
final line reads *"Edges/arcs show constraints"* on one page and *"Hyper-edges
show constraints"* on the next. The two pages share almost all their text, so
the text and visual methods merge them and the first variant is lost.

`--method layout` handles this by comparing pages as ordered **text lines** and
asking whether the next page *preserves every line* of the previous one. A
previous line counts as preserved if it appears again exactly, or as the
**prefix** of a longer line (builds often complete a line in place: *"Row
constraints:"* becomes *"Row constraints: X1..X9 all different"*). If any line
is neither kept nor extended — its text was *replaced* — that page starts a new
slide, so both variants survive.

This distinction (a line *extended* is a build; a line *replaced* is a new
slide) is what lets the layout method keep parallel builds that the other
methods silently drop. It is opt-in because it is stricter than the defaults:
on decks with in-place counters or heavy text reflow it can keep more pages
than you want. Reach for it when a deck has parallel builds; the reliable
label/text default is unchanged.

### Automatic cross-check

You don't have to know in advance that a deck contains parallel builds. Under
`--method auto`, after the primary method groups the pages, the layout method
is run as a second opinion and the two groupings are compared. Wherever layout
would start a new slide *inside* one of the primary method's groups — a
disagreement — that page is surfaced as a suggestion:

```
Possible missed slide boundaries (a page may start a new slide):
  group 9: page 33 looks like a new slide - 'The Constraint Graph of a CSP'
To apply all: --split 33
```

This is *ensemble disagreement as a signal*: a fast, reliable method does the
grouping, a stricter method checks it, and only where they disagree does the
tool ask you to look. Suggestions are printed, not applied, so a clean deck
(where the methods agree) produces no noise, while a deck with parallel builds
gets its boundaries flagged for review. Apply them with `--auto-split`, or copy
the printed `--split` line. On the CSP deck below, the cross-check flagged seven
boundaries and every one matched an independently hand-labelled slide.

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

Suggestions come from two sources: a sharp **title change** inside a group, and
the **layout cross-check** (a substitution the primary method merged away). They
are printed but **not** applied automatically. `--auto-split` applies all of
them; this is correct when every suggestion is a real boundary (as on CSP), but
some decks reveal elements one at a time before summarising them, and there
`--auto-split` over-splits. The robust workflow is therefore to read the
suggestions and apply `--split` with the boundaries you actually want — see
"Why the last column is sometimes reviewed" under Validation.

Titles are compared by *word overlap* rather than character similarity, so two
headings that share a common word but cover different topics — e.g.
"Evaluating Algorithms" vs "Uninformed Search Algorithms" — are still
recognised as a boundary, while genuine continuations ("Proof" → "Proof
continued") are not.

## Validation

Tested on ten real lecture decks, comparing the tool's output against a
hand-verified true count. "Auto-detected" is the plain `--dry-run` result;
"reviewed splits" is what a human keeps after reviewing the tool's suggestions
(see the note below on why this step is human judgement, not automatic).

| Lecture                    | Pages | Method | Auto-detected | True count | Reached true count by |
|----------------------------|------:|--------|--------------:|-----------:|-----------------------|
| L2 Intelligent Agents      |    81 | labels |            21 |         23 | reviewed `--split 27,53` |
| L3 Search                  |    41 | labels |            20 |         22 | `--auto-split`           |
| L4 Search II               |    81 | labels |            29 |         36 | `--auto-split`           |
| L5 Search III              |    49 | labels |            17 |         17 | nothing (clean)          |
| L6 CSP                     |    68 | labels |            28 |         35 | `--auto-split`           |
| L7 Logical Agents          |    57 | labels |            18 |         21 | `--auto-split`           |
| L8 Inference & FoL         |    43 | labels |            43 |         43 | nothing (no builds)      |
| L9 Unification & FoL       |    73 | labels |            73 |         73 | nothing (no builds)      |
| L10 MiniZinc Tutorial      |    20 | labels |            20 |         20 | nothing (no builds)      |
| L11 Uncertainty            |    68 | labels |            23 |         23 | nothing (clean)          |
| L12 Bayesian Networks      |    26 | labels |            14 |         16 | `--auto-split`           |
| L13 PDDL                   |    40 | labels |            22 |         27 | `--auto-split` (+ blank-page drop) |
| Wrap-up                    |    23 | labels |            18 |         18 | nothing (clean)          |
| Combined lectures (merged) |   670 | text   |           368 |          — | (no ground truth)        |

Across these decks the tool exercises every detection path: `labels` (most
decks, where the PDF's page labels declare the slide structure), `text` (the
merged 670-page file, whose bookmarks were unusable), and the no-build case
where the correct action is to change nothing (both FoL decks passed through
untouched). On several decks automatic detection already equals the true count;
on others the cross-check's suggestions, reviewed and applied, close the gap.

### Why the last column is sometimes "reviewed", not automatic

The tool reliably detects *where* content is substituted between pages — a line
replaced rather than added. What it cannot decide is whether a given
substitution should be **kept as two slides** or **collapsed to its final
form**, because that is a matter of what the reader finds useful, not anything
in the document.

Two real examples, structurally identical but wanting opposite outcomes:

- **CSP (keep both).** A slide's final line reads *"Edges/arcs show
  constraints"* on one page and *"Hyper-edges show constraints"* on the next.
  Each variant carries unique content, so both are worth keeping.
- **Intelligent Agents / PEAS (keep only the last).** A slide reveals the four
  PEAS elements one at a time — *Environment*, then *Sensors*, then *Actuators*,
  then *Performance* — each replacing the previous, before a final page shows
  all four together. Here only the final combined page is worth keeping.

Both are in-place substitutions; no structural rule can tell them apart, because
the difference is pedagogical intent. So the tool **surfaces every substitution
as a suggestion** and lets the reader decide. `--auto-split` applies all of
them (correct for CSP; over-splits PEAS), so for decks with build-then-summarise
slides the intended workflow is to read the suggestions and apply `--split` with
just the boundaries you want. This "detect automatically, decide manually" split
is deliberate: forcing an automatic answer would be wrong half the time.

## All options

| Flag                     | Purpose                                                   |
|--------------------------|-----------------------------------------------------------|
| `--method`               | `auto` (default), `bookmarks`, `labels`, `text`, `visual`, `layout` |
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

## Limitations

The default methods assume builds are *cumulative* — each step adds to the
previous one, so keeping the last page keeps everything. They cannot, on their
own, handle **parallel builds**, where one slide shows two alternative versions
of the same base content (see "The layout method" above). `--method layout`
addresses this case, but is itself a heuristic: it distinguishes an *extended*
line from a *replaced* one by prefix, so a slide that genuinely replaces a line
with one starting the same way, or that shrinks, can still be misread. No purely
mechanical rule captures author intent perfectly, which is why `--split` and
`--merge` remain available for the cases any detector gets wrong.

## Scope

Deliberately focused on presentation PDFs with incremental builds. It is *not*
a general PDF editor or a generic duplicate-file finder — keeping the scope
narrow is what lets the detection heuristics stay reliable.