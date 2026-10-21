#!/usr/bin/env python3
"""Pin page and equation locators: page-numbered regex hits in a PDF text layer, page-marked text dump, page renders (arXiv id or local file); --selftest.

Use after reading equations from the e-print source, to record where a statement sits in the PDF a
reader opens. A value that exists only in a figure has no text-layer hit; flag it as read by eye.

    python3 pdf-locator-grep.py 2104.01798 'position uncertainty' --cache ./scratch
    python3 pdf-locator-grep.py paper.pdf 'Eq\\. *\\(4[0-9]\\)' --context 200
    python3 pdf-locator-grep.py paper.pdf --dump scratch/paper.txt          # whole text, one marker per page
    python3 pdf-locator-grep.py paper.pdf --render 3,7-8 --render-dir scratch/pages

The text layer is an index for finding places, not evidence about a formula: extraction can reorder
terms, split brackets, drop superscripts and move footnotes or floats across pages. Before a sign,
bracket, index or factor read from the text layer becomes a finding, look at the rendered page (or the
e-print source); when a check written from a transcription fails, compare the transcription with the
render first (conventions/physics-verification-cycle.md#pdf-text-is-an-index).

--dump and --render never replace an existing file (choose a fresh path; collected evidence stays as it
was) and refuse to write onto the input PDF. A pattern is optional when --dump or --render is given.
An arXiv id is downloaded once into --cache (default: current directory); for fetches that must be
recorded with version, status and digest use fetch-literature.py instead. Requires PyMuPDF.
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


def fresh(path: Path, pdf: Path) -> None:
    """Refuse to replace an existing file or to write onto the input."""
    if path.resolve() == pdf.resolve():
        raise SystemExit(f"refusing to write onto the input PDF: {path}")
    if path.exists():
        raise SystemExit(f"refusing to replace an existing file (choose a fresh path): {path}")


def dump(pdf: Path, out: Path) -> int:
    import fitz
    fresh(out, pdf)
    with fitz.open(pdf) as doc:
        n = len(doc)
        parts = [f"\n===== PDF PAGE {i}/{n} =====\n\n{page.get_text(sort=True)}"
                 for i, page in enumerate(doc, start=1)]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(parts), encoding="utf-8")
    return n


def page_list(spec: str, n: int) -> list[int]:
    if spec == "all":
        return list(range(1, n + 1))
    pages: list[int] = []
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        lo, hi = int(a), int(b or a)
        if not 1 <= lo <= hi <= n:
            raise SystemExit(f"page range {part!r} outside 1..{n}")
        pages.extend(range(lo, hi + 1))
    return pages


def render(pdf: Path, spec: str, out_dir: Path, scale: float) -> list[Path]:
    import fitz
    written = []
    with fitz.open(pdf) as doc:
        pages = page_list(spec, len(doc))
        targets = [out_dir / f"{pdf.stem}-p{p:03d}.png" for p in pages]
        for t in targets:
            fresh(t, pdf)
        out_dir.mkdir(parents=True, exist_ok=True)
        for p, t in zip(pages, targets):
            doc[p - 1].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(t)
            written.append(t)
    return written


def selftest() -> int:
    import fitz
    checks = {}
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "t.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "first page without the key")
        doc.new_page().insert_text((72, 72), "the coherence length (41) is defined here")
        doc.save(pdf)
        got = hits(pdf, r"coherence length \(\d+\)", 10)
        checks["hit on page 2 of 2"] = len(got) == 1 and got[0][0] == 2 and got[0][1] == 2
        checks["no false hit"] = hits(pdf, r"absent phrase", 10) == []
        checks["local file kept"] = resolve(str(pdf), Path(d)) == pdf
        out = Path(d) / "t.txt"
        checks["dump pages"] = dump(pdf, out) == 2 and "===== PDF PAGE 2/2 =====" in out.read_text()
        for label, fn in [("dump refuses existing", lambda: dump(pdf, out)),
                          ("dump refuses input", lambda: dump(pdf, pdf)),
                          ("range checked", lambda: page_list("0-1", 2))]:
            try:
                fn()
                checks[label] = False
            except SystemExit:
                checks[label] = True
        pngs = render(pdf, "2", Path(d) / "pages", 1.0)
        checks["render one page"] = [p.name for p in pngs] == ["t-p002.png"] and pngs[0].stat().st_size > 0
        try:
            render(pdf, "1-2", Path(d) / "pages", 1.0)   # p002 exists: nothing may be written
            checks["render refuses existing"] = False
        except SystemExit:
            checks["render refuses existing"] = not (Path(d) / "pages" / "t-p001.png").exists()
        checks["page list"] = page_list("1,3-4", 5) == [1, 3, 4] and page_list("all", 2) == [1, 2]
    bad = [k for k, v in checks.items() if not v]
    print("selftest:", "PASS" if not bad else f"FAIL {bad}")
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="arXiv id or path to a PDF")
    ap.add_argument("pattern", nargs="?", help="regular expression")
    ap.add_argument("--context", type=int, default=160)
    ap.add_argument("--cache", type=Path, default=Path("."))
    ap.add_argument("--dump", type=Path, help="write the whole text layer with one marker per page (fresh path)")
    ap.add_argument("--render", metavar="PAGES", help="pages to render as PNG: 'all' or e.g. '3,15-16'")
    ap.add_argument("--render-dir", type=Path, help="directory for --render (files never replaced)")
    ap.add_argument("--scale", type=float, default=2.0, help="render scale (default 2.0)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.target:
        ap.error("target is required")
    if not (a.pattern or a.dump or a.render):
        ap.error("give a pattern, --dump or --render")
    if a.render and not a.render_dir:
        ap.error("--render needs --render-dir")
    pdf = resolve(a.target, a.cache)
    if a.dump:
        print(f"-- {dump(pdf, a.dump)} page(s) -> {a.dump}")
    if a.render:
        for t in render(pdf, a.render, a.render_dir, a.scale):
            print(f"-- rendered {t}")
    if a.pattern:
        found = hits(pdf, a.pattern, a.context)
        for page, total, snippet in found:
            print(f"[p.{page}/{total}] ...{snippet}...")
        print(f"-- {len(found)} match(es) in {pdf.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
