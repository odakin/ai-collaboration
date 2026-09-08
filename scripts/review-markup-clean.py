#!/usr/bin/env python3
"""review markup cleaner: 共著 review 用の着色と著者間問答を LaTeX source から外す (投稿前清掃 + 清掃版どうしの diff 用)。

なぜ: 共著 review 中の原稿は「新規箇所を \\red{...} で着色」「[XX]: 質問 / [YY: 返答] を本文に置く」で回る。
投稿前にはこれを落とす必要があり (組版 PDF に残ると submission blocker)、
また **AI pass の前後を latexdiff で読み合わせるとき、着色の差が実質の差を埋める**ので、
両側に同じ清掃を当ててから diff を取ると実質の変更だけが見える。
正本 = conventions/edit-intent-record.md#implementation-pass-discipline。

する事は 3 つだけ (中身は書き換えない):
  1. 問答ブロックの削除    --qa-prefix で始まる \\<macro>{...} を丸ごと消す (削除前の全文は stdout に出さない = 呼び元が diff で持つ)
  2. 着色の解除            残りの \\<macro>{...} を中身だけに開く
  3. 日付の非表示          --suppress-date で \\maketitle の直前に \\date{} を挿す (既に \\date があれば何もしない)

コメント行 (% ...) の中の macro は触らない。数式・改行・字下げは保存する。

  python3 review-markup-clean.py in.tex out.tex --macro red --qa-prefix '\\bf [XX]' --qa-prefix '[YY:' --suppress-date
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


def clean(text: str, macro: str = "red", qa_prefixes: tuple[str, ...] = (), suppress_date: bool = False):
    """(cleaned text, {'qa': n, 'unwrap': n, 'date': 0|1}) を返す。"""
    open_tok = "\\" + macro + "{"
    counts = {"qa": 0, "unwrap": 0, "date": 0}
    pos = 0
    while True:
        i = text.find(open_tok, pos)
        if i < 0:
            break
        if _in_comment(text, i):
            pos = i + len(open_tok)
            continue
        j = i + len(open_tok)
        k = _match_close(text, j)
        content = text[j:k]
        if any(content.lstrip().startswith(p) for p in qa_prefixes):
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

    if suppress_date and "\\date{" not in text:
        if text.count("\\maketitle") != 1:
            raise ValueError("--suppress-date needs exactly one \\maketitle (found %d)" % text.count("\\maketitle"))
        text = text.replace("\\maketitle", "\\date{}\\maketitle", 1)
        counts["date"] = 1
    return text, counts


def _selftest() -> int:
    ok = True

    def check(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print("FAIL %s\n  got : %r\n  want: %r" % (name, got, want))

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

    # foil 5: 閉じ括弧の不足は例外
    try:
        clean("\\red{unbalanced\n", macro="red")
        ok = False
        print("FAIL unbalanced: no exception")
    except ValueError:
        pass

    print("selftest OK (7 checks)" if ok else "selftest FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="strip review colouring and author Q&A from a LaTeX source")
    ap.add_argument("source", nargs="?", help="input .tex")
    ap.add_argument("dest", nargs="?", help="output .tex")
    ap.add_argument("--macro", default="red", help="colour macro name without the backslash (default: red)")
    ap.add_argument("--qa-prefix", action="append", default=[],
                    help="delete a \\<macro>{...} whose content starts with this (repeatable), e.g. '\\bf [XX]'")
    ap.add_argument("--suppress-date", action="store_true", help="insert \\date{} before \\maketitle")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if not a.source or not a.dest:
        ap.error("source and dest are required (or use --selftest)")
    text = open(a.source, encoding="utf-8").read()
    out, n = clean(text, macro=a.macro, qa_prefixes=tuple(a.qa_prefix), suppress_date=a.suppress_date)
    open(a.dest, "w", encoding="utf-8").write(out)
    print("%s -> %s: Q&A deleted=%d, colouring unwrapped=%d, date suppressed=%d"
          % (a.source, a.dest, n["qa"], n["unwrap"], n["date"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
