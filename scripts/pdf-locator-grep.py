#!/usr/bin/env python3
"""Pin page and equation locators: page-numbered regex hits in a PDF text layer (arXiv id or local file); --selftest.

Use after reading equations from the e-print source, to record where a statement sits in the PDF a
reader opens. A value that exists only in a figure has no text-layer hit; flag it as read by eye.

    python3 pdf-locator-grep.py 2104.01798 'position uncertainty' --cache ./scratch
    python3 pdf-locator-grep.py paper.pdf 'Eq\\. *\\(4[0-9]\\)' --context 200

An arXiv id is downloaded once into --cache (default: current directory). Requires PyMuPDF.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def resolve(target: str, cache: Path) -> Path:
    p = Path(target)
    if p.suffix.lower() == ".pdf" and p.exists():
        return p
    cache.mkdir(parents=True, exist_ok=True)
    pdf = cache / (target.replace("/", "_") + ".pdf")
    if not pdf.exists() or pdf.stat().st_size < 10000:
        subprocess.run(["curl", "-sL", "-A", "Mozilla/5.0", "-o", str(pdf),
                        f"https://arxiv.org/pdf/{target}"], check=True)
    return pdf


def hits(pdf: Path, pattern: str, context: int) -> list[tuple[int, int, str]]:
    import fitz
    rx = re.compile(pattern)
    out = []
    with fitz.open(pdf) as doc:
        n = len(doc)
        for i, page in enumerate(doc, start=1):
            text = page.get_text().replace("\n", " ")
            for m in rx.finditer(text):
                s, e = max(0, m.start() - context), min(len(text), m.end() + context)
                out.append((i, n, text[s:e]))
    return out


def selftest() -> int:
    import fitz
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "t.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "first page without the key")
        doc.new_page().insert_text((72, 72), "the coherence length (41) is defined here")
        doc.save(pdf)
        got = hits(pdf, r"coherence length \(\d+\)", 10)
        ok = len(got) == 1 and got[0][0] == 2 and got[0][1] == 2
        none = hits(pdf, r"absent phrase", 10) == []
        same = resolve(str(pdf), Path(d)) == pdf
    print("selftest:", "PASS" if ok and none and same else "FAIL")
    return 0 if ok and none and same else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="arXiv id or path to a PDF")
    ap.add_argument("pattern", nargs="?", help="regular expression")
    ap.add_argument("--context", type=int, default=160)
    ap.add_argument("--cache", type=Path, default=Path("."))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.target or not a.pattern:
        ap.error("target and pattern are required")
    pdf = resolve(a.target, a.cache)
    found = hits(pdf, a.pattern, a.context)
    for page, total, snippet in found:
        print(f"[p.{page}/{total}] ...{snippet}...")
    print(f"-- {len(found)} match(es) in {pdf.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
