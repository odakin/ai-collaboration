#!/usr/bin/env python3
"""Map \\label names to printed equation numbers from a plain LaTeX source, for citing equations of older papers that have no arXiv HTML.

Why: citing a paper's equation by number needs the number the reader sees, and the PDF text layer of an
old paper gives equations in fragments (conventions/physics-verification-cycle.md#pdf-text-is-an-index).
The e-print TeX has the labels. arxiv-equation-inventory.py covers papers with arXiv HTML; this one covers
the source file.

Counts equation (1 per block) and eqnarray/align (1 per line unless \\nonumber or \\notag); comments are
dropped first. Not handled: \\section-prefixed numbering, subequations, \\tag, macros that open an
environment, starred forms (skipped, as they print no number). So the output is a claim to check: compare a
few labels with the PDF before citing (the script prints the total for that purpose), and a mismatch means
the source uses one of the unhandled forms.

    python3 tex-equation-labels.py paper.tex overlapPD jacobsachsinteg
    python3 tex-equation-labels.py paper.tex --all
    python3 tex-equation-labels.py --selftest

Standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys


def equation_numbers(src):
    """Return ({label: number}, total printed equations) for a LaTeX source string."""
    src = re.sub(r"(?<!\\)%.*", "", src)
    number, labels = 0, {}
    for block in re.finditer(r"\\begin\{(equation|eqnarray|align)\}(.*?)\\end\{\1\}", src, re.S):
        env, body = block.group(1), block.group(2)
        if env == "equation":
            number += 1
            for name in re.findall(r"\\label\{([^}]+)\}", body):
                labels[name] = number
            continue
        for line in re.split(r"\\\\", body):
            if re.search(r"\\(nonumber|notag)", line):
                continue
            number += 1
            for name in re.findall(r"\\label\{([^}]+)\}", line):
                labels[name] = number
    return labels, number


def selftest():
    src = r"""
    \begin{equation} a \label{one} \end{equation}
    % \begin{equation} commented \label{no} \end{equation}
    \begin{equation*} unnumbered \end{equation*}
    \begin{eqnarray} b \label{two} \\ c \nonumber \\ d \label{three} \end{eqnarray}
    \begin{align} e \notag \\ f \label{four} \end{align}
    """
    labels, total = equation_numbers(src)
    assert labels == {"one": 1, "two": 2, "three": 3, "four": 4}, labels
    assert total == 4, total
    print("selftest ok")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", nargs="?")
    ap.add_argument("labels", nargs="*")
    ap.add_argument("--all", action="store_true", help="print every label")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        selftest()
        return 0
    if not a.source:
        ap.error("a LaTeX source file is required")
    with open(a.source, errors="replace") as f:
        labels, total = equation_numbers(f.read())
    for name in sorted(labels, key=labels.get) if a.all else a.labels:
        print(name, labels.get(name, "not found"))
    print("total", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
