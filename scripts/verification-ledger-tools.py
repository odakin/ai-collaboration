#!/usr/bin/env python3
"""Campaign ledger plumbing for parallel sub-workers: merge per-group item files into ledger.yaml in gated batches, and map an equation inventory onto ledger items (coverage table); --selftest.

Why (layer-1 hoist, measured in one campaign): when a primary worker splits a paper into groups and
background sub-workers write `notes/<group>-items.yaml` (no git), the primary must merge dozens of
entries into `ledger.yaml` under the commit-cadence gate (≤ N new `- id:` per commit).  Hand-written
merges broke twice: (1) a YAML dumper emitted a plain scalar followed by the document-end marker `...`,
which silently terminated the ledger document; (2) regex coverage missed sources written as
"(4.7a,b)".  This tool keeps the raw entry text (comments, folded strings, key order), inserts only
what the primary adds (`severity:`, a JSON-quoted `integration_note:`), refuses duplicates and
over-large batches, and re-parses the ledger after every write.

Usage:
    verification-ledger-tools.py merge <items.yaml> <ledger.yaml> <id>[:severity] ... [--notes notes.yaml] [--max 3]
    verification-ledger-tools.py coverage <campaign-dir> [--inventory notes/equation-inventory.json]
                                   [--extra B.2-B.9] [--fix eq=text ...] [--write]
    verification-ledger-tools.py --selftest

merge     appends the named entries (raw text) from a group file; `id:severity` inserts `severity:`
          after the entry's `status:` line; --notes maps id -> text written as `integration_note:`.
coverage  expands `(a)–(b)` ranges in inventory order, reads `(x.ya,b)` as x.ya and x.yb, and writes
          notes/coverage.md (eq → items with their status letter).  --extra adds numbers absent from
          the inventory (e.g. an appendix block the HTML collapsed); --fix overrides one row by hand.
Rules this implements: conventions/physics-verification-cycle.md#campaign-tooling (M).
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

ID_LINE = re.compile(r"^- id: (\S+)")
NUM = r"[0-9A-Z]+\.[0-9]+[a-z]?"


def split_entries(text: str) -> dict:
    blocks, cur = {}, None
    for line in text.splitlines(keepends=True):
        m = ID_LINE.match(line)
        if m:
            cur = m.group(1)
            if cur in blocks:
                raise ValueError(f"duplicate id in source: {cur}")
            blocks[cur] = []
        if cur is not None and not line.startswith("#"):
            blocks[cur].append(line)
    return blocks


def merge(src: Path, ledger: Path, specs: list, notes: dict, max_new: int) -> list:
    if len(specs) > max_new:
        raise ValueError(f"{len(specs)} entries requested, cadence limit is {max_new}")
    blocks = split_entries(src.read_text(encoding="utf-8"))
    existing = yaml.safe_load(ledger.read_text(encoding="utf-8")) if ledger.exists() else []
    have = {e["id"] for e in (existing or [])}
    out = []
    for spec in specs:
        iid, _, sev = spec.partition(":")
        if iid not in blocks:
            raise KeyError(f"{iid} not in {src}")
        if iid in have:
            raise ValueError(f"{iid} already in ledger")
        new = []
        for line in blocks[iid]:
            new.append(line)
            if sev and re.match(r"^  status: ", line):
                new.append(f"  severity: {sev}\n")
        if new and not new[-1].endswith("\n"):
            new[-1] += "\n"
        if iid in notes:
            new.append(f"  integration_note: {json.dumps(notes[iid], ensure_ascii=False)}\n")
        out.extend(new)
    before = ledger.read_text(encoding="utf-8") if ledger.exists() else ""
    if before and not before.endswith("\n"):
        before += "\n"
    candidate = before + "".join(out)
    parsed = yaml.safe_load(candidate)
    ids = [e["id"] for e in parsed]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate ids after merge")
    ledger.write_text(candidate, encoding="utf-8")
    return ids[-len(specs):]


def expand_numbers(text: str, order: dict, full: list) -> set:
    nums = set()
    for m in re.finditer(rf"\(({NUM})\)\s*[-–—]+\s*\(({NUM})\)", text):
        a, b = m.group(1), m.group(2)
        if a in order and b in order and order[a] <= order[b]:
            nums.update(full[order[a]:order[b] + 1])
        else:
            nums.update([a, b])
    for m in re.finditer(r"\(([0-9A-Z]+\.[0-9]+)([a-z])?(?:,\s*([a-z]))?\)", text):
        base, s1, s2 = m.group(1), m.group(2), m.group(3)
        if s1:
            nums.add(base + s1)
            if s2:
                nums.add(base + s2)
        else:
            nums.add(base)
    return nums


def coverage(camp: Path, inventory: Path, extra: list, fixes: dict) -> tuple:
    inv = [e["number"].strip("()") for e in json.loads(inventory.read_text(encoding="utf-8"))]
    full = list(inv) + [x for x in extra if x not in inv]
    order = {n: i for i, n in enumerate(full)}
    ledger = yaml.safe_load((camp / "ledger.yaml").read_text(encoding="utf-8"))
    status = {e["id"]: str(e.get("status", "?")) for e in ledger}
    cov = {n: [] for n in full}
    for e in ledger:
        for n in expand_numbers(str(e.get("source", "")), order, full):
            keys = [n] if n in cov else [k for k in cov if re.fullmatch(re.escape(n) + "[a-z]", k)]
            for k in keys:
                if e["id"] not in cov[k]:
                    cov[k].append(e["id"])
    rows = []
    for n in full:
        if n in fixes:
            rows.append((n, fixes[n]))
        elif cov[n]:
            rows.append((n, ", ".join(f"{i} [{status[i][0]}]" for i in cov[n])))
        else:
            rows.append((n, None))
    unmapped = [n for n, t in rows if t is None]
    return rows, unmapped


def render_coverage(rows: list) -> str:
    out = ["# Coverage: numbered equations → ledger items", "",
           "Generated by verification-ledger-tools.py coverage from each entry's `source`; [v]/[r]/[u] = item status.",
           "An item listed here references the equation; it is not necessarily the item that decides it.", ""]
    cur = None
    for n, t in rows:
        sec = n.split(".")[0]
        if sec != cur:
            out += ["", f"## {sec}", "", "| eq | items |", "|---|---|"]
            cur = sec
        out.append(f"| ({n}) | {t if t is not None else '— (unmapped)'} |")
    return "\n".join(out) + "\n"


def parse_extra(spec: str) -> list:
    out = []
    for part in filter(None, spec.split(",")):
        m = re.fullmatch(r"([0-9A-Z]+)\.(\d+)-\1\.(\d+)", part.strip())
        if m:
            out += [f"{m.group(1)}.{i}" for i in range(int(m.group(2)), int(m.group(3)) + 1)]
        else:
            out.append(part.strip())
    return out


def selftest() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / "G-items.yaml").write_text(
            "# group file\n- id: G-01\n  source: \"eqs (1.1)-(1.3)\"\n  status: refuted\n  note: >-\n    folded\n    text\n"
            "- id: G-02\n  source: \"eq (1.4a,b)\"\n  status: verified\n", encoding="utf-8")
        led = d / "ledger.yaml"
        led.write_text("- id: W-01\n  source: \"(A.1)\"\n  status: unverified\n", encoding="utf-8")
        ids = merge(d / "G-items.yaml", led, ["G-01:typo", "G-02"], {"G-01": "text with: colon and ... dots"}, 3)
        assert ids == ["G-01", "G-02"], ids
        parsed = yaml.safe_load(led.read_text(encoding="utf-8"))
        g1 = [e for e in parsed if e["id"] == "G-01"][0]
        assert g1["severity"] == "typo" and g1["note"] == "folded text" and g1["integration_note"].endswith("... dots")
        for bad in (lambda: merge(d / "G-items.yaml", led, ["G-01"], {}, 3),            # duplicate
                    lambda: merge(d / "G-items.yaml", led, ["G-01", "G-02", "X", "Y"], {}, 3)):  # over cap
            try:
                bad()
                raise AssertionError("merge accepted a bad request")
            except (ValueError, KeyError):
                pass
        camp = d / "c"
        (camp / "notes").mkdir(parents=True)
        led.replace(camp / "ledger.yaml")
        inv = [{"number": f"({n})"} for n in ("1.1", "1.2", "1.3", "1.4a", "1.4b", "1.5", "A.1")]
        (camp / "notes" / "inv.json").write_text(json.dumps(inv), encoding="utf-8")
        rows, unmapped = coverage(camp, camp / "notes" / "inv.json", parse_extra("A.2-A.3"), {"A.3": "manual"})
        table = dict(rows)
        assert table["1.2"].startswith("G-01 [r]") and table["1.4b"].startswith("G-02 [v]")
        assert unmapped == ["1.5", "A.2"], unmapped
        assert table["A.3"] == "manual" and "(unmapped)" in render_coverage(rows)
    print("verification-ledger-tools selftest: PASS")


def main(argv: list) -> int:
    if "--selftest" in argv:
        selftest()
        return 0
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("items")
    m.add_argument("ledger")
    m.add_argument("ids", nargs="+")
    m.add_argument("--notes")
    m.add_argument("--max", type=int, default=3)
    c = sub.add_parser("coverage")
    c.add_argument("campaign")
    c.add_argument("--inventory", default="notes/equation-inventory.json")
    c.add_argument("--extra", default="")
    c.add_argument("--fix", nargs="*", default=[])
    c.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "merge":
        notes = yaml.safe_load(Path(a.notes).read_text(encoding="utf-8")) if a.notes else {}
        print("merged:", merge(Path(a.items), Path(a.ledger), a.ids, notes or {}, a.max))
        return 0
    camp = Path(a.campaign)
    fixes = dict(f.split("=", 1) for f in a.fix)
    rows, unmapped = coverage(camp, camp / a.inventory, parse_extra(a.extra), fixes)
    print(f"equations: {len(rows)}; unmapped: {unmapped}")
    if a.write:
        (camp / "notes" / "coverage.md").write_text(render_coverage(rows), encoding="utf-8")
        print("wrote", camp / "notes" / "coverage.md")
    return 1 if unmapped else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
