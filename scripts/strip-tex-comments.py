#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strip LaTeX comments from a referee copy without changing the typeset output.

Why (2026-09-11): the referee copy of a manuscript must carry no author dialogue.  Review
markup (\\red{...}, Q&A) is removed by review-markup-clean.py, but commented-out lines still
carry authorship notes ("%\\red{(Karl and Shinya)}"), rejected drafts, and pointers to
companion papers.  Stripping them is part of the sealed-sandbox recipe
(conventions/cold-eyes-isolation.md#sealed-sandbox, step 2).

Rules (typesetting-neutral):
  * a line whose first non-blank character is % is dropped entirely;
  * in any other line, the text after an unescaped % is dropped but the % itself is kept,
    so end-of-line spacing control in macro definitions is unchanged;
  * \\% (escaped) is left alone.
Verify by rebuilding and comparing the extracted text of the two PDFs (the calling recipe
does this); this script only guarantees the source-level property.

A bibliography database (.bib) carries the same channel: the lines between entries that start with %
(and @comment entries) hold the author's notes on why a reference was added, which round asked for
it, where the source note lives.  Measured: a referee copy whose .tex was stripped still carried such
a line in its .bib, and the judging session stopped on it.  strip_bib() drops those lines; it never
touches the inside of an entry (% is not a comment character inside a BibTeX field, so a trailing %
must stay).  The `note = {...}` fields are printed by some styles; the recipe strips them separately
when the style prints them (cold-eyes-isolation.md#referee-copy-strip-comments).

Usage: strip-tex-comments.py IN.tex OUT.tex        (prints the line counts; IN.bib OUT.bib strips the .bib way)
       strip-tex-comments.py --selftest
"""
import re
import sys

_TRAIL = re.compile(r'(?<!\\)%.*$')
_BIB_COMMENT_ENTRY = re.compile(r'^\s*@comment\b', re.IGNORECASE)


def strip(text: str) -> str:
    out = []
    for line in text.split('\n'):
        if line.lstrip().startswith('%'):
            continue
        out.append(_TRAIL.sub('%', line))
    return '\n'.join(out)


def strip_bib(text: str) -> str:
    """Drop the comment lines of a .bib (first non-blank char %, or a one-line @comment{...} entry).

    Nothing inside an entry is changed: BibTeX reads text between entries as a comment anyway, and a %
    inside a field value is a literal character."""
    out = []
    for line in text.split('\n'):
        if line.lstrip().startswith('%') or _BIB_COMMENT_ENTRY.match(line):
            continue
        out.append(line)
    return '\n'.join(out)


def strip_for(path: str, text: str) -> str:
    return strip_bib(text) if path.lower().endswith('.bib') else strip(text)


def _selftest() -> int:
    src = "\\section{A} %\\red{(X and Y)}\n% dropped line\nfoo\\% not a comment\n\\newcommand{\\z}{%\n  bar}%\ntext"
    exp = "\\section{A} %\nfoo\\% not a comment\n\\newcommand{\\z}{%\n  bar}%\ntext"
    got = strip(src)
    assert got == exp, (got, exp)
    assert "(X and Y)" not in got and "dropped" not in got
    bib = ("% ---- added after the referee asked for it ----\n@article{k,\n  title = \"{A 93\\% result}\",\n"
           "  note = \"{p.3 % not a comment here}\",\n}\n@Comment{why this entry: see plans/x.md}\n")
    gotb = strip_bib(bib)
    assert "referee" not in gotb and "plans/" not in gotb, gotb
    assert "93\\% result" in gotb and "p.3 % not a comment here" in gotb, "entry contents must be untouched"
    assert strip_for("refs.BIB", bib) == gotb and strip_for("a.tex", src) == exp
    print("selftest OK")
    return 0


def main(argv):
    if len(argv) == 2 and argv[1] == '--selftest':
        return _selftest()
    if len(argv) != 3:
        print(__doc__)
        return 2
    src = open(argv[1], encoding='utf-8').read()
    out = strip_for(argv[1], src)
    open(argv[2], 'w', encoding='utf-8').write(out)
    print(f"{argv[1]} -> {argv[2]}: {src.count(chr(10)) + 1} -> {out.count(chr(10)) + 1} lines")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
