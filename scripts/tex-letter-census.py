#!/usr/bin/env python3
"""LaTeX の数式の中の 1 文字の記号 (指定した字) を文脈つきで列挙し (添字の中か外か、 \\text の中の $…$ も拾い、 \\text・\\mathrm・\\label などの引数と comment・verbatim は除く)、 添字の中の字を macro に替える案を出す・当てる (括弧の無い添字は {…} で包む): 記法の一括変更を 1 文字ずつ判定する入口。--selftest 内蔵、規律 = claude-config conventions/paper-audit.md#single-letter-macro-pass

なぜ要るか: frame 添字を太字の macro にする・揺らぎに hat を付ける、 のような 1 文字の記法変更は、
一括の sed では必ず壊れる (同じ字が係数・次元・冪・場の種類のラベル・関数名・一般のベクトルにも使われる)。
人が 1 つずつ判定するには、 (1) 判定する候補を数式の文脈だけに絞って全部並べ、 (2) 機械で当てられる部分
(添字の中) の案を行ごとに見せ、 (3) 添字の外の候補 (関数の引数・散文の $b$ など) は手で当てるよう残す、
の 3 つが要る。 本 script はその 1 と 2 を持つ。 当てた後の純粋性 (記法以外が変わっていないか) は
check-rename-purity.py で、 組版は compare-tex-builds.py で見る。

使い方:

    # 1. 候補の一覧 (行番号・添字の中 group / 外 base・字・前後の文脈)
    python3 tex-letter-census.py notes.tex --letters abcdefg

    # 2. 添字の中の字を macro に替える案 (-old / +new を行ごとに表示。 書かない)
    python3 tex-letter-census.py notes.tex --letters abcdefg --propose --macro '\\b{}' --macro-map 'f=\\bff'

    # 3. 案から除く字・行を指定して当てる
    python3 tex-letter-census.py notes.tex --letters abcdefg --propose --macro '\\b{}' \\
        --exclude-letters e --skip-lines 1768-1768 --write

- `--macro` の `{}` が字に置き換わる (`\\b{}` + a → `\\ba`)。 字ごとの例外は `--macro-map 'f=\\bff'`
  (LaTeX の予約語 `\\bf` を避ける例)。 括弧の無い添字 (`x^a`) は `x^{\\ba}` にする
  (`x^\\ba` は macro が `\\textbf{…}` に展開されると壊れる)。 macro の直後に案の外の英字が続くときは
  `{}` を挟む (`^{ax}` → `^{\\ba{}x}`)。
- 数式とみなす範囲 = `$…$` `$$…$$` `\\(…\\)` `\\[…\\]` と数式環境 (equation / align / gather /
  multline / eqnarray / displaymath、 星つきも) の中。 引数を数式として扱う自前の wrapper macro は
  `--math-macro al --math-macro als` で足す。
- 除く範囲 = comment、 verbatim 環境、 `\\text` `\\textbf` `\\mathrm` `\\mathbf` `\\operatorname` `\\label`
  `\\ref` `\\cite` などの引数 (ただし引数の中の `$…$` は数式として拾う)、 `\\rm` `\\it` `\\bf` の切り替えから
  group の終わりまで、 アクセント (`\\hat` `\\bar` `\\tilde` ほか) の付いた字 (`O(\\hat e)` の e は添字でなく記号)。
- 案は判定ではない: 添字の中にあっても frame 添字でない字 (時空の次元 `d^d`、 冪 `(\\ell^2)^a`、
  場の種類のラベル `J^{e\\omega}`) が混ざる。 全行を読み、 違うものは `--exclude-letters` /
  `--skip-lines` で外す (規律の本文 = 上の paper-audit.md の節)。
"""
from __future__ import annotations

import argparse
import bisect
import re
import sys
import tempfile
from pathlib import Path

MATH_ENVS = r"equation|align|alignat|gather|multline|eqnarray|displaymath|flalign"
BEGIN_MATH = re.compile(r"\\begin\{(?:" + MATH_ENVS + r")\*?\}")
END_MATH = re.compile(r"\\end\{(?:" + MATH_ENVS + r")\*?\}")
VERB_BEGIN = re.compile(r"\\begin\{(verbatim|lstlisting|minted)\*?\}")
TEXTLIKE = (
    "text", "textrm", "textit", "textbf", "texttt", "textsf", "textup", "mbox", "emph",
    "mathrm", "mathit", "mathbf", "mathsf", "mathtt", "mathbb", "mathcal", "mathfrak",
    "operatorname", "label", "ref", "eqref", "pageref", "cite", "citep", "citet", "url",
    "href", "begin", "end", "input", "include", "includegraphics", "newcommand",
    "renewcommand", "DeclareMathOperator", "section", "subsection", "subsubsection",
    "paragraph", "title", "author", "date", "hypersetup", "usepackage", "documentclass",
    "bibliography", "bibliographystyle", "tx",
)
SWITCHES = ("rm", "it", "bf", "sf", "tt")
ACCENTS = ("hat", "bar", "tilde", "vec", "dot", "ddot", "check", "breve", "acute", "grave",
           "widehat", "widetilde", "overline", "underline", "h", "ol", "wh", "wt")


def blank_comments(src: str) -> str:
    """Replace comment text by spaces, keeping every offset (an escaped \\% stays)."""
    out = []
    for line in src.split("\n"):
        buf = []
        i = 0
        while i < len(line):
            if line[i] == "\\" and i + 1 < len(line):
                buf.append(line[i:i + 2])
                i += 2
                continue
            if line[i] == "%":
                buf.append(" " * (len(line) - i))
                break
            buf.append(line[i])
            i += 1
        out.append("".join(buf))
    return "\n".join(out)


def group_end(text: str, k: int) -> int:
    """Index of the brace closing the group that opens at text[k] == '{' (len-1 if unbalanced)."""
    depth = 0
    j = k
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return len(text) - 1


def masks(text: str, math_macros: tuple[str, ...] = ()) -> tuple[list[bool], list[bool]]:
    """(math, skip) masks over text offsets."""
    n = len(text)
    math = [False] * n
    skip = [False] * n
    i = 0
    inline = False
    display = False
    envs = 0
    verb_end = None
    wrapper = re.compile(r"\\(" + "|".join(map(re.escape, math_macros)) + r")\{") if math_macros else None
    while i < n:
        if verb_end is not None:
            if text.startswith(verb_end, i):
                i += len(verb_end)
                verb_end = None
            else:
                skip[i] = True
                i += 1
            continue
        m = VERB_BEGIN.match(text, i)
        if m:
            verb_end = "\\end{" + m.group(1)
            i = m.end()
            continue
        m = BEGIN_MATH.match(text, i)
        if m:
            envs += 1
            i = m.end()
            continue
        m = END_MATH.match(text, i)
        if m:
            envs = max(0, envs - 1)
            i = m.end()
            continue
        if wrapper is not None and not (inline or display or envs):
            m = wrapper.match(text, i)
            if m:
                e = group_end(text, m.end() - 1)
                for k in range(m.end(), e):
                    math[k] = True
                i = e + 1
                continue
        if text.startswith("\\[", i):
            display = True
            i += 2
            continue
        if text.startswith("\\]", i):
            display = False
            i += 2
            continue
        if text.startswith("\\(", i):
            inline = True
            i += 2
            continue
        if text.startswith("\\)", i):
            inline = False
            i += 2
            continue
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "$":
            if text.startswith("$$", i):
                display = not display
                i += 2
            else:
                inline = not inline
                i += 1
            continue
        if inline or display or envs:
            math[i] = True
        i += 1
    textlike = re.compile(r"\\(" + "|".join(TEXTLIKE) + r")\*?\s*\{")
    for m in textlike.finditer(text):
        e = group_end(text, m.end() - 1)
        inner = False
        for k in range(m.start(), e + 1):
            if text[k] == "$" and (k == 0 or text[k - 1] != "\\"):
                inner = not inner
                skip[k] = True
                continue
            if not inner:
                skip[k] = True
    for m in re.finditer(r"\\(" + "|".join(SWITCHES) + r")(?![A-Za-z])", text):
        depth = 0
        k = m.end()
        while k < n:
            c = text[k]
            if c == "\\":
                k += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0:
                    break
                depth -= 1
            skip[k] = True
            k += 1
    return math, skip


def scan(src: str, letters: str, math_macros: tuple[str, ...] = ()):
    """Yield (offset, letter, where, single) for every candidate letter in math mode.

    where = "group" (inside a ^/_ group or a one-character ^x/_x) or "base" (a stand-alone letter
    elsewhere in math). single = True for an unbraced ^x/_x.
    """
    text = blank_comments(src)
    math, skip = masks(text, math_macros)
    n = len(text)
    # the letter that an accent decorates (\hat e, \bar{e}) is a symbol, not an index
    for m in re.finditer(r"\\(" + "|".join(ACCENTS) + r")(?![A-Za-z])\s*", text):
        j = m.end()
        if j < n and text[j] == "{":
            for k in range(j, group_end(text, j) + 1):
                skip[k] = True
        elif j < n and text[j].isalpha():
            skip[j] = True
    in_group: dict[int, bool] = {}
    for m in re.finditer(r"[\^_]", text):
        k = m.start()
        if not math[k] or skip[k] or (k > 0 and text[k - 1] == "\\"):
            continue
        j = k + 1
        while j < n and text[j] == " ":
            j += 1
        if j >= n:
            continue
        if text[j] == "{":
            e = group_end(text, j)
            p = j + 1
            while p < e:
                c = text[p]
                if c == "\\":
                    q = p + 1
                    while q < e and text[q].isalpha():
                        q += 1
                    p = q if q > p + 1 else q + 1
                    continue
                if c in letters and not skip[p]:
                    in_group[p] = False
                p += 1
        elif text[j] in letters and not (j + 1 < n and text[j + 1].isalpha()) and not skip[j]:
            in_group[j] = True
    out = []
    for p, single in in_group.items():
        out.append((p, text[p], "group", single))
    for m in re.finditer(r"(?<![A-Za-z\\])([A-Za-z])(?![A-Za-z])", text):
        p = m.start(1)
        if p in in_group or text[p] not in letters or not math[p] or skip[p]:
            continue
        out.append((p, text[p], "base", False))
    out.sort()
    return out


def line_index(src: str):
    starts = [0]
    for k, c in enumerate(src):
        if c == "\n":
            starts.append(k + 1)
    return lambda p: bisect.bisect_right(starts, p)


def parse_ranges(specs: list[str]) -> list[tuple[int, int]]:
    out = []
    for spec in specs:
        for part in spec.split(","):
            lo, _, hi = part.partition("-")
            out.append((int(lo), int(hi or lo)))
    return out


def propose(src: str, letters: str, macro: str, macro_map: dict[str, str], exclude: str = "",
            skip_lines: list[tuple[int, int]] | None = None, math_macros: tuple[str, ...] = ()):
    """Return (new_src, changed line numbers) with every in-group candidate replaced by its macro."""
    line_of = line_index(src)
    cands = [c for c in scan(src, letters, math_macros) if c[2] == "group"]
    targets = {p for p, ch, _w, _s in cands if ch not in exclude}
    skip_lines = skip_lines or []
    out = list(src)
    changed = set()
    for p, ch, _where, single in reversed(cands):
        if p not in targets:
            continue
        ln = line_of(p)
        if any(lo <= ln <= hi for lo, hi in skip_lines):
            continue
        rep = macro_map.get(ch, macro.replace("{}", ch))
        nxt = src[p + 1] if p + 1 < len(src) else ""
        if nxt.isalpha() and (p + 1) not in targets:
            rep += "{}"
        if single:
            rep = "{" + rep + "}"
        out[p] = rep
        changed.add(ln)
    return "".join(out), sorted(changed)


def selftest() -> int:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and cond

    doc = "\n".join([
        r"\documentclass{article}",
        r"\begin{document}",
        r"Frame $\gamma^{a}_{E}p_{a}$ and $x^b$ and $\mathrm{a}_c$.",  # 3
        r"\text{ at $(b,\nu)$ }",  # 4: text, inner math
        r"$V(b,\nu)\,J^{e\omega}\,d^{d}\ell$ % comment a_b",  # 5
        r"\begin{verbatim}",
        r"x^a",  # 7: verbatim
        r"\end{verbatim}",
        r"\begin{align}",
        r"T^{(\rm transcribed)}_{ax} = g_{f}",  # 10
        r"\end{align}",
        r"\al{ q_{d} }",  # 12: wrapper macro
        r"$\mathcal{L}_{O(\hat e)} + \bar{a}_{b}$",  # 13: accent arguments
        r"\end{document}",
    ])
    rows = scan(doc, "abcdef")
    line_of = line_index(doc)
    seen = {(line_of(p), ch, w) for p, ch, w, _s in rows}
    check("subscript and superscript groups are found", {(3, "a", "group")} <= seen)
    check("one-character superscript is found", (3, "b", "group") in seen)
    check("\\mathrm argument is skipped", (3, "a", "base") not in seen and (3, "c", "group") in seen)
    check("$...$ inside \\text is scanned", (4, "b", "base") in seen)
    check("function argument is a base candidate", (5, "b", "base") in seen)
    check("comment is skipped", not any(ln == 5 and ch == "a" for ln, ch, _w in seen))
    check("verbatim is skipped", not any(ln == 7 for ln, _c, _w in seen))
    check("\\rm switch is skipped to the group end", not any(ln == 10 and ch in "bde" for ln, ch, _w in seen))
    check("math environment is scanned", (10, "a", "group") in seen and (10, "f", "group") in seen)
    check("wrapper macro is not math by default", not any(ln == 12 for ln, _c, _w in seen))
    check("accent argument is not an index", not any(ln == 13 and ch in "ae" for ln, ch, _w in seen)
          and (13, "b", "group") in seen)
    seen_al = {(line_of(p), ch, w) for p, ch, w, _s in scan(doc, "abcdef", ("al",))}
    check("--math-macro makes the wrapper math", (12, "d", "group") in seen_al)
    new, changed = propose(doc, "abcdef", r"\b{}", {"f": r"\bff"}, exclude="e")
    lines = new.split("\n")
    check("group letters get the macro", r"\gamma^{\ba}_{E}p_{\ba}" in lines[2])
    check("unbraced superscript is wrapped in braces", r"x^{\bb}" in lines[2])
    check("species label excluded by --exclude-letters", r"J^{e\omega}" in lines[4])
    check("dimension in a group is proposed (to be judged by a person)", r"d^{\bd}" in lines[4])
    check("base candidates are not changed", r"V(b,\nu)" in lines[4] and r"$(b,\nu)$" in lines[3])
    check("macro-map overrides the pattern", r"g_{\bff}" in lines[9])
    check("a following non-target letter is separated", r"_{\ba{}x}" in lines[9])
    check("verbatim untouched", lines[6] == "x^a")
    new2, _ = propose(doc, "abcdef", r"\b{}", {}, skip_lines=[(3, 3)])
    check("--skip-lines keeps the line", new2.split("\n")[2] == doc.split("\n")[2])
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "x.tex"
        path.write_text(doc, encoding="utf-8")
        rc = main([str(path), "--letters", "abcdef", "--propose", "--macro", r"\b{}", "--write"])
        check("--write applies the proposal", rc == 0 and r"x^{\bb}" in path.read_text(encoding="utf-8"))
    print("selftest:", "ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("--letters", help="letters to look for, e.g. abcdefg")
    ap.add_argument("--propose", action="store_true", help="show the macro proposal for in-group letters")
    ap.add_argument("--macro", default=r"\b{}", help=r"macro pattern, {} = the letter (default \b{})")
    ap.add_argument("--macro-map", action="append", default=[], help=r"per-letter override, e.g. f=\bff")
    ap.add_argument("--exclude-letters", default="", help="letters left out of the proposal")
    ap.add_argument("--skip-lines", action="append", default=[], help="line ranges left out, e.g. 10-12,40")
    ap.add_argument("--math-macro", action="append", default=[], help="macro whose argument is math (e.g. al)")
    ap.add_argument("--write", action="store_true", help="write the proposal to the file")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.file or not args.letters:
        ap.error("FILE and --letters are required")
    path = Path(args.file)
    src = path.read_text(encoding="utf-8")
    math_macros = tuple(args.math_macro)
    if not args.propose:
        line_of = line_index(src)
        rows = scan(src, args.letters, math_macros)
        for p, ch, where, single in rows:
            ctx = src[max(0, p - 25):p + 15].replace("\n", " ")
            tag = where + ("*" if single else "")
            print(f"{line_of(p):5d} {tag:6s} {ch}  …{ctx}…")
        groups = sum(1 for r in rows if r[2] == "group")
        print(f"# {len(rows)} candidates ({groups} in sub/superscript groups, {len(rows) - groups} elsewhere; * = unbraced)",
              file=sys.stderr)
        return 0
    macro_map = {}
    for item in args.macro_map:
        k, _, v = item.partition("=")
        macro_map[k] = v
    new, changed = propose(src, args.letters, args.macro, macro_map, args.exclude_letters,
                           parse_ranges(args.skip_lines), math_macros)
    old_lines, new_lines = src.split("\n"), new.split("\n")
    for ln in changed:
        print(f"{ln:5d} - {old_lines[ln - 1]}\n      + {new_lines[ln - 1]}")
    print(f"# {len(changed)} line(s) {'written' if args.write else 'proposed (not written)'}", file=sys.stderr)
    if args.write:
        path.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
