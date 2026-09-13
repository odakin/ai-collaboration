#!/usr/bin/env python3
"""Which wording does the literature use? Count INSPIRE-HEP records whose title or full text contains each exact phrase, and print the counts side by side with ratios to the first phrase; --selftest runs offline.

Why (2026-09-12/13): two naming questions on a manuscript were settled by the same manual loop of INSPIRE queries,
retyped each time. The counts are evidence for "which term is
standard", not for correctness; quote them with the date and the field (title vs full text).

Usage:
  inspire-phrase-frequency.py "dark matter halo" "dark-matter halo"
  inspire-phrase-frequency.py --plurals "Wilson loop" "Wilson line"   # also counts phrase + "s"
  inspire-phrase-frequency.py --fields ft --json "effective field theory" "effective theory"
  inspire-phrase-frequency.py --selftest

Fields: t = title, ft = full text (default both). Each count is one request (`size=1`, the total only),
with --sleep seconds between requests (default 0.3). Hyphens and spaces are sent as typed; do not assume that
punctuation variants (hyphen and en dash) are matched alike.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

API = "https://inspirehep.net/api/literature"
UA = {"User-Agent": "inspire-phrase-frequency/1.0 (terminology frequency for manuscript wording)"}


def build_query(field: str, phrase: str) -> str:
    return f'{field}:"{phrase}"'


def fetch_total(field: str, phrase: str, timeout: float = 60.0) -> int:
    url = f"{API}?q={urllib.parse.quote(build_query(field, phrase))}&size=1&fields=control_number"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return int(json.load(r)["hits"]["total"])


def expand(phrases: list[str], plurals: bool) -> list[str]:
    out: list[str] = []
    for p in phrases:
        out.append(p)
        if plurals and not p.endswith("s"):
            out.append(p + "s")
    return out


def count(phrases: list[str], fields: list[str], fetch=fetch_total, sleep: float = 0.3) -> dict:
    table: dict[str, dict[str, int]] = {}
    first = True
    for p in phrases:
        table[p] = {}
        for f in fields:
            if not first and sleep:
                time.sleep(sleep)
            first = False
            table[p][f] = fetch(f, p)
    return table


def render(table: dict, fields: list[str]) -> str:
    phrases = list(table)
    width = max(len(p) for p in phrases) + 2
    head = "phrase".ljust(width) + "".join(f"{f:>10}{'ratio':>9}" for f in fields)
    lines = [head, "-" * len(head)]
    base = {f: table[phrases[0]][f] for f in fields}
    for p in phrases:
        row = p.ljust(width)
        for f in fields:
            n = table[p][f]
            ratio = f"{n / base[f]:.3g}" if base[f] else "—"
            row += f"{n:>10}{ratio:>9}"
        lines.append(row)
    lines.append(f"(INSPIRE-HEP, {time.strftime('%Y-%m-%d')}; ratio = count / first phrase in the same field)")
    return "\n".join(lines)


def selftest() -> int:
    failed = []

    def expect(name, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            failed.append(name)

    expect("query quotes the phrase for exact matching", build_query("ft", "Wilson loop") == 'ft:"Wilson loop"')
    expect("--plurals appends s once, not to words already ending in s",
           expand(["Wilson loop", "fermion", "fields"], True) == ["Wilson loop", "Wilson loops", "fermion",
                                                                     "fermions", "fields"])
    fake = {("t", "A"): 10, ("ft", "A"): 200, ("t", "B"): 0, ("ft", "B"): 50}
    calls = []

    def fetch(f, p):
        calls.append((f, p))
        return fake[(f, p)]

    tab = count(["A", "B"], ["t", "ft"], fetch=fetch, sleep=0)
    expect("one request per phrase x field, in order", calls == [("t", "A"), ("ft", "A"), ("t", "B"), ("ft", "B")])
    out = render(tab, ["t", "ft"])
    expect("ratios are relative to the first phrase in the same field", "0.25" in out and "0" in out)
    zero = render({"Z": {"t": 0}, "Y": {"t": 3}}, ["t"])
    expect("a zero base count prints a dash instead of dividing by zero", "—" in zero)
    print("selftest:", "ALL PASS" if not failed else f"FAILED ({len(failed)})")
    return 0 if not failed else 1


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("phrases", nargs="+")
    ap.add_argument("--fields", default="t,ft", help="comma list of t (title) and ft (full text)")
    ap.add_argument("--plurals", action="store_true", help="also count each phrase with a trailing s")
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    fields = [f.strip() for f in a.fields.split(",") if f.strip()]
    bad = [f for f in fields if f not in ("t", "ft")]
    if bad:
        ap.error(f"unknown field(s): {bad}")
    table = count(expand(a.phrases, a.plurals), fields, sleep=a.sleep)
    print(json.dumps(table, ensure_ascii=False, indent=1) if a.json else render(table, fields))
    return 0


if __name__ == "__main__":
    sys.exit(main())
