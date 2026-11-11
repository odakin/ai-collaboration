#!/usr/bin/env python3
"""Pin page and equation locators: page-numbered regex hits in a PDF text layer, page-marked text dump, page renders, zoomed crops, printed page numbers and a copy's sha256 (arXiv id or local file); --selftest.

Use after reading equations from the e-print source, to record where a statement sits in the PDF a
reader opens, and to read a scanned source by eye. A value that exists only in a figure has no
text-layer hit; flag it as read by eye.

    python3 pdf-locator-grep.py 2104.01798 'position uncertainty' --cache ./scratch
    python3 pdf-locator-grep.py paper.pdf 'Eq\\. *\\(4[0-9]\\)' --context 200
    python3 pdf-locator-grep.py paper.pdf --dump scratch/paper.txt          # whole text, one marker per page
    python3 pdf-locator-grep.py paper.pdf --render 3,7-8 --render-dir scratch/pages
    # a journal copy whose PDF page 1 is an archive cover: printed page = PDF page + 100
    python3 pdf-locator-grep.py copy.pdf --page-offset 100 --sha256 <recorded digest> --render 112-113 --render-dir scratch/pages
    python3 pdf-locator-grep.py copy.pdf --page-offset 100 --crop 113:50,100,450,250 --render-dir scratch/pages

The text layer is an index for finding places, not evidence about a formula: extraction can reorder
terms, split brackets, drop superscripts and move footnotes or floats across pages. Before a sign,
bracket, index or factor read from the text layer becomes a finding, look at the rendered page (or the
e-print source); when a check written from a transcription fails, compare the transcription with the
render first (conventions/physics-verification-cycle.md#pdf-text-is-an-index). The text layer of a scan
(OCR) garbles formulas: use it for finding words only, and read formulas from --render / --crop.

--page-offset N: printed page = PDF page + N (find N from the page numbers on a rendered page, or
estimate it with claude-config scripts/scan-book-survey.py offset). Hits, --dump markers and file names
then carry both numbers, and --render / --crop take printed page numbers.
--crop PAGE:x0,y0,x1,y1 (repeatable): render that rectangle (PDF points, origin top left) of the page at
--crop-scale (default 5) into --render-dir; the page size in points is printed, so a first crop can be
narrowed. --sha256 HEX: stop before reading anything when the copy's digest differs from the recorded one
(a collation read from another copy does not match its record).

--dump, --render and --crop never replace an existing file (choose a fresh path; collected evidence stays
as it was) and refuse to write onto the input PDF. A pattern is optional when --dump, --render or --crop
is given. An arXiv id is downloaded once into --cache (default: current directory); for fetches that must
be recorded with version, status and digest use fetch-literature.py instead. Requires PyMuPDF.
"""
from __future__ import annotations

import argparse
import hashlib
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


def check_sha256(pdf: Path, want: str) -> str:
    """The copy's digest; SystemExit when it is not the recorded one."""
    got = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if got != want.strip().lower():
        raise SystemExit(f"sha256 differs from the recorded copy: {got} (recorded {want.strip().lower()}) — {pdf}")
    return got


def page_label(i: int, n: int, offset: int | None) -> str:
    """'p.12/30' or, with a printed-page offset of 100, 'p.112 (PDF 12/30)'."""
    return f"p.{i}/{n}" if offset is None else f"p.{i + offset} (PDF {i}/{n})"


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


def dump(pdf: Path, out: Path, offset: int | None = None) -> int:
    import fitz
    fresh(out, pdf)
    with fitz.open(pdf) as doc:
        n = len(doc)
        mark = (lambda i: f"PDF PAGE {i}/{n}") if offset is None else (lambda i: f"PDF PAGE {i}/{n} = PRINTED {i + offset}")
        parts = [f"\n===== {mark(i)} =====\n\n{page.get_text(sort=True)}" for i, page in enumerate(doc, start=1)]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(parts), encoding="utf-8")
    return n


def page_list(spec: str, n: int, offset: int | None = None) -> list[int]:
    """PDF page numbers for a spec in PDF numbers, or in printed numbers when an offset is given."""
    off = offset or 0
    if spec == "all":
        return list(range(1, n + 1))
    pages: list[int] = []
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        lo, hi = int(a) - off, int(b or a) - off
        if not 1 <= lo <= hi <= n:
            span = f"1..{n}" if offset is None else f"printed {1 + off}..{n + off} (PDF 1..{n})"
            raise SystemExit(f"page range {part!r} outside {span}")
        pages.extend(range(lo, hi + 1))
    return pages


def png_name(pdf: Path, p: int, offset: int | None, suffix: str = "") -> str:
    base = f"{pdf.stem}-p{p:03d}" if offset is None else f"{pdf.stem}-p{p + offset:03d}-pdf{p:03d}"
    return base + suffix + ".png"


def render(pdf: Path, spec: str, out_dir: Path, scale: float, offset: int | None = None) -> list[Path]:
    import fitz
    written = []
    with fitz.open(pdf) as doc:
        pages = page_list(spec, len(doc), offset)
        targets = [out_dir / png_name(pdf, p, offset) for p in pages]
        for t in targets:
            fresh(t, pdf)
        out_dir.mkdir(parents=True, exist_ok=True)
        for p, t in zip(pages, targets):
            doc[p - 1].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(t)
            written.append(t)
    return written


def parse_crop(spec: str) -> tuple[int, tuple[float, float, float, float]]:
    page, _, rect = spec.partition(":")
    try:
        x0, y0, x1, y1 = (float(v) for v in rect.split(","))
        return int(page), (x0, y0, x1, y1)
    except ValueError:
        raise SystemExit(f"--crop wants PAGE:x0,y0,x1,y1 (PDF points), got {spec!r}")


def crop(pdf: Path, spec: str, out_dir: Path, scale: float, offset: int | None = None) -> tuple[Path, tuple[float, float]]:
    """Render one rectangle of one page; returns the PNG and the page size in points."""
    import fitz
    page_no, (x0, y0, x1, y1) = parse_crop(spec)
    with fitz.open(pdf) as doc:
        (p,) = page_list(str(page_no), len(doc), offset)
        page = doc[p - 1]
        size = (round(page.rect.width, 1), round(page.rect.height, 1))
        clip = fitz.Rect(x0, y0, x1, y1) & page.rect
        if clip.is_empty or x1 <= x0 or y1 <= y0:
            raise SystemExit(f"--crop {spec!r}: the rectangle is empty or outside the page ({size[0]} x {size[1]} pt)")
        target = out_dir / png_name(pdf, p, offset, f"-crop-{int(x0)}-{int(y0)}-{int(x1)}-{int(y1)}")
        fresh(target, pdf)
        out_dir.mkdir(parents=True, exist_ok=True)
        page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False).save(target)
    return target, size


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

        # A copy with an archive cover: three pages, printed page = PDF page + 10 (the cover is printed 11).
        book = Path(d) / "b.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "archive cover sheet")
        for k in (12, 13):
            doc.new_page().insert_text((72, 72), f"printed page {k} with a misprinted symbol")
        doc.save(book)
        off = 10
        checks["printed label"] = page_label(2, 3, off) == "p.12 (PDF 2/3)" and page_label(2, 3, None) == "p.2/3"
        checks["printed page list"] = page_list("12-13", 3, off) == [2, 3] and page_list("11", 3, off) == [1]
        try:
            page_list("14", 3, off)
            checks["printed range checked"] = False
        except SystemExit as e:
            checks["printed range checked"] = "printed 11..13" in str(e)
        bout = Path(d) / "b.txt"
        dump(book, bout, off)
        checks["dump marks printed pages"] = "===== PDF PAGE 3/3 = PRINTED 13 =====" in bout.read_text()
        bp = render(book, "13", Path(d) / "bpages", 1.0, off)
        checks["render by printed page"] = [p.name for p in bp] == ["b-p013-pdf003.png"]
        cp, size = crop(book, "12:72,50,300,100", Path(d) / "bpages", 2.0, off)
        pix = fitz.Pixmap(str(cp))
        checks["crop size"] = cp.name == "b-p012-pdf002-crop-72-50-300-100.png" and abs(pix.width - 456) <= 2 and abs(pix.height - 100) <= 2
        checks["crop reports page size"] = size == (round(fitz.open(book)[1].rect.width, 1), round(fitz.open(book)[1].rect.height, 1))
        for label, spec in [("crop refuses existing", "12:72,50,300,100"),
                            ("crop refuses empty rect", "12:300,50,72,100"),
                            ("crop refuses outside the page", "12:2000,2000,2100,2100"),
                            ("crop refuses bad spec", "12:1,2,3")]:
            try:
                crop(book, spec, Path(d) / "bpages", 2.0, off)
                checks[label] = False
            except SystemExit:
                checks[label] = True
        digest = hashlib.sha256(book.read_bytes()).hexdigest()
        checks["sha256 matches"] = check_sha256(book, digest.upper()) == digest
        try:
            check_sha256(book, "0" * 64)
            checks["sha256 mismatch stops"] = False
        except SystemExit as e:
            checks["sha256 mismatch stops"] = digest in str(e)
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
    ap.add_argument("--render-dir", type=Path, help="directory for --render and --crop (files never replaced)")
    ap.add_argument("--scale", type=float, default=2.0, help="render scale (default 2.0)")
    ap.add_argument("--crop", action="append", default=[], metavar="PAGE:x0,y0,x1,y1",
                    help="render this rectangle (PDF points, origin top left) of the page at --crop-scale (repeatable)")
    ap.add_argument("--crop-scale", type=float, default=5.0, help="scale of --crop (default 5.0)")
    ap.add_argument("--page-offset", type=int, help="printed page = PDF page + N; page arguments are then printed numbers")
    ap.add_argument("--sha256", help="stop unless the copy's sha256 is this recorded digest")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_intermixed_args()   # the pattern may come after the options (plain parse_args refused it there)
    if a.selftest:
        return selftest()
    if not a.target:
        ap.error("target is required")
    if not (a.pattern or a.dump or a.render or a.crop):
        ap.error("give a pattern, --dump, --render or --crop")
    if (a.render or a.crop) and not a.render_dir:
        ap.error("--render and --crop need --render-dir")
    pdf = resolve(a.target, a.cache)
    if a.sha256:
        print(f"-- sha256 matches the recorded copy: {check_sha256(pdf, a.sha256)}")
    off = a.page_offset
    if a.dump:
        print(f"-- {dump(pdf, a.dump, off)} page(s) -> {a.dump}")
    if a.render:
        for t in render(pdf, a.render, a.render_dir, a.scale, off):
            print(f"-- rendered {t}")
    for spec in a.crop:
        t, (w, h) = crop(pdf, spec, a.render_dir, a.crop_scale, off)
        print(f"-- cropped {t} (page {w} x {h} pt)")
    if a.pattern:
        found = hits(pdf, a.pattern, a.context)
        for page, total, snippet in found:
            print(f"[{page_label(page, total, off)}] ...{snippet}...")
        print(f"-- {len(found)} match(es) in {pdf.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
