#!/usr/bin/env python3
"""Flag candidate AI-writing tropes in the book and slide source.

Advisory only: this always exits 0. It flags candidates for a person to judge,
per CLAUDE.md's "AI-writing tropes" rule (Writing style section) and
seminars/shared-rules/shared-ground-rules.md's Language and style section.
It does not fail a build and it is not a find-and-replace tool: a hit is a
place to look, not necessarily a place to change.

Usage:
    python3 check-tropes.py [file ...]

With no arguments, checks index.qmd, chapters/*.qmd, and seminars/week*.qmd
(whichever of those exist from the current working directory).

Skips YAML front matter (--- ... ---), R/Python code chunks (```{r} ...
``` or ```{python} ... ```), and inline `code spans`, so it only ever looks
at prose and slide bullets, not code, chunk options, or an R expression
quoted inline (`n - 1` is arithmetic, not a dash).

Two tropes from the catalogue are deliberately not pattern-matched here:
a reflexive rule-of-three and a false range ("from X to Y"). Both need
semantic judgement a regex can't make (most three-item and range phrasings
in this book are genuine enumerations, not the trope), so they're read for
by hand, per CLAUDE.md's "AI-writing tropes" rule.
"""

import re
import sys
from pathlib import Path

DEFAULT_GLOBS = [
    "index.qmd",
    "chapters/*.qmd",
    "seminars/week*.qmd",
]

# Each pattern is (category, compiled regex). Patterns are matched
# case-sensitively where casing matters to the trope (e.g. "Here's") and
# case-insensitively otherwise. Keep patterns specific enough to avoid
# swamping the output with the book's own deliberate, correct usages.
_flags = re.IGNORECASE


def pat(p):
    return re.compile(p, _flags)


def pat_cs(p):
    """Case-sensitive compile, for a pattern where casing IS the signal."""
    return re.compile(p)


INLINE_CODE = re.compile(r"`[^`]*`")


PATTERNS = [
    ("negative-parallelism", pat(r"\bit'?s not\b[^.?!]{0,60}\bit'?s\b")),
    ("negative-parallelism", pat(r"\bnot (because|just|only)\b[^.?!]{0,60}\b(but|it'?s)\b")),
    ("negative-parallelism", pat(r"\bnot\b[^.?!]{0,20}\bnot\b[^.?!]{0,20}\bjust\b")),
    ("self-answered-question", pat(r"\?\s+[A-Z][a-z]")),  # "...? Y." mid-sentence style
    ("false-suspense", pat(r"\bhere'?s (the thing|the catch|what|why|where)\b")),
    ("false-suspense", pat(r"\bthis is where\b")),
    ("false-suspense", pat(r"\bthe key is\b")),
    ("trailing-reinforcement", pat(r"\bthat'?s (exactly|the whole|the point|why)\b")),
    ("analogy-opener", pat(r"\bthink of (it|this|the|them)\b")),
    ("analogy-opener", pat(r"\bimagine\b")),
    ("obviousness", pat(r"\b(simply|just|of course|clearly|obviously)\b")),
    ("intensifier", pat(r"\bactually\b")),
    ("intensifier", pat(r"\bgenuinely\b")),
    ("intensifier", pat(r"\breally\b")),
    ("intensifier", pat(r"\btruly\b")),
    ("intensifier", pat(r"\bfundamentally\b")),
    ("intensifier", pat(r"\bquietly\b")),
    ("intensifier", pat(r"\bexactly\b")),
    ("real-intensifier", pat(r"\bfor real\b")),
    ("real-intensifier", pat(r"\breal work\b")),
    ("serves-as", pat(r"\b(serves|stands|acts) as\b")),
    ("banned-vocab", pat(r"\bdelve\b")),
    ("banned-vocab", pat(r"\bcrucial\b")),
    ("banned-vocab", pat(r"\bpivotal\b")),
    ("banned-vocab", pat(r"\brobust\b")),
    ("banned-vocab", pat(r"\bleverage\b")),
    ("banned-vocab", pat(r"\blandscape\b")),
    ("banned-vocab", pat(r"\bnavigate\b")),
    ("banned-vocab", pat(r"\bseamless\b")),
    ("banned-vocab", pat(r"\benhance\b")),
    ("banned-vocab", pat(r"\bfoster\b")),
    ("banned-vocab", pat(r"\bshowcase\b")),
    ("banned-vocab", pat(r"\bunderscore\b")),
    ("banned-vocab", pat(r"\bhighlight(s|ing|ed)?\b")),
    ("banned-vocab", pat(r"\bkey (idea|point|thing|takeaway)\b")),
    ("hedge-worth", pat(r"\bit'?s worth \w+ing\b")),
    ("hedge-rather-than", pat(r"\brather than\b")),
    ("participle-tail", pat(r", (highlighting|making it|underscoring|showing|emphasizing|emphasising)\b")),
    ("spaced-hyphen-dash", pat(r"\S \- \S")),
    ("arrow-connector", pat(r"→")),
    ("em-en-dash", pat(r"[–—]")),
]

# Matched with an explicit, unshared re.compile so re.IGNORECASE above doesn't
# quietly defeat the casing they depend on.
BOLD_FIRST_ITEM = pat_cs(r"^\s*[-*]\s+\*\*[^*]{2,60}\*\*")
TITLE_CASE_HEADING = pat_cs(r"^#{1,6}\s+(?:[A-Z][a-z']*\s+){2,}[A-Z][a-z']*\s*$")

# Exemptions: a match is dropped if this second pattern also matches the same line.
EXEMPTIONS = {
    "arrow-connector": pat(r"\*\*[^*]+→[^*]*\*\*|File\s*→|Session\s*→"),
    "intensifier": pat(r"exact test|exactly \d"),
    "self-answered-question": pat(r"\?\s*$"),  # question at end of line, not mid-sentence
}

# A bold-first bullet is only flagged as a *run*: 3 or more consecutive list
# items each opening with a bold span, which is the actual Wikipedia/Holmes
# trope ("every bullet starts with bolded phrases, mimicking template
# formatting"). A single bold-first definitional label, or a pair (e.g. "Null
# hypothesis." / "Alternative hypothesis."), is this book's own sanctioned
# named-term convention and is not flagged.
BOLD_RUN_THRESHOLD = 3

CODE_FENCE = re.compile(r"^```")
YAML_FENCE = re.compile(r"^---\s*$")


def strip_code_and_frontmatter(lines):
    """Return (line_no, line) pairs for lines outside YAML frontmatter and code chunks."""
    out = []
    in_yaml = False
    in_code = False
    yaml_seen = False
    for i, line in enumerate(lines, start=1):
        if not yaml_seen and i == 1 and YAML_FENCE.match(line):
            in_yaml = True
            yaml_seen = True
            continue
        if in_yaml:
            if YAML_FENCE.match(line):
                in_yaml = False
            continue
        if CODE_FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        out.append((i, line))
    return out


def scan_bold_runs(prose_lines):
    """Flag a run of 3+ consecutive list lines that each open with a bold span."""
    hits = []
    run = []  # list of (lineno, line) currently in a bold-first run
    for lineno, line in prose_lines:
        if BOLD_FIRST_ITEM.match(line):
            run.append((lineno, line))
            continue
        if line.strip() == "":
            # a blank line between bold-first bullets doesn't break the run
            continue
        if run:
            if len(run) >= BOLD_RUN_THRESHOLD:
                for rlineno, rline in run:
                    hits.append((rlineno, "bold-first-run", rline.strip()[:60]))
            run = []
    if len(run) >= BOLD_RUN_THRESHOLD:
        for rlineno, rline in run:
            hits.append((rlineno, "bold-first-run", rline.strip()[:60]))
    return hits


def scan_file(path):
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    prose_lines = strip_code_and_frontmatter(lines)
    hits = []
    for lineno, line in prose_lines:
        if TITLE_CASE_HEADING.match(line):
            hits.append((lineno, "title-case-heading", line.strip()))
        clean = INLINE_CODE.sub(" ", line)
        for category, regex in PATTERNS:
            for m in regex.finditer(clean):
                exemption = EXEMPTIONS.get(category)
                if exemption and exemption.search(clean):
                    continue
                hits.append((lineno, category, m.group(0)))
    hits.extend(scan_bold_runs(prose_lines))
    hits.sort(key=lambda h: h[0])
    return hits


def resolve_targets(args):
    if args:
        return [Path(a) for a in args]
    targets = []
    for g in DEFAULT_GLOBS:
        targets.extend(sorted(Path().glob(g)))
    return [t for t in targets if t.is_file()]


def main():
    targets = resolve_targets(sys.argv[1:])
    if not targets:
        print("No target files found (run from the repo root, or pass file paths).")
        return 0

    grand_total = 0
    for path in targets:
        hits = scan_file(path)
        if not hits:
            continue
        print(f"\n== {path} ==")
        counts = {}
        for lineno, category, snippet in hits:
            snippet_display = snippet if len(snippet) <= 60 else snippet[:57] + "..."
            print(f"{path}:{lineno}: [{category}] {snippet_display!r}")
            counts[category] = counts.get(category, 0) + 1
        total = sum(counts.values())
        grand_total += total
        summary = ", ".join(f"{c}: {n}" for c, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        print(f"-- {path}: {total} hits ({summary})")

    print(f"\n{grand_total} total hits across {len(targets)} file(s). Advisory only: judge each, don't chase the count to zero.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
