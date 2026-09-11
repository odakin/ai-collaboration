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

Usage: strip-tex-comments.py IN.tex OUT.tex        (prints the line counts)
       strip-tex-comments.py --selftest
"""
import re
import sys

_TRAIL = re.compile(r'(?<!\\)%.*$')


def strip(text: str) -> str:
    out = []
    for line in text.split('\n'):
        if line.lstrip().startswith('%'):
            continue
        out.append(_TRAIL.sub('%', line))
    return '\n'.join(out)


def _selftest() -> int:
    src = "\\section{A} %\\red{(X and Y)}\n% dropped line\nfoo\\% not a comment\n\\newcommand{\\z}{%\n  bar}%\ntext"
    exp = "\\section{A} %\nfoo\\% not a comment\n\\newcommand{\\z}{%\n  bar}%\ntext"
    got = strip(src)
    assert got == exp, (got, exp)
    assert "(X and Y)" not in got and "dropped" not in got
    print("selftest OK")
    return 0


def main(argv):
    if len(argv) == 2 and argv[1] == '--selftest':
        return _selftest()
    if len(argv) != 3:
        print(__doc__)
        return 2
    src = open(argv[1], encoding='utf-8').read()
    out = strip(src)
    open(argv[2], 'w', encoding='utf-8').write(out)
    print(f"{argv[1]} -> {argv[2]}: {src.count(chr(10)) + 1} -> {out.count(chr(10)) + 1} lines")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
