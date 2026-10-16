#!/usr/bin/env python3
"""review markup cleaner: 共著 review 用の着色と著者間問答を LaTeX source から外す (投稿前清掃 + 清掃版どうしの diff 用)。

なぜ: 共著 review 中の原稿は「新規箇所を \\red{...} で着色」「[XX]: 質問 / [YY: 返答] を本文に置く」で回る。
投稿前にはこれを落とす必要があり (組版 PDF に残ると submission blocker)、
また **AI pass の前後を latexdiff で読み合わせるとき、着色の差が実質の差を埋める**ので、
両側に同じ清掃を当ててから diff を取ると実質の変更だけが見える。
AI の文を色で区別していた原稿を地の文に戻す (章ごとに著者が裁定する) ときも同じ道具で、範囲を限って外す。
正本 = conventions/edit-intent-record.md#implementation-pass-discipline / #submission-cleanup。

する事 (中身の文は書き換えない):
  1. 問答ブロックの削除    --qa-prefix で始まる \\<macro>{...} を丸ごと消す (削除前の全文は stdout に出さない = 呼び元が diff で持つ)。
                           --qa-to-comment なら消さずに % コメント行にする
  2. 注記の comment 化      --comment-macro の \\<name>{...} は全体を % コメント行にする (印字しない著者宛ての注記 = \\CL{...} 等)
  3. 着色の解除            残りの \\<macro>{...} (--macro は繰り返し可) と {\\color{<name>}...} (--color) を中身だけに開く
  4. 日付の非表示          --suppress-date で \\maketitle の直前に \\date{} を挿す (既に \\date があれば何もしない)

コメント行 (% ...) の中の macro は触らない。数式・改行・字下げは保存する。
文中の注記を comment にするときは、その注記だけを自分の行に出す (同じ行の続きの文を comment に巻き込まない)。
--from-line/--to-line (1 始まり、両端を含む) を付けると 1-3 はその行の中で開く wrapper だけに当て、範囲の外は変えない。
範囲の中で開いて外で閉じる wrapper があれば止める (範囲を広げて打ち直す)。

  python3 review-markup-clean.py in.tex out.tex --macro red --qa-prefix '\\bf [XX]' --qa-prefix '[YY:' --suppress-date
  python3 review-markup-clean.py paper.tex paper.tex --macro cl --color Orange --comment-macro CL \\
      --qa-prefix '[Claude' --qa-to-comment --from-line 120 --to-line 860
  python3 review-markup-clean.py --selftest
"""
from __future__ import annotations

import argparse
import sys


def _in_comment(text: str, idx: int) -> bool:
    """idx がコメント (エスケープされていない % 以降) の中か。"""
    k = text.rfind("\n", 0, idx) + 1
    while k < idx:
        c = text[k]
        if c == "\\":
            k += 2
            continue
        if c == "%":
            return True
        k += 1
    return False


def _match_close(text: str, start: int) -> int:
    """start = 開き { の次の位置。対応する } の位置を返す (コメントとエスケープを飛ばす)。"""
    depth = 1
    k = start
    while k < len(text):
        c = text[k]
        if c == "\\":
            k += 2
            continue
        if c == "%":
            nl = text.find("\n", k)
            k = len(text) if nl < 0 else nl + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    raise ValueError("unbalanced \\%s{...} starting at %d" % ("macro", start))


def _next_token(text: str, pos: int, tokens) -> tuple[int, str] | None:
    """pos 以降で、コメントの外にある最も早い token の (位置, token)。"""
    best = None
    for tok in tokens:
        p = pos
        while True:
            i = text.find(tok, p)
            if i < 0:
                break
            if _in_comment(text, i):
                p = i + len(tok)
                continue
            if best is None or i < best[0]:
                best = (i, tok)
            break
    return best


def _as_comment(text: str, i: int, end: int, content: str) -> tuple[str, int]:
    """text[i:end] (wrapper 全体) を % コメント行に置き換えた text と、続きを探す位置を返す。
    同じ行の前後に文があれば、注記だけを自分の行に出す (前後の文は comment にしない、段落も切らない)。"""
    line_start = text.rfind("\n", 0, i) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    before, after = text[line_start:i], text[end:line_end]
    body = content.strip("\n").split("\n")
    block = "\n".join("% " + ln.strip() if ln.strip() else "%" for ln in body)
    head = before.rstrip() + "\n" if before.strip() else before
    tail = "\n" + after.lstrip(" \t") if after.strip() else ""
    text = text[:line_start] + head + block + tail + text[line_end:]
    return text, line_start + len(head) + len(block)


def _clean_segment(text, macros, colors, comment_macros, qa_prefixes, qa_to_comment, counts):
    kinds = {}
    for m in macros:
        kinds["\\" + m + "{"] = "macro"
    for c in comment_macros:
        kinds["\\" + c + "{"] = "comment"
    for name in colors:
        kinds["{\\color{" + name + "}"] = "color"
    pos = 0
    while True:
        found = _next_token(text, pos, kinds)
        if not found:
            return text
        i, tok = found
        j = i + len(tok)
        k = _match_close(text, j)
        content = text[j:k]
        kind = kinds[tok]
        is_qa = kind == "macro" and any(content.lstrip().startswith(p) for p in qa_prefixes)
        if kind == "comment" or (is_qa and qa_to_comment):
            text, pos = _as_comment(text, i, k + 1, content)
            counts["comment"] += 1
            continue
        if is_qa:
            end = k + 1
            if end < len(text) and text[end] == " ":
                end += 1
            text = text[:i] + text[end:]
            line_start = text.rfind("\n", 0, i) + 1
            line_end = text.find("\n", i)
            line_end = len(text) if line_end < 0 else line_end
            if text[line_start:line_end].strip() == "":
                text = text[:line_start] + text[line_end + 1:]
                pos = line_start
            else:
                pos = i
            counts["qa"] += 1
            continue
        repl = content
        if (i == 0 or text[i - 1] == "\n") and repl.startswith("\n"):
            repl = repl[1:]  # 行頭の \macro{ が単独行なら、その改行は落とす
        close_line_start = text.rfind("\n", 0, k) + 1
        close_alone = text[close_line_start:k].strip() == "" and (k + 1 == len(text) or text[k + 1] == "\n")
        if close_alone:
            text = text[:i] + repl.rstrip("\n") + "\n" + text[k + 2:]
        else:
            text = text[:i] + repl + text[k + 1:]
        counts["unwrap"] += 1
        pos = i


def clean(text: str, macro: str = "red", qa_prefixes: tuple[str, ...] = (), suppress_date: bool = False, *,
          macros: tuple[str, ...] | None = None, colors: tuple[str, ...] = (),
          comment_macros: tuple[str, ...] = (), qa_to_comment: bool = False,
          line_range: tuple[int, int] | None = None):
    """(cleaned text, {'qa': n, 'comment': n, 'unwrap': n, 'date': 0|1}) を返す。
    macros を渡さなければ macro 1 つ (既定 red)。line_range = (first, last)、1 始まりで両端を含む。"""
    counts = {"qa": 0, "comment": 0, "unwrap": 0, "date": 0}
    args = (tuple(macros) if macros is not None else (macro,), tuple(colors), tuple(comment_macros),
            tuple(qa_prefixes), qa_to_comment, counts)
    if line_range is None:
        text = _clean_segment(text, *args)
    else:
        first, last = line_range
        if not 1 <= first <= last:
            raise ValueError("line range must satisfy 1 <= from <= to (got %d-%d)" % (first, last))
        starts = [0] + [n + 1 for n, c in enumerate(text) if c == "\n"]
        start = starts[first - 1] if first - 1 < len(starts) else len(text)
        end = starts[last] if last < len(starts) else len(text)
        try:
            seg = _clean_segment(text[start:end], *args)
        except ValueError:
            raise ValueError("a wrapper opened in lines %d-%d closes outside them; widen the range" % (first, last))
        text = text[:start] + seg + text[end:]

    if suppress_date:
        # コメント行の言及 (% ... \maketitle ...) と \@maketitle の再定義は数えない
        live = [i for i in range(len(text))
                if text.startswith("\\maketitle", i) and not _in_comment(text, i)]
        live_date = [i for i in range(len(text))
                     if text.startswith("\\date{", i) and not _in_comment(text, i)]
        if not live_date:
            if len(live) != 1:
                raise ValueError("--suppress-date needs exactly one uncommented \\maketitle (found %d)" % len(live))
            i = live[0]
            text = text[:i] + "\\date{}" + text[i:]
            counts["date"] = 1
    return text, counts


def _selftest() -> int:
    ok = True
    n_checks = 0

    def check(name, got, want):
        nonlocal ok, n_checks
        n_checks += 1
        if got != want:
            ok = False
            print("FAIL %s\n  got : %r\n  want: %r" % (name, got, want))

    def raises(name, fn):
        nonlocal ok, n_checks
        n_checks += 1
        try:
            fn()
            ok = False
            print("FAIL %s: no exception" % name)
        except ValueError:
            pass

    src = (
        "Body one.\n"
        "\\red{\\bf [XX]: Is this right?} \\red{[YY: yes, corrected.]}\n"
        "Body two \\red{coloured inline} tail.\n"
        "\\red{\n"
        "A whole paragraph under review.\n"
        "Second line of it.\n"
        "}\n"
        "% \\red{commented out, must survive}\n"
        "Math \\red{$a_{\\{b\\}}+c$} stays.\n"
    )
    out, n = clean(src, macro="red", qa_prefixes=("\\bf [XX]", "[YY:"))
    check("qa count", n["qa"], 2)
    check("unwrap count", n["unwrap"], 3)
    check(
        "body",
        out,
        "Body one.\n"
        "Body two coloured inline tail.\n"
        "A whole paragraph under review.\n"
        "Second line of it.\n"
        "% \\red{commented out, must survive}\n"
        "Math $a_{\\{b\\}}+c$ stays.\n",
    )
    check("no macro left outside comments", "\\red{" in out.replace("% \\red{commented out, must survive}", ""), False)

    # foil 1: 問答 prefix を渡さなければ問答も「着色解除」されるだけ (削除しない)
    out2, n2 = clean("\\red{\\bf [XX]: q}\n", macro="red", qa_prefixes=())
    check("no qa prefixes -> unwrap only", (out2, n2["qa"], n2["unwrap"]), ("\\bf [XX]: q\n", 0, 1))

    # foil 2: 別 macro 名
    out3, n3 = clean("\\cSM{blue text} and \\red{kept}\n", macro="cSM", qa_prefixes=())
    check("macro name honoured", (out3, n3["unwrap"]), ("blue text and \\red{kept}\n", 1))

    # foil 3: 入れ子の brace と footnote の中
    out4, n4 = clean("x\\footnote{note \\red{col} end}\n", macro="red", qa_prefixes=())
    check("inside footnote", (out4, n4["unwrap"]), ("x\\footnote{note col end}\n", 1))

    # foil 4: 日付
    out5, n5 = clean("\\title{T}\\maketitle\n", suppress_date=True)
    check("date inserted", (out5, n5["date"]), ("\\title{T}\\date{}\\maketitle\n", 1))
    out6, n6 = clean("\\date{2020}\\maketitle\n", suppress_date=True)
    check("existing date kept", (out6, n6["date"]), ("\\date{2020}\\maketitle\n", 0))
    out7, n7 = clean("% see \\maketitle below\n\\title{T}\\maketitle\n", suppress_date=True)
    check("commented mention ignored", (out7, n7["date"]),
          ("% see \\maketitle below\n\\title{T}\\date{}\\maketitle\n", 1))
    out8, n8 = clean("%\\date{old}\n\\maketitle\n", suppress_date=True)
    check("commented date does not count as present", (out8, n8["date"]), ("%\\date{old}\n\\date{}\\maketitle\n", 1))

    # foil 5: 閉じ括弧の不足は例外
    raises("unbalanced", lambda: clean("\\red{unbalanced\n", macro="red"))

    # 複数の macro と色の群 (入れ子の macro も外れる)
    kw = dict(macros=("cl",), colors=("Orange",))
    out9, n9 = clean("{\\color{Orange}\nPara with \\cl{nested} macro.\n}\nx {\\color{Orange}y} z \\cl{w}\n", **kw)
    check("color group + nested macro", (out9, n9["unwrap"]), ("Para with nested macro.\nx y z w\n", 4))
    out10, _ = clean("\\red{a} \\cl{b}\n", macros=("red", "cl"))
    check("several macros", out10, "a b\n")
    out11, n11 = clean("{\\color{Blue}keep} {\\color{Orange}go}\n", colors=("Orange",), macros=())
    check("other colour untouched", (out11, n11["unwrap"]), ("{\\color{Blue}keep} go\n", 1))

    # 注記の comment 化: 行全体 / 文中 (前後の文を巻き込まない) / 複数行
    out12, n12 = clean("\\CL{Please check this.}\n", macros=(), comment_macros=("CL",))
    check("comment macro, whole line", (out12, n12["comment"]), ("% Please check this.\n", 1))
    out13, _ = clean("Text \\CL{note} more text.\n", macros=(), comment_macros=("CL",))
    check("comment macro, mid-line", out13, "Text\n% note\nmore text.\n")
    out14, _ = clean("\\CL{line one\n\nline two}\n", macros=(), comment_macros=("CL",))
    check("comment macro, multi-line", out14, "% line one\n%\n% line two\n")
    out15, n15 = clean("A \\cl{[Claude] check sign} B \\cl{kept}\n", macros=("cl",),
                       qa_prefixes=("[Claude",), qa_to_comment=True)
    check("qa to comment", (out15, n15["comment"], n15["qa"], n15["unwrap"]),
          ("A\n% [Claude] check sign\nB kept\n", 1, 0, 1))

    # 行範囲: 範囲の外は変えない / 範囲が wrapper を切ったら止める
    out16, n16 = clean("\\red{1}\n\\red{2}\n\\red{3}\n", line_range=(2, 2))
    check("line range", (out16, n16["unwrap"]), ("\\red{1}\n2\n\\red{3}\n", 1))
    out17, _ = clean("\\red{1}\n\\red{2}\n", line_range=(2, 9))
    check("range past the end", out17, "\\red{1}\n2\n")
    raises("range cuts a wrapper", lambda: clean("\\red{a\nb}\n", line_range=(1, 1)))
    raises("bad range", lambda: clean("x\n", line_range=(3, 2)))

    print("selftest OK (%d checks)" % n_checks if ok else "selftest FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="strip review colouring and author Q&A from a LaTeX source")
    ap.add_argument("source", nargs="?", help="input .tex")
    ap.add_argument("dest", nargs="?", help="output .tex (may be the same file)")
    ap.add_argument("--macro", action="append", default=None,
                    help="colour macro name without the backslash, unwrapped (repeatable; default: red, "
                         "only when neither --color nor --comment-macro is given)")
    ap.add_argument("--color", action="append", default=[],
                    help="unwrap {\\color{NAME}...} groups (repeatable), e.g. Orange")
    ap.add_argument("--comment-macro", action="append", default=[],
                    help="turn the whole \\NAME{...} into %% comment lines (repeatable), e.g. CL")
    ap.add_argument("--qa-prefix", action="append", default=[],
                    help="delete a \\<macro>{...} whose content starts with this (repeatable), e.g. '\\bf [XX]'")
    ap.add_argument("--qa-to-comment", action="store_true",
                    help="turn --qa-prefix blocks into %% comment lines instead of deleting them")
    ap.add_argument("--from-line", type=int, help="first line to clean (1-based, inclusive)")
    ap.add_argument("--to-line", type=int, help="last line to clean (1-based, inclusive)")
    ap.add_argument("--suppress-date", action="store_true", help="insert \\date{} before \\maketitle")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if not a.source or not a.dest:
        ap.error("source and dest are required (or use --selftest)")
    text = open(a.source, encoding="utf-8").read()
    line_range = None
    if a.from_line is not None or a.to_line is not None:
        line_range = (a.from_line or 1, a.to_line or text.count("\n") + 1)
    out, n = clean(text, qa_prefixes=tuple(a.qa_prefix), suppress_date=a.suppress_date,
                   macros=tuple(a.macro or ([] if a.color or a.comment_macro else ["red"])), colors=tuple(a.color),
                   comment_macros=tuple(a.comment_macro), qa_to_comment=a.qa_to_comment, line_range=line_range)
    open(a.dest, "w", encoding="utf-8").write(out)
    print("%s -> %s: Q&A deleted=%d, commented=%d, colouring unwrapped=%d, date suppressed=%d"
          % (a.source, a.dest, n["qa"], n["comment"], n["unwrap"], n["date"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
