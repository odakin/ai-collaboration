#!/usr/bin/env python3
"""2 版の LaTeX build を機械比較する組版 gate: log から error / 未定義参照 / overfull を折返し復元して数え、.aux の label→頁 写像の drift を出し (= 総頁数が同じでも中の頁割りは動く)、配布 PDF を自分の build が再現するかを pdftotext で証明する。--selftest 内蔵、規律 = conventions/edit-intent-record.md#build-gate

3 つの独立した機能。 どれも他版・他者の成果物を読む前に回す。

1. **log 比較** (`--before-log / --after-log`): error 数・未定義参照・未定義引用・多重定義・頁数・
   overfull/underfull を両版で出し、 **後版で新たに出たものだけ**を名指しする。 改稿で増えた組版警告と
   元から在ったものを混同しない。 ⚠️ TeX の log は 79 桁で折り返すので、 素の grep は
   `Overfull \hbox (N.NNpt too wide) in paragraph at lines A--B` を途中で切る。 本 script は
   折返しを復元してから数える (= 素の grep より多く見つかる)。

2. **label→頁 の drift** (`--before-aux / --after-aux`): `\newlabel` から label ごとの (番号, 頁) を
   取り、 版間で動いた label を出す。 **総頁数の一致は組版が動いていないことの証拠にならない** —
   記号幅の変わる一括置換では頁数が同じまま中の頁割りだけ動き、 図表・付録の位置が変わる。
   番号が動いた label は参照の意味が変わるので `[NUMBER]` として別に出す。

3. **build の再現証明** (`--reproduce given.pdf --built built.pdf`): 配布された PDF と自分の build の
   `pdftotext -layout` を比較し、 差分行数を出す。 **0 行を確かめてから**、 以後の観察 (頁の見た目・
   overfull・行かぶり) を source に帰属してよい。 0 行でないなら、 見ているものは相手の版ではなく
   自分の pipeline の産物かもしれない (engine 差の実例 = claude-config latex.md#latexmk-pdf-overrides-rc)。

使い方:

    python3 compare-tex-builds.py --before-log before/main.log --after-log after/main.log \
        --before-aux before/main.aux --after-aux after/main.aux
    python3 compare-tex-builds.py --reproduce distributed.pdf --built mybuild/main.pdf
    python3 compare-tex-builds.py --build-cmd 'pdflatex -interaction=nonstopmode main'   # 参考出力のみ

`--strict` で、 後版にだけ在る error / 未定義参照 / 多重定義があれば exit 1 (overfull は既定で
gate にしない = `edit-intent-record.md#overfull-not-a-gate`、 投稿直前の final pass で 1 回だけ掃除する)。
`--strict-overfull` を足すと overfull の新規発生も FAIL にする。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

WRAP = 79  # pdftex wraps log lines at this width


# ---------------------------------------------------------------- log


def unwrap(text: str) -> list[str]:
    """Rejoin pdftex's hard-wrapped log lines so that a long warning is one string again."""
    out: list[str] = []
    buf = ""
    for ln in text.split("\n"):
        buf += ln
        if len(ln) < WRAP:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def parse_log(text: str) -> dict:
    lines = unwrap(text)
    pages = re.findall(r"Output written on .*?\((\d+) pages?", text)
    return {
        "errors": [l for l in lines if l.startswith("!")],
        "undefined_refs": [l for l in lines if "Reference" in l and "undefined" in l],
        "undefined_cites": [l for l in lines if "Citation" in l and "undefined" in l],
        "multiply_defined": [l for l in lines if "multiply defined" in l or "multiply-defined" in l],
        "overfull": [l for l in lines if l.startswith("Overfull")],
        "underfull": [l for l in lines if l.startswith("Underfull")],
        "pages": int(pages[0]) if pages else None,
    }


def overfull_key(line: str) -> str:
    """Identity of an overfull box = its source line range (the amount drifts with wording)."""
    m = re.search(r"at lines (\d+)--(\d+)", line)
    return f"lines {m.group(1)}--{m.group(2)}" if m else line[:80]


# ---------------------------------------------------------------- aux


def parse_aux(text: str) -> dict[str, tuple[str, str]]:
    """{label: (number, page)} from \\newlabel; cleveref's `@cref` shadow entries are skipped."""
    out: dict[str, tuple[str, str]] = {}
    for m in re.finditer(r"\\newlabel\{([^}]*)\}\{\{([^{}]*)\}\{([^{}]*)\}", text):
        label = m.group(1)
        if label.endswith("@cref"):
            continue
        out[label] = (m.group(2), m.group(3))
    return out


def aux_drift(before: dict, after: dict) -> dict:
    moved_page, moved_number, added, removed = [], [], [], []
    for label, (num, page) in after.items():
        if label not in before:
            added.append(label)
            continue
        onum, opage = before[label]
        if onum != num:
            moved_number.append((label, onum, num))
        if opage != page:
            moved_page.append((label, opage, page))
    removed = [l for l in before if l not in after]
    return {"moved_page": moved_page, "moved_number": moved_number,
            "added": added, "removed": removed}


# ---------------------------------------------------------------- pdf


def pdf_text(pdf: Path) -> list[str]:
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext not found (poppler); cannot prove build reproduction")
    r = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                       capture_output=True, text=True, check=True)
    return r.stdout.split("\n")


def text_diff_count(a: list[str], b: list[str]) -> int:
    import difflib
    return sum(1 for d in difflib.unified_diff(a, b, lineterm="", n=0)
               if (d.startswith("-") or d.startswith("+"))
               and not d.startswith("---") and not d.startswith("+++"))


# ---------------------------------------------------------------- report


def report(bl: dict | None, al: dict | None, drift: dict | None,
           strict: bool, strict_overfull: bool) -> int:
    fail = 0
    if bl and al:
        print("| quantity | before | after |")
        print("|---|---|---|")
        for key, label in (("errors", "errors"), ("undefined_refs", "undefined references"),
                           ("undefined_cites", "undefined citations"),
                           ("multiply_defined", "multiply defined"),
                           ("overfull", "Overfull hbox"), ("underfull", "Underfull box")):
            print(f"| {label} | {len(bl[key])} | {len(al[key])} |")
        print(f"| pages | {bl['pages']} | {al['pages']} |")

        for key, label, gated in (("errors", "error", True),
                                  ("undefined_refs", "undefined reference", True),
                                  ("undefined_cites", "undefined citation", True),
                                  ("multiply_defined", "multiply-defined label", True),
                                  ("overfull", "Overfull hbox", strict_overfull),
                                  ("underfull", "Underfull box", False)):
            old = {overfull_key(x) if key == "overfull" else x for x in bl[key]}
            new = [x for x in al[key]
                   if (overfull_key(x) if key == "overfull" else x) not in old]
            if new:
                print(f"\n[NEW] {len(new)} {label}(s) present in after but not before:")
                for x in new:
                    print(f"   {x[:160]}")
                if strict and gated:
                    fail += len(new)

        if bl["pages"] != al["pages"]:
            print(f"\n[NEW] page count changed: {bl['pages']} -> {al['pages']}")

    if drift is not None:
        print(f"\n[info] labels: {len(drift['moved_page'])} moved page, "
              f"{len(drift['moved_number'])} changed number, "
              f"{len(drift['added'])} added, {len(drift['removed'])} removed")
        for label, o, n in drift["moved_number"]:
            print(f"[NUMBER] {label}: {o} -> {n}")
            if strict:
                fail += 1
        for label, o, n in drift["moved_page"]:
            print(f"[PAGE]   {label}: p{o} -> p{n}")
        for label in drift["removed"]:
            print(f"[GONE]   {label}")
            if strict:
                fail += 1
        if not drift["moved_page"] and not drift["moved_number"]:
            print("[info] pagination and numbering are identical "
                  "(page-count equality alone would not have shown this)")

    if fail:
        print(f"\nFAILED: {fail} gated regression(s)")
        return 1
    print("\nALL PASS" if (bl or drift) else "")
    return 0


# ---------------------------------------------------------------- selftest


def selftest() -> int:
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    # A wrapped Overfull warning: pdftex breaks it at 79 columns. The naive reader misses it.
    head = "Overfull \\hbox (3.14159pt too wide) in paragraph at lines 120--124"
    pad = "x" * (WRAP - len(head))          # forces the first physical line to be full width
    wrapped_log = (
        "This is pdfTeX\n"
        f"{head}{pad}\n"
        " []\n"
        "LaTeX Warning: Reference `eq:foo' on page 3 undefined on input line 12.\n"
        "! Undefined control sequence.\n"
        "Output written on main.pdf (12 pages, 600000 bytes).\n"
    )
    parsed = parse_log(wrapped_log)
    check("wrapped Overfull line is recovered by unwrapping  [foil for a naive grep]",
          len(parsed["overfull"]) == 1)
    check("the recovered line keeps its source range",
          overfull_key(parsed["overfull"][0]) == "lines 120--124")
    check("a naive line-by-line scan would also have seen this one (it starts the line)",
          any(l.startswith("Overfull") for l in wrapped_log.split("\n")))
    check("error count", len(parsed["errors"]) == 1)
    check("undefined reference count", len(parsed["undefined_refs"]) == 1)
    check("page count", parsed["pages"] == 12)
    check("clean log parses to zeros",
          parse_log("Output written on main.pdf (12 pages, 1 bytes).\n")["errors"] == [])

    # aux: same page count, different pagination — the case page-count equality misses
    before_aux = (r"\newlabel{eq:one}{{5}{2}{}{equation.5}{}}" "\n"
                  r"\newlabel{app:z}{{C}{9}{}{appendix.C}{}}" "\n"
                  r"\newlabel{eq:one@cref}{{[equation][5][]5}{[1][2][]2}}" "\n"
                  r"\newlabel{tab:x}{{1}{11}{}{table.1}{}}" "\n")
    after_aux = (r"\newlabel{eq:one}{{5}{2}{}{equation.5}{}}" "\n"
                 r"\newlabel{app:z}{{C}{8}{}{appendix.C}{}}" "\n"
                 r"\newlabel{tab:x}{{2}{10}{}{table.1}{}}" "\n")
    b, a = parse_aux(before_aux), parse_aux(after_aux)
    check("@cref shadow entries are skipped", "eq:one@cref" not in b and len(b) == 3)
    d = aux_drift(b, a)
    check("label that kept its page is not reported", "eq:one" not in [x[0] for x in d["moved_page"]])
    check("label that moved page is reported", ("app:z", "9", "8") in d["moved_page"])
    check("label whose number changed is reported separately",
          ("tab:x", "1", "2") in d["moved_number"])
    check("identical aux reports no drift",
          aux_drift(b, b)["moved_page"] == [] and aux_drift(b, b)["moved_number"] == [])
    check("removed label is reported", aux_drift(a | {"gone": ("1", "1")}, a)["removed"] == ["gone"])

    # text comparison
    check("identical text diffs to 0 lines", text_diff_count(["a", "b"], ["a", "b"]) == 0)
    check("one changed line diffs to 2 lines", text_diff_count(["a", "b"], ["a", "c"]) == 2)

    # strict gating: a new error fails, a new overfull does not (unless asked)
    clean = parse_log("Output written on main.pdf (12 pages, 1 bytes).\n")
    broke = parse_log("! Undefined control sequence.\n"
                      "Overfull \\hbox (1.0pt too wide) in paragraph at lines 1--2\n"
                      "Output written on main.pdf (12 pages, 1 bytes).\n")
    check("strict fails on a new error", report(clean, broke, None, True, False) == 1)
    only_of = parse_log("Overfull \\hbox (1.0pt too wide) in paragraph at lines 1--2\n"
                        "Output written on main.pdf (12 pages, 1 bytes).\n")
    check("strict does NOT fail on a new overfull by default",
          report(clean, only_of, None, True, False) == 0)
    check("--strict-overfull does fail on it", report(clean, only_of, None, True, True) == 1)

    print("\nALL PASS" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--before-log", type=Path)
    p.add_argument("--after-log", type=Path)
    p.add_argument("--before-aux", type=Path)
    p.add_argument("--after-aux", type=Path)
    p.add_argument("--reproduce", type=Path, help="PDF you were given")
    p.add_argument("--built", type=Path, help="PDF you built yourself")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--strict-overfull", action="store_true")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()

    if a.selftest:
        return selftest()

    if a.reproduce and a.built:
        n = text_diff_count(pdf_text(a.reproduce), pdf_text(a.built))
        print(f"[{'PASS' if n == 0 else 'FAIL'}] pdftotext differing lines: {n}")
        if n:
            print("   Your build does not reproduce the given PDF. Do not attribute visual "
                  "observations to the source until this is 0 (check engine, assets, revision).")
            return 1
        print("   Build reproduces the given PDF; later visual observations are attributable "
              "to the source.")
        return 0

    bl = parse_log(a.before_log.read_text(encoding="latin-1")) if a.before_log else None
    al = parse_log(a.after_log.read_text(encoding="latin-1")) if a.after_log else None
    drift = None
    if a.before_aux and a.after_aux:
        drift = aux_drift(parse_aux(a.before_aux.read_text(encoding="latin-1")),
                          parse_aux(a.after_aux.read_text(encoding="latin-1")))
    if not (bl or drift):
        p.error("give --before-log/--after-log, --before-aux/--after-aux, or --reproduce/--built")
    return report(bl, al, drift, a.strict, a.strict_overfull)


if __name__ == "__main__":
    sys.exit(main())
