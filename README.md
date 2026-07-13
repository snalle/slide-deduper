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

Tested on thirteen real lecture decks plus the full merged corpus, comparing
the tool's output against a hand-verified true count. "Auto-detected" is the
plain `--dry-run` result; "reached true count by" is what a human keeps after
reviewing the tool's suggestions (see the note below on why this step is human
judgement, not automatic).

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
| **Combined (13 lectures)** |   670 | text   |           380 |       ~374 | text fallback; see below |

Across these decks the tool exercises every detection path: `labels` (most
individual decks, where the PDF's page labels declare the slide structure),
`text` (the merged corpus, whose per-lecture labels were lost in the merge), and
the no-build case where the correct action is to change nothing (the FoL and
MiniZinc decks passed through untouched). On several decks automatic detection
already equals the true count; on others the cross-check's suggestions, reviewed
and applied, close the gap.

### The combined-corpus test

Running the tool on all thirteen lectures concatenated into one 670-page file is
the end-to-end stress test. The result — **380 slides against a hand-verified
target of ~374, within 1.6%** — is informative in three ways:

- **Graceful degradation.** Merging destroyed the per-lecture page labels, so
  the tool fell back from `labels` to `text` detection automatically. It still
  landed within 1.6% of the sum of the individually-verified counts.
- **Right for the right reasons.** A 141-page stretch with *zero* removals maps
  cleanly onto the three no-build lectures (FoL ×2 + MiniZinc = 136 pages) — the
  tool correctly changed nothing there rather than failing to detect builds.
- **Why not exact.** The ~6-slide gap comes from the twelve lecture *seams*
  (where one deck's last slide meets the next deck's title) and from the
  per-lecture human judgements (keeping CSP's substitution, collapsing PEAS's)
  that `text` detection cannot reproduce on its own. Reaching exactly 374 would
  require the same manual review applied per-lecture — the tool gets within 1.6%
  automatically.

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
| `--auto-split`           | apply all suggested boundaries (title-change + layout cross-check) automatically |
| `--merge SPEC`           | combine groups by report index, e.g. `3+4,7+8`            |
| `--quiet`                | suppress the text report                                  |

## Tests

```bash
pytest tests/                    # with pytest installed
python3 tests/test_grouping.py   # no dependencies beyond the package
```

The suite (15 tests) covers each detection method, the real-world regressions
listed under "Edge cases" above, the layout method and cross-check, manual
`--split`, blank-page and duplicate handling, and the boundary suggester.

## Limitations — what it still struggles with

The tool is reliable on the common case (cumulative builds with usable labels or
comparable text), but it is a set of heuristics, not a mind-reader. Known limits:

- **Substitution intent is undecidable.** The tool detects *where* a line is
  replaced rather than added, but not whether you want both variants kept (like
  CSP's Edges/Hyper-edges) or only the final summary (like PEAS revealed one
  element at a time). These are structurally identical; the difference is
  pedagogical intent. So substitutions are *surfaced as suggestions*, and
  `--auto-split` — which applies all of them — over-splits build-then-summarise
  slides. The intended workflow there is to review and apply `--split` manually.

- **The layout method's prefix rule can misfire.** It treats an *extended* line
  as a build and a *replaced* line as a new slide, judged by prefix. A slide
  that genuinely replaces a line with one that happens to start the same way, or
  that *shrinks* text between builds, can be misread. It is also stricter than
  the defaults, so on decks with in-place counters or heavy reflow it keeps more
  pages than wanted — which is why it is opt-in, not the default.

- **Image-only slides can't be compared by text.** The `text` and `layout`
  methods rely on extractable text. A slide that is purely a diagram or
  screenshot (e.g. an incrementally-built graph rendered as images) has no text
  to compare, so consecutive image-only builds may each be kept as separate
  slides. The `visual` method exists for this but is coarser; for image-heavy
  builds, manual `--merge` or `--split` may be needed.

- **Merged decks lose structure.** Concatenating lectures destroys per-file page
  labels (and can corrupt bookmarks to page 0), forcing the fuzzier `text`
  fallback. On the 670-page combined corpus this still landed within 1.6% of the
  hand-verified target, but exact recovery would need the per-lecture manual
  review re-applied, and lecture *seams* introduce small boundary errors.

- **Lecture seams in combined files.** Where one deck's final slide meets the
  next deck's title slide, the tool may keep an extra transition page or merge
  across the boundary. Small, but it accounts for part of the combined-corpus
  gap.

- **`--merge` uses group indices, `--split` uses page numbers.** A deliberate
  asymmetry (page numbers are stable regardless of grouping; merge naturally
  works on the indices shown in the report), but worth knowing when combining
  both in one run — split is applied first, then merge on the resulting indices.

When any detector gets a specific deck wrong, `--split` and `--merge` are the
escape hatch — the tool is designed so a human always has the final say.

## Edge cases the tool was hardened against

Each of these was a real failure found by running actual lecture PDFs, then
fixed and pinned with a regression test:

| Edge case | What broke | Fix |
|-----------|-----------|-----|
| Sparse "section" bookmarks | 3 bookmarks in an 81-page deck collapsed it to 3 groups | reject implausibly sparse bookmarks; fall through to content detection |
| Merged-file bookmarks | destinations collapsed to page 0 | detect and ignore |
| Beamer `N / M` footers | changing page number made builds look different | strip footers before text comparison |
| Character-level title match | "Evaluating Algorithms" vs "Uninformed Search Algorithms" scored as similar | compare titles by *word* overlap, not characters |
| Non-Latin characters (`←`, math) | crashed on Windows cp1252 consoles | force UTF-8 output |
| Exact-duplicate frames | exporter repeated the final frame across a label boundary | merge adjacent groups with identical boundary text |
| Blank slides | a full-page white rectangle looked like content, confused layout detection | drop pages with no text/images/meaningful drawing, ignoring full-page background fills |
| Parallel builds | text/visual merged substituted variants, losing content | `--method layout` + cross-check surface them for review |

## Scope

Deliberately focused on presentation PDFs with incremental builds. It is *not*
a general PDF editor or a generic duplicate-file finder — keeping the scope
narrow is what lets the detection heuristics stay reliable.