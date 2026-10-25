#!/usr/bin/env python3
"""pdf-citation-contexts.py — 論文 PDF が特定の文献をどこで引いているかを拾う: 文献表の番号 ([n] / 行頭の "n.") を正規表現で特定し、 本文の [..] の引用 (範囲 [21–25] を展開) を頁と前後の文脈つきで全部出す。 erratum の下流 sweep (引用している論文が訂正前の式を値として使っているか) を読む入口。 --selftest 内蔵。

使い方
------
  pdf-citation-contexts.py paper.pdf --ref 'PLB=2307\\.12230|138218' --ref 'PRD=2307\\.05932|076001'
  pdf-citation-contexts.py paper.pdf --ref '2307\\.12230' --keywords 'σred|σsum|M_?ψ' --context 400
  pdf-citation-contexts.py paper.pdf --ref ... --json out.json

  --ref NAME=REGEX  文献表の 1 項目を特定する正規表現 (arXiv id・DOI・誌名巻号・題の一部)。 NAME= は省略可、 何回でも
  --keywords REGEX  本文で式を使っていそうな語 (記号・量の名前) の行を頁つきで出す (引用の近くに無くても拾う)
  --context N       引用の前後に出す字数 (既定 350)

出力 = 文献ごとに: 文献表で見つけた番号と、 その行 / 本文の引用 1 件ずつ (頁、 [..] の中身、 前後の文)。
文献表そのものの項目は「文献表」 と印をつける。 引用 0 件・番号 0 件は、 そう書いて終わる (null を黙らない)。

読み方の注意
------------
- 見るのは番号つきの引用 ([12] / [3, 7–9] / Refs. [21–25]) だけ。 著者名と年の引用 (Smith et al. 2020) と上付きの番号は拾わない
  = 番号が見つからなければ「この PDF の引用の形が違う可能性」 と出す。 その PDF は自分で読む。
- 文献表の番号は、 正規表現が当たった行か、 その手前 6 行の中で一番近い行頭の番号を採る。 項目が 2 行以上に折り返していて、
  当たったのが 2 行目以降でも、 次の項目の番号を拾わない (手前だけを見る)。
- 拾うのは「どこで引いているか」 まで。 その文脈で式を値として使っているかは、 出力の文と論文の該当の節を読んで決める
  (引用が文献の列挙の中だけなら、 値は使っていないことが多いが、 判定は人が書く)。
- text 層の無い PDF (scan) は読めない (文字が 0 なら、 そう出す)。

依存 = PyMuPDF (fitz)。 無ければ終了値 3 (検査が走っていない) で止まる。 OS: macOS / Linux / Windows。
"""
from __future__ import annotations

import argparse
import json
import re
import sys

GROUP_RE = re.compile(r"\[(\s*\d{1,4}(?:\s*[–—-]\s*\d{1,4})?(?:\s*[,;]\s*\d{1,4}(?:\s*[–—-]\s*\d{1,4})?)*\s*)\]")
LABEL_LINE_RE = re.compile(r"^\s*(?:\[(\d{1,4})\]|(\d{1,4})\.)(?:\s|$)")


def expand_group(inner: str) -> list[int]:
    """'21, 23–25' → [21, 23, 24, 25] (en dash / em dash / hyphen、 区切りは , か ;)。"""
    out: list[int] = []
    for part in re.split(r"[,;]", inner):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[–—-]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b and b - a < 500:
                out.extend(range(a, b + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def find_ref_labels(lines: list[str], pattern: re.Pattern) -> list[tuple[int, int, str]]:
    """文献表で pattern が当たった行ごとに (番号, 行の index, 行) を返す。 番号は当たった行か手前 6 行の行頭の番号。"""
    found = []
    for j, line in enumerate(lines):
        if not pattern.search(line):
            continue
        label = None
        for k in range(j, max(-1, j - 7), -1):
            m = LABEL_LINE_RE.match(lines[k])
            if m:
                label = int(m.group(1) or m.group(2))
                break
        if label is not None:
            found.append((label, j, line.strip()))
    return found


def find_citations(pages: list[str], label: int, pattern: re.Pattern, context: int) -> list[dict]:
    """本文の [..] のうち label を含むものを全部。 直後に pattern が来る [label] は文献表の項目として印をつける。"""
    hits = []
    for pno, text in enumerate(pages, 1):
        flat = re.sub(r"\s*\n\s*", " ", text)
        for m in GROUP_RE.finditer(flat):
            nums = expand_group(m.group(1))
            if label not in nums:
                continue
            after = flat[m.end(): m.end() + 400]
            is_list = nums == [label] and bool(pattern.search(after))
            a, b = max(0, m.start() - context), min(len(flat), m.end() + context // 2)
            hits.append({"page": pno, "group": m.group(0), "ref_list": is_list, "context": flat[a:b]})
    return hits


def analyze(pages: list[str], refs: list[tuple[str, str]], context: int = 350, keywords: str | None = None) -> dict:
    lines = [ln for text in pages for ln in text.split("\n")]
    result = {"chars": sum(len(t) for t in pages), "refs": {}, "keywords": []}
    for name, rx in refs:
        pat = re.compile(rx, re.I)
        labels = find_ref_labels(lines, pat)
        uniq = sorted({lab for lab, _, _ in labels})
        entry = {"regex": rx, "labels": uniq, "label_lines": [ln for _, _, ln in labels], "citations": {}}
        for lab in uniq:
            entry["citations"][str(lab)] = find_citations(pages, lab, pat, context)
        result["refs"][name] = entry
    if keywords:
        kw = re.compile(keywords)
        for pno, text in enumerate(pages, 1):
            for ln in text.split("\n"):
                if kw.search(ln):
                    result["keywords"].append({"page": pno, "line": ln.strip()[:200]})
    return result


def print_report(res: dict, path: str) -> None:
    print(f"===== {path}  (文字数 {res['chars']})")
    if res["chars"] == 0:
        print("  text 層が無い (scan の PDF?) = この道具では読めない")
        return
    for name, e in res["refs"].items():
        print(f"--- {name}  /{e['regex']}/")
        if not e["labels"]:
            print("  文献表で番号つきの項目が見つからない (引かれていない / 著者名と年の引用 / 上付きの番号 の可能性 = PDF を読む)")
            continue
        for ln in e["label_lines"]:
            print(f"  文献表の行: {ln[:160]}")
        for lab in e["labels"]:
            cites = e["citations"][str(lab)]
            body = [c for c in cites if not c["ref_list"]]
            print(f"  [{lab}]: 本文の引用 {len(body)} 件 (文献表の項目 {len(cites) - len(body)} 件)")
            for c in cites:
                mark = "  (文献表)" if c["ref_list"] else ""
                print(f"    p.{c['page']} {c['group']}{mark}: …{c['context']}…")
    if res["keywords"]:
        print("--- keywords")
        for k in res["keywords"]:
            print(f"  p.{k['page']}: {k['line']}")


def read_pages(path: str) -> list[str]:
    import fitz  # noqa: PLC0415 (import here so that --help works without PyMuPDF)
    with fitz.open(path) as d:
        return [p.get_text() for p in d]


def selftest() -> int:
    fails: list[str] = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    check("expand range en dash", expand_group("21–24"), [21, 22, 23, 24])
    check("expand list + range", expand_group(" 1, 3-5 ; 9 "), [1, 3, 4, 5, 9])
    check("expand em dash", expand_group("7—8"), [7, 8])
    check("expand reversed range ignored", expand_group("9-3"), [])

    lines = [
        "References",
        "[3] A. Author, First paper, J. One 1 (2020) 1.",
        "[4] B. Writer, A second",
        "paper, Phys. Lett. B 846 (2023) 138218 [2307.12230].",
        "[5] C. Other, Third, J. Two 2 (2021) 3.",
        "24. D. Style, Numbered with a dot, arXiv:2401.00001",
    ]
    pat = re.compile(r"2307\.12230")
    labs = find_ref_labels(lines, pat)
    # foil for the bug this tool fixes: the match is on the 2nd line of entry [4]; the next entry is [5].
    # A window that also looks *after* the matched line picks 5.
    check("label from wrapped entry", [x[0] for x in labs], [4])
    check("dot-style label", [x[0] for x in find_ref_labels(lines, re.compile("2401.00001"))], [24])

    pages = [
        "Wave packets were studied before [1, 3-5]. See also Ref. [7] and [40].\nA later remark [4].",
        "\n".join(lines),
    ]
    res = analyze(pages, [("X", r"2307\.12230")], context=40)
    cites = res["refs"]["X"]["citations"]["4"]
    check("citations of [4] (range, single, list entry)", [(c["page"], c["group"], c["ref_list"]) for c in cites],
          [(1, "[1, 3-5]", False), (1, "[4]", False), (2, "[4]", True)])
    res0 = analyze(pages, [("none", r"9999\.99999")])
    check("no label -> empty", res0["refs"]["none"]["labels"], [])

    try:
        import fitz  # noqa: PLC0415
    except ImportError:
        print("selftest: PyMuPDF (fitz) が無いので PDF の往復だけ飛ばした (純粋な部分は通った)" if not fails else "")
        fitz = None
    if fitz is not None:
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            pdf = os.path.join(td, "t.pdf")
            doc = fitz.open()
            for text in pages:
                pg = doc.new_page()
                for i, ln in enumerate(text.split("\n")):
                    pg.insert_text((72, 72 + 14 * i), ln, fontsize=10)
            doc.save(pdf)
            doc.close()
            res_pdf = analyze(read_pages(pdf), [("X", r"2307\.12230")], context=40)
            got = [(c["page"], c["ref_list"]) for c in res_pdf["refs"]["X"]["citations"].get("4", [])]
            check("PDF round trip", got, [(1, False), (1, False), (2, True)])

    if fails:
        print("SELFTEST FAILED")
        for f in fails:
            print("  -", f)
        return 1
    print("selftest OK (範囲の展開 / 折り返した文献表の項目の番号 / 行頭の n. / 本文と文献表の区別 / PDF の往復)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--ref", action="append", default=[], help="NAME=REGEX か REGEX (何回でも)")
    ap.add_argument("--keywords", help="本文で拾う語の正規表現")
    ap.add_argument("--context", type=int, default=350)
    ap.add_argument("--json", help="結果を JSON で保存")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.pdf or not args.ref:
        ap.print_help()
        return 2
    try:
        pages = read_pages(args.pdf)
    except ImportError:
        print("PyMuPDF (fitz) が無い = 検査が走っていない (pip install pymupdf)")
        return 3
    refs = []
    for r in args.ref:
        name, _, rx = r.partition("=") if re.match(r"^[\w.-]+=", r) else ("", "", r)
        refs.append((name or rx, rx))
    res = analyze(pages, refs, args.context, args.keywords)
    print_report(res, args.pdf)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(res, f, indent=1, ensure_ascii=False)
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
