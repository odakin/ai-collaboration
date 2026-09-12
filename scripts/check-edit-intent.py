#!/usr/bin/env python3
"""AI 原稿改稿の意図記録 (edit-intent sidecar) の骨組み生成 + 機械検査: hunk 被覆 / 位置 / 種類 / ID 実在 / 裁量枠 / 削除 verbatim を PASS/FAIL + exit code で。 --selftest 内蔵。 正本 = conventions/edit-intent-record.md

Why (2026-09-08): an AI implementation pass rewrote a manuscript in 89 hunks / 474 lines
from 15 referee findings and an author decision ledger, and nothing recorded which hunk
implemented which decision.  A week later the author's session re-derived that map by hand
and found three edits that exceeded the decisions (a deletion the ledger forbade, an 85-line
removal where the ledger said "compress", three rewrites where it said "one sentence").
Nothing was physically wrong; what was missing was traceability.  This script makes the
record cheap to produce (scaffold from the diff) and cheap to trust (check before commit).

Usage:

    # 1. scaffold the sidecar from the diff (hunk rows + positions + verbatim of net deletions)
    python3 check-edit-intent.py --scaffold --root <manuscript repo> --repo external/overleaf \\
        --file paper.tex --base <commit> --head <commit> --implementer codex \\
        --ledger review/author-decisions.md --ledger review/referee-report-and-revision-plan.md \\
        --out review/edit-intent-2026-09-01.md
    # 2. check a filled sidecar ([PASS]/[FAIL] lines, ALL PASS / FAILED, exit 0/1; --json available)
    python3 check-edit-intent.py review/edit-intent-2026-09-01.md [--root DIR] [--json]
    # 3. selftest on a synthetic git repo (one passing sidecar + foils that must FAIL)
    python3 check-edit-intent.py --selftest

Sidecar format (see the convention for the full example): frontmatter with
`repo` / `file` / `base` / `head` / `ledgers` (+ `date`, `implementer`), a table under
`## 対応表` with columns `hunk | 位置 | 種類 | ID | 意図`, a `## 裁量` section that lists every
discretionary hunk as `hunk N: ...` (or says なし), and a `## 削除` section with one
`### hunk N` fenced block per net-deletion hunk holding the removed lines verbatim.

Checks (any FAIL → exit 1):
  frontmatter keys + base/head resolve · hunk coverage 1..N exactly once · 位置 matches the
  recomputed diff · 種類 vocabulary (exactly one of 実装/裁量, optional 削除) · every ID token
  exists literally in a ledger · every 裁量 row is listed in ## 裁量 (section mandatory) ·
  net-deletion hunks carry 削除 and their removed lines are present verbatim · 意図 non-empty.
Not checked (human floor): whether the decision actually permits the edit, whether a
quantity instruction (compress / one sentence) was respected (large net deletions with an
ID get an INFO line), the merit of the discretion.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KINDS_PRIMARY = ("実装", "裁量")
KIND_DELETE = "削除"
KINDS_ALL = KINDS_PRIMARY + (KIND_DELETE,)
REQUIRED_KEYS = ("repo", "file", "base", "head", "ledgers")
LARGE_DELETION = 10  # net removed lines at/above which an INFO reminder about quantity instructions is printed
ID_SPLIT = re.compile(r"[,，;/\s]+")
ID_NONE = {"", "—", "-", "–", "なし", "n/a", "N/A"}
HUNK_REF = re.compile(r"hunk\s*(\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*)", re.IGNORECASE)
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
POS_RE = re.compile(r"-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?")


# ---------------------------------------------------------------- git / diff

def _git(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return proc.returncode, proc.stdout


@dataclass
class Hunk:
    index: int              # 1-based, order of appearance in `git diff -U0`
    header: str             # canonical "-a,b +c,d"
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)

    @property
    def net_deletion(self) -> bool:
        return len(self.removed) > len(self.added)


def _split_cells_raw(s: str) -> list[str]:
    """Split a markdown table line on unescaped ``|`` (``\\|`` stays inside a cell)."""
    return re.split(r"(?<!\\)\|", s)


def _escape_cell(v: str) -> str:
    """Escape a ``|`` so it can live inside a table cell (both readers split on unescaped ``|``)."""
    return re.sub(r"(?<!\\)\|", r"\\|", v)


def canonical_pos(text: str) -> str | None:
    m = POS_RE.search(text or "")
    if not m:
        return None
    a, b, c, d = m.group(1), m.group(2) or "1", m.group(3), m.group(4) or "1"
    return f"-{a},{b} +{c},{d}"


def hunks_from_diff(diff_text: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    current: Hunk | None = None
    for line in diff_text.splitlines():
        m = HUNK_HEADER.match(line)
        if m:
            a, b, c, d = m.group(1), m.group(2) or "1", m.group(3), m.group(4) or "1"
            current = Hunk(index=len(hunks) + 1, header=f"-{a},{b} +{c},{d}")
            hunks.append(current)
            continue
        if current is None:
            continue  # file header lines (diff --git / --- / +++)
        if line.startswith("-"):
            current.removed.append(line[1:].rstrip("\r"))
        elif line.startswith("+"):
            current.added.append(line[1:].rstrip("\r"))
        # "\ No newline at end of file" and anything else: ignored
    return hunks


def compute_diff(git_dir: Path, base: str, head: str, file: str) -> tuple[int, str]:
    return _git(git_dir, "diff", "-U0", "--no-color", "--no-ext-diff", "--diff-algorithm=myers", base, head, "--", file)


def commit_exists(git_dir: Path, ref: str) -> bool:
    rc, _ = _git(git_dir, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return rc == 0


# ---------------------------------------------------------------- sidecar parsing

def parse_frontmatter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing frontmatter (first line must be ---)")
    meta: dict[str, Any] = {}
    key_for_list: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return meta
        stripped = line.split(" #", 1)[0].rstrip()
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            continue
        if stripped.lstrip().startswith("- ") and key_for_list:
            meta.setdefault(key_for_list, []).append(stripped.lstrip()[2:].strip().strip("'\""))
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            key_for_list = None
        elif value == "":
            meta[key] = []
            key_for_list = key
        else:
            meta[key] = value.strip("'\"")
            key_for_list = None
    raise ValueError("unterminated frontmatter")


def expand_hunks(spec: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"\s*,\s*", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if hi < lo:
                raise ValueError(f"bad hunk range {part!r}")
            out.extend(range(lo, hi + 1))
        elif re.fullmatch(r"\d+", part):
            out.append(int(part))
        else:
            raise ValueError(f"bad hunk spec {part!r}")
    return out


def _sections(body: str) -> list[tuple[str, list[str]]]:
    """Split on `## ` headings → [(heading text, lines)]. Text before the first heading gets heading ''."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in body.splitlines():
        m = re.match(r"^##\s+(.*?)\s*$", line)
        if m and not line.startswith("###"):
            sections.append((m.group(1), []))
        else:
            sections[-1][1].append(line)
    return sections


def _strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:])
    return text


@dataclass
class Row:
    line_no: int
    hunks: list[int]
    pos: str
    kinds: list[str]
    ids: list[str]
    intent: str
    raw_hunk: str
    raw_kind: str


@dataclass
class Sidecar:
    meta: dict[str, Any]
    rows: list[Row]
    table_errors: list[str]
    discretion_text: str | None       # None = section missing
    discretion_hunks: set[int]
    deletion_present: bool
    deletion_blocks: dict[int, list[str]]  # hunk index -> verbatim lines


def _parse_table(lines: list[str]) -> tuple[list[Row], list[str]]:
    rows: list[Row] = []
    errors: list[str] = []
    header: list[str] | None = None
    col: dict[str, int] = {}
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            if header is not None and line.strip() == "":
                break
            continue
        cells = [c.strip().replace("\\|", "|") for c in _split_cells_raw(line.strip().strip("|"))]
        if header is None:
            header = [c.lower() for c in cells]
            for name, keys in (("hunk", ("hunk",)), ("pos", ("位置",)), ("kind", ("種類",)), ("id", ("id",)), ("intent", ("意図",))):
                for k in keys:
                    if k in header:
                        col[name] = header.index(k)
            for need in ("hunk", "kind", "id", "intent"):
                if need not in col:
                    errors.append(f"table header lacks column {need!r} (got {header})")
            if errors:
                return rows, errors
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) and any(cells):
            continue  # separator row
        if len(cells) <= max(col.values()):
            errors.append(f"line {i + 1}: row has {len(cells)} cells, expected ≥ {max(col.values()) + 1}")
            continue
        raw_hunk = cells[col["hunk"]]
        try:
            hunks = expand_hunks(raw_hunk)
        except ValueError as exc:
            errors.append(f"line {i + 1}: {exc}")
            continue
        raw_kind = cells[col["kind"]]
        kinds = [k for k in re.split(r"[+＋/,\s]+", raw_kind) if k]
        ids = [t for t in ID_SPLIT.split(cells[col["id"]]) if t not in ID_NONE]
        rows.append(Row(
            line_no=i + 1, hunks=hunks, pos=cells[col["pos"]] if "pos" in col else "",
            kinds=kinds, ids=ids, intent=cells[col["intent"]].strip(), raw_hunk=raw_hunk, raw_kind=raw_kind,
        ))
    if header is None:
        errors.append("no table found under 対応表")
    return rows, errors


def _parse_deletion_blocks(lines: list[str]) -> dict[int, list[str]]:
    blocks: dict[int, list[str]] = {}
    i = 0
    while i < len(lines):
        m = re.match(r"^###\s*hunk\s+(.+?)\s*$", lines[i], re.IGNORECASE)
        if not m:
            i += 1
            continue
        try:
            targets = expand_hunks(m.group(1))
        except ValueError:
            targets = []
        j = i + 1
        while j < len(lines) and not re.match(r"^\s*`{3,}", lines[j]) and not lines[j].startswith("### "):
            j += 1
        if j >= len(lines) or lines[j].startswith("### "):
            i = j
            continue
        fence = re.match(r"^\s*(`{3,})", lines[j]).group(1)
        k = j + 1
        content: list[str] = []
        while k < len(lines) and not (lines[k].strip().startswith(fence) and set(lines[k].strip()) == {"`"}):
            content.append(lines[k].rstrip("\r"))
            k += 1
        for t in targets:
            blocks.setdefault(t, []).extend(content)
        i = k + 1
    return blocks


def parse_sidecar(text: str) -> Sidecar:
    meta = parse_frontmatter(text)
    body = _strip_frontmatter(text)
    sections = _sections(body)
    table_lines: list[str] | None = None
    discretion: list[str] | None = None
    deletion: list[str] | None = None
    for heading, lines in sections:
        if "対応表" in heading and table_lines is None:
            table_lines = lines
        elif "裁量" in heading and discretion is None:
            discretion = lines
        elif "削除" in heading and deletion is None:
            deletion = lines
    if table_lines is None:  # fallback: first table anywhere whose header mentions hunk
        for _, lines in sections:
            if any(l.strip().startswith("|") and "hunk" in l.lower() for l in lines):
                table_lines = lines
                break
    rows, errors = _parse_table(table_lines or [])
    discretion_text = None
    discretion_hunks: set[int] = set()
    if discretion is not None:
        stripped = [l for l in discretion if l.strip() and not l.strip().startswith("<!--")]
        discretion_text = "\n".join(stripped)
        for m in HUNK_REF.finditer(discretion_text):
            try:
                discretion_hunks.update(expand_hunks(m.group(1)))
            except ValueError:
                pass
    return Sidecar(
        meta=meta, rows=rows, table_errors=errors, discretion_text=discretion_text,
        discretion_hunks=discretion_hunks, deletion_present=deletion is not None,
        deletion_blocks=_parse_deletion_blocks(deletion or []),
    )


# ---------------------------------------------------------------- check

def _id_in_ledgers(token: str, ledgers: dict[str, str]) -> bool:
    pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])")
    return any(pat.search(text) for text in ledgers.values())


def resolve_root(sidecar_path: Path, root_arg: str | None) -> Path:
    if root_arg:
        return Path(root_arg).expanduser().resolve()
    rc, out = _git(sidecar_path.parent, "rev-parse", "--show-toplevel")
    if rc == 0 and out.strip():
        return Path(out.strip())
    return sidecar_path.parent.resolve()


def check(sidecar_path: Path, root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    infos: list[str] = []

    def record(name: str, passed: bool, detail: str) -> None:
        results.append({"name": name, "passed": bool(passed), "detail": detail})

    try:
        text = sidecar_path.read_text(encoding="utf-8")
        sc = parse_sidecar(text)
    except (OSError, ValueError) as exc:
        record("sidecar parse", False, str(exc))
        return results, infos

    missing = [k for k in REQUIRED_KEYS if not sc.meta.get(k)]
    record("frontmatter", not missing, "missing: " + ", ".join(missing) if missing else
           f"repo={sc.meta.get('repo')} file={sc.meta.get('file')} base={sc.meta.get('base')} head={sc.meta.get('head')}")
    if missing:
        return results, infos

    repo_val = str(sc.meta["repo"])
    git_dir = Path(repo_val).expanduser() if os.path.isabs(os.path.expanduser(repo_val)) else (root / repo_val)
    git_dir = git_dir.resolve()
    base, head, file = str(sc.meta["base"]), str(sc.meta["head"]), str(sc.meta["file"])
    if not git_dir.exists():
        record("git dir", False, f"not found: {git_dir}")
        return results, infos
    bad = [r for r in (base, head) if not commit_exists(git_dir, r)]
    record("commits resolve", not bad, ("not found in " + str(git_dir) + ": " + ", ".join(bad) + " (fetch the manuscript clone?)") if bad else f"{base} and {head} in {git_dir}")
    if bad:
        return results, infos

    rc, diff_text = compute_diff(git_dir, base, head, file)
    hunks = hunks_from_diff(diff_text) if rc == 0 else []
    record("diff", rc == 0 and bool(hunks), f"{len(hunks)} hunks ({base}..{head} {file})" if hunks else f"git diff rc={rc}, 0 hunks")
    if not hunks:
        return results, infos
    by_index = {h.index: h for h in hunks}

    ledgers: dict[str, str] = {}
    missing_ledgers: list[str] = []
    for rel in sc.meta["ledgers"] if isinstance(sc.meta["ledgers"], list) else [sc.meta["ledgers"]]:
        p = Path(rel).expanduser() if os.path.isabs(os.path.expanduser(str(rel))) else root / str(rel)
        if p.exists():
            ledgers[str(rel)] = p.read_text(encoding="utf-8", errors="replace")
        else:
            missing_ledgers.append(str(rel))
    record("ledgers", bool(ledgers) and not missing_ledgers, ("missing: " + ", ".join(missing_ledgers)) if missing_ledgers else ", ".join(ledgers))

    record("table", not sc.table_errors and bool(sc.rows), "; ".join(sc.table_errors) if sc.table_errors else f"{len(sc.rows)} rows")
    if sc.table_errors or not sc.rows:
        return results, infos

    # hunk coverage
    seen = Counter(n for r in sc.rows for n in r.hunks)
    unknown = sorted(n for n in seen if n not in by_index)
    dup = sorted(n for n, c in seen.items() if c > 1)
    absent = sorted(n for n in by_index if n not in seen)
    problems = []
    if unknown:
        problems.append("unknown " + ",".join(map(str, unknown)))
    if dup:
        problems.append("duplicate " + ",".join(map(str, dup)))
    if absent:
        problems.append("missing " + ",".join(map(str, absent)))
    record("hunk coverage", not problems, "; ".join(problems) if problems else f"1..{len(hunks)} covered exactly once")

    # 位置
    pos_bad: list[str] = []
    for r in sc.rows:
        if not r.pos.strip():
            continue
        parts = [canonical_pos(p) for p in re.split(r"\s*;\s*", r.pos) if p.strip()]
        valid = [n for n in r.hunks if n in by_index]
        if len(parts) == 1:
            if valid and parts[0] != by_index[valid[0]].header:
                pos_bad.append(f"row L{r.line_no} hunk {r.raw_hunk}: {r.pos!r} ≠ {by_index[valid[0]].header!r}")
        elif len(parts) != len(valid) or any(p != by_index[n].header for p, n in zip(parts, valid)):
            pos_bad.append(f"row L{r.line_no} hunk {r.raw_hunk}: {r.pos!r} ≠ {[by_index[n].header for n in valid]}")
    record("位置", not pos_bad, "; ".join(pos_bad[:5]) if pos_bad else "all positions match the recomputed diff")

    # 種類
    kind_bad: list[str] = []
    for r in sc.rows:
        bad_tokens = [k for k in r.kinds if k not in KINDS_ALL]
        primary = [k for k in r.kinds if k in KINDS_PRIMARY]
        if bad_tokens:
            kind_bad.append(f"row L{r.line_no} hunk {r.raw_hunk}: unknown 種類 {bad_tokens}")
        elif len(primary) != 1:
            kind_bad.append(f"row L{r.line_no} hunk {r.raw_hunk}: 種類 must contain exactly one of 実装/裁量 (got {r.raw_kind!r})")
    record("種類", not kind_bad, "; ".join(kind_bad[:5]) if kind_bad else "vocabulary OK")

    # ID
    id_bad: list[str] = []
    for r in sc.rows:
        if "実装" in r.kinds and not r.ids:
            id_bad.append(f"row L{r.line_no} hunk {r.raw_hunk}: 実装 without ID")
        for t in r.ids:
            if ledgers and not _id_in_ledgers(t, ledgers):
                id_bad.append(f"row L{r.line_no} hunk {r.raw_hunk}: ID {t!r} not in any ledger")
    record("ID 実在", not id_bad, "; ".join(id_bad[:5]) if id_bad else "every ID token found in a ledger")

    # 裁量
    disc_rows = [r for r in sc.rows if "裁量" in r.kinds]
    if sc.discretion_text is None:
        record("裁量枠", False, "section ## 裁量 missing (write なし if there is none)")
    elif not sc.discretion_text.strip():
        record("裁量枠", False, "section ## 裁量 is empty (write なし if there is none)")
    else:
        unlisted = sorted({n for r in disc_rows for n in r.hunks} - sc.discretion_hunks)
        none_only = re.fullmatch(r"[-*\s]*なし[。.\s]*", sc.discretion_text.strip()) is not None
        if disc_rows and none_only:
            record("裁量枠", False, f"{len(disc_rows)} 裁量 row(s) but ## 裁量 says なし")
        elif unlisted:
            record("裁量枠", False, "裁量 hunk not listed in ## 裁量: " + ",".join(map(str, unlisted)))
        else:
            record("裁量枠", True, f"{len(disc_rows)} 裁量 row(s), all listed" if disc_rows else "no 裁量 rows, section says " + sc.discretion_text.strip()[:20])

    # 削除
    del_bad: list[str] = []
    for r in sc.rows:
        valid = [n for n in r.hunks if n in by_index]
        net = [n for n in valid if by_index[n].net_deletion]
        flagged = KIND_DELETE in r.kinds
        if net and not flagged:
            del_bad.append(f"row L{r.line_no} hunk {r.raw_hunk}: net deletion (hunk {','.join(map(str, net))}) without 種類 削除")
        if flagged and not any(by_index[n].removed for n in valid):
            del_bad.append(f"row L{r.line_no} hunk {r.raw_hunk}: 削除 flagged but no line is removed")
        if flagged:
            for n in valid:
                h = by_index[n]
                if not h.removed:
                    continue
                block = sc.deletion_blocks.get(n)
                if block is None:
                    del_bad.append(f"hunk {n}: no `### hunk {n}` verbatim block under ## 削除")
                    continue
                need = Counter(l.rstrip() for l in h.removed)
                have = Counter(l.rstrip() for l in block)
                lost = [l for l, c in need.items() if have[l] < c]
                if lost:
                    del_bad.append(f"hunk {n}: {len(lost)} removed line(s) not verbatim in block, e.g. {lost[0][:60]!r}")
    if not sc.deletion_present and any(h.net_deletion for h in hunks):
        del_bad.append("section ## 削除 missing while the diff has net-deletion hunks")
    record("削除 verbatim", not del_bad, "; ".join(del_bad[:5]) if del_bad else "every net deletion flagged and present verbatim")

    # 意図
    empty = [f"L{r.line_no} hunk {r.raw_hunk}" for r in sc.rows if r.intent in ID_NONE]
    record("意図", not empty, "empty 意図: " + ", ".join(empty[:5]) if empty else "all rows have an intent")

    # INFO: quantity reminder
    for r in sc.rows:
        for n in r.hunks:
            h = by_index.get(n)
            if h and r.ids and len(h.removed) - len(h.added) >= LARGE_DELETION:
                infos.append(f"量の指示を確認: hunk {n} (-{len(h.removed)}/+{len(h.added)}, {' '.join(r.ids)}) — 決定が「圧縮」「1 文のみ」 等の量を含むなら守れているか (規則 5)")
    return results, infos


# ---------------------------------------------------------------- scaffold

def scaffold(root: Path, repo: str, file: str, base: str, head: str, ledgers: list[str], implementer: str, date: str) -> str:
    git_dir = (Path(repo).expanduser() if os.path.isabs(os.path.expanduser(repo)) else root / repo).resolve()
    for ref in (base, head):
        if not commit_exists(git_dir, ref):
            raise SystemExit(f"✗ commit {ref} not found in {git_dir}")
    rc, diff_text = compute_diff(git_dir, base, head, file)
    hunks = hunks_from_diff(diff_text) if rc == 0 else []
    if not hunks:
        raise SystemExit(f"✗ no hunks in {base}..{head} -- {file} (rc={rc})")
    out: list[str] = ["---", "sidecar: edit-intent", f"date: {date}", f"implementer: {implementer}",
                      f"repo: {repo}", f"file: {file}", f"base: {base}", f"head: {head}", "ledgers:"]
    out += [f"  - {l}" for l in ledgers]
    out += ["---", f"# Edit intent {date} ({file}, {base} → {head})", "",
            "<!-- 種類 = 実装 / 裁量 (+削除)、 ID = ledger に在る token (実装は必須)、 意図 = 1 行。 hunk と 位置 は機械生成、 触らない -->",
            "", "## 対応表", "", "| hunk | 位置 | 種類 | ID | 意図 |", "|---|---|---|---|---|"]
    for h in hunks:
        out.append(f"| {h.index} | {h.header} | {KINDS_PRIMARY[0] + '+' + KIND_DELETE if h.net_deletion else ''} |  |  |")  # net deletion: prefill 実装+削除 (change to 裁量+削除 if discretionary)
    out += ["", "## 裁量", "", "<!-- 決定 ledger に無い変更を `hunk N: 何を・なぜ` で 1 行ずつ。 無ければ「なし」 -->", "", "## 削除", ""]
    dels = [h for h in hunks if h.net_deletion]
    if not dels:
        out.append("なし (net 削除の hunk は無い)")
    for h in dels:
        fence = "````" if any(l.lstrip().startswith("```") for l in h.removed) else "```"
        out += [f"### hunk {h.index}", f"{fence}latex"] + h.removed + [fence, ""]
    return "\n".join(out).rstrip() + "\n"



# ---------------------------------------------------------------- fill

def fill_sidecar(text: str, intents: dict[str, dict[str, str]], discretion: str | None = None) -> str:
    """Fill the empty 種類 / ID / 意図 cells of a scaffolded sidecar (2026-09-11).

    Keys of `intents` are a hunk number ("3") or an old start line ("L1064"); values are
    {"kind": ..., "id": ..., "intent": ...}. A prefilled kind (実装+削除 on a net deletion) is kept
    unless the entry gives one; a missing kind defaults to 実装. Rows already carrying an ID or an
    intent are left alone. Raises ValueError when an empty row has no entry, when an entry matches
    no row. A "|" inside a value is escaped for the table (the readers split on unescaped "|"). The ## 裁量 placeholder gets `discretion` (default なし).
    """
    used: set[str] = set()
    out: list[str] = []
    for line in text.split("\n"):
        parts = _split_cells_raw(line)
        if len(parts) == 7 and parts[1].strip().isdigit() and re.match(r"\s*-\d+", parts[2]):
            n, pos = parts[1].strip(), parts[2].strip()
            kind, id_, intent = parts[3].strip(), parts[4].strip(), parts[5].strip()
            if not id_ and not intent:
                key = n if n in intents else ("L" + re.match(r"-(\d+)", pos).group(1))
                if key not in intents:
                    raise ValueError(f"no entry for hunk {n} ({pos}); give \"{n}\" or \"{key}\"")
                e = intents[key]
                used.add(key)
                kind = e.get("kind") or kind or KINDS_PRIMARY[0]
                id_, intent = e.get("id", ""), e.get("intent", "")
                kind, id_, intent = (_escape_cell(v) for v in (kind, id_, intent))
                line = f"| {n} | {pos} | {kind} | {id_} | {intent} |"
        out.append(line)
    unused = sorted(set(intents) - used)
    if unused:
        raise ValueError("entries match no empty row: " + ", ".join(unused))
    res = "\n".join(out)
    m = re.search(r"(## 裁量\n\n<!--[^\n]*-->\n)(\n## )", res)
    if m:
        res = res[:m.end(1)] + "\n" + (discretion or "なし") + "\n" + res[m.end(1):]
    return res

# ---------------------------------------------------------------- selftest

def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True)


def selftest() -> int:
    if shutil.which("git") is None:
        print("SKIP: git not available")
        return 0
    checks = 0

    def expect(cond: bool, what: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            print(f"selftest FAIL: {what}")
            raise SystemExit(1)

    # parser units
    expect(canonical_pos("-12 +12") == "-12,1 +12,1", "canonical_pos default count")
    expect(canonical_pos("@@ -610,85 +613,6 @@") == "-610,85 +613,6", "canonical_pos full")
    expect(expand_hunks("2-4, 7") == [2, 3, 4, 7], "expand_hunks")
    fm = parse_frontmatter("---\nrepo: .\nledgers:\n  - a.md\n  - b.md\nx: [p, q]\n---\nbody")
    expect(fm["ledgers"] == ["a.md", "b.md"] and fm["x"] == ["p", "q"] and fm["repo"] == ".", "frontmatter lists")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _run(["git", "init", "-q"], root)
        _run(["git", "config", "user.email", "selftest@example.invalid"], root)
        _run(["git", "config", "user.name", "selftest"], root)
        lines = [f"line {i}" for i in range(1, 31)]
        (root / "paper.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
        _run(["git", "add", "paper.tex"], root)
        _run(["git", "commit", "-q", "-m", "base"], root)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
        new = list(lines)
        new[2] = "line 3 modified"                                   # hunk 1: 1→1
        del new[9:14]                                                # hunk 2: 5→0 (net deletion)
        new.insert(20 - 5, "inserted A"); new.insert(21 - 5, "inserted B")  # hunk 3: 0→2
        # hunk 4: 2→1 (net deletion) near the end
        idx = new.index("line 25")
        new[idx:idx + 2] = ["line 25+26 merged"]
        (root / "paper.tex").write_text("\n".join(new) + "\n", encoding="utf-8")
        _run(["git", "commit", "-q", "-am", "head"], root)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
        (root / "review").mkdir()
        (root / "review" / "decisions.md").write_text("# decisions\n\n| ID | disposition |\n|---|---|\n| F01 | accept |\n| R02 | compress |\n\nMY-2 resolved.\n", encoding="utf-8")

        text = scaffold(root, ".", "paper.tex", base[:7], head[:7], ["review/decisions.md"], "selftest", "2026-01-01")
        hk = hunks_from_diff(compute_diff(root, base, head, "paper.tex")[1])
        expect(len(hk) == 4, f"synthetic diff has 4 hunks (got {len(hk)})")
        expect(hk[1].net_deletion and hk[3].net_deletion and not hk[0].net_deletion and not hk[2].net_deletion, "net-deletion flags")
        expect("### hunk 2" in text and "### hunk 4" in text and "line 10" in text, "scaffold has verbatim blocks")

        def fill(t: str) -> str:
            t = t.replace(f"| 1 | {hk[0].header} |  |  |  |", f"| 1 | {hk[0].header} | 実装 | F01 | fix typo |")
            t = t.replace(f"| 2 | {hk[1].header} | 実装+削除 |  |  |", f"| 2 | {hk[1].header} | 実装+削除 | R02, MY-2 | compress the digression |")
            t = t.replace(f"| 3 | {hk[2].header} |  |  |  |", f"| 3 | {hk[2].header} | 裁量 |  | add a transition |")
            t = t.replace(f"| 4 | {hk[3].header} | 実装+削除 |  |  |", f"| 4 | {hk[3].header} | 裁量+削除 | R02 | merge two sentences |")
            return t.replace("<!-- 決定 ledger に無い変更を `hunk N: 何を・なぜ` で 1 行ずつ。 無ければ「なし」 -->",
                             "- hunk 3: transition sentence, not in any decision.\n- hunk 4: merged beyond R02's scope.")

        good = fill(text)
        sidecar = root / "review" / "edit-intent-2026-01-01.md"

        def run_check(content: str) -> tuple[bool, dict[str, bool]]:
            sidecar.write_text(content, encoding="utf-8")
            res, _ = check(sidecar, root)
            return all(r["passed"] for r in res), {r["name"]: r["passed"] for r in res}

        ok, names = run_check(good)
        expect(ok, f"filled scaffold passes ({names})")

        foils = [
            ("row removed → coverage", good.replace(f"| 3 | {hk[2].header} | 裁量 |  | add a transition |\n", ""), "hunk coverage"),
            ("unknown ID", good.replace("| F01 |", "| F99 |"), "ID 実在"),
            ("裁量 says なし", re.sub(r"- hunk 3:.*\n- hunk 4:.*", "なし", good), "裁量枠"),
            ("verbatim block deleted", re.sub(r"### hunk 2\n```latex\n(?:.*\n)*?```\n", "", good), "削除 verbatim"),
            ("verbatim altered", good.replace("line 11", "line 11 (paraphrased)"), "削除 verbatim"),
            ("位置 stale", good.replace(f"| 1 | {hk[0].header} |", "| 1 | -3,1 +99,1 |"), "位置"),
            ("net deletion without 削除", good.replace("| 実装+削除 | R02, MY-2 |", "| 実装 | R02, MY-2 |"), "削除 verbatim"),
            ("削除 on pure addition", good.replace("| 裁量 |  | add a transition |", "| 裁量+削除 |  | add a transition |"), "削除 verbatim"),
            ("empty 意図", good.replace("| fix typo |", "|  |"), "意図"),
            ("実装 without ID", good.replace("| 実装 | F01 |", "| 実装 |  |"), "ID 実在"),
            ("two primary kinds", good.replace("| 実装 | F01 |", "| 実装+裁量 | F01 |"), "種類"),
        ]
        for what, content, expected_fail in foils:
            ok, names = run_check(content)
            expect(not ok and names.get(expected_fail) is False, f"foil {what!r} must FAIL at {expected_fail} (got {names})")
        m3 = "L" + re.match(r"-(\d+)", hk[2].header).group(1)
        mapping = {"1": {"kind": "実装", "id": "F01", "intent": "fix typo"},
                   "2": {"id": "R02, MY-2", "intent": "compress the digression"},
                   m3: {"kind": "裁量", "id": "", "intent": "add a transition"},
                   "4": {"kind": "裁量+削除", "id": "R02", "intent": "merge two sentences"}}
        filled = fill_sidecar(text, mapping, "- hunk 3: transition sentence, not in any decision.\n- hunk 4: merged beyond R02's scope.")
        ok, names = run_check(filled)
        expect(ok, f"--fill output (keys by hunk and by old start line) passes ({names})")
        for bad, why in (({"1": mapping["1"]}, "row without an entry"), (dict(mapping, **{"9": mapping["1"]}), "entry matching no row"),
                         ):
            try:
                fill_sidecar(text, bad)
                expect(False, f"--fill must refuse a {why}")
            except ValueError:
                expect(True, f"--fill refuses a {why}")
        piped = fill_sidecar(text, dict(mapping, **{"1": {"kind": "実装", "id": "F01", "intent": r"kept |_{spinor} as a restriction"}}),
                             "- hunk 3: transition sentence, not in any decision.\n- hunk 4: merged beyond R02's scope.")
        expect(r"kept \|_{spinor}" in piped, "--fill escapes a pipe inside a cell")
        ok, _ = run_check(piped)
        expect(ok, "--fill output with an escaped pipe still passes the check")
        expect(any("kept |_{spinor} as a restriction" == r.intent for r in parse_sidecar(piped).rows),
               "an escaped pipe round-trips to the raw value when the sidecar is read back")
        ok, _ = run_check(text)
        expect(not ok, "raw scaffold (unfilled) must not pass")
    print(f"selftest OK ({checks} checks)")
    return 0


# ---------------------------------------------------------------- main

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - old pythons / non-tty
        pass
    ap = argparse.ArgumentParser(description="edit-intent sidecar: scaffold / check / selftest (conventions/edit-intent-record.md)")
    ap.add_argument("sidecar", nargs="?", help="sidecar .md to check")
    ap.add_argument("--root", help="manuscript repo root (default: git toplevel of the sidecar, or cwd for --scaffold)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--scaffold", action="store_true", help="generate a sidecar skeleton from the diff")
    ap.add_argument("--repo", default=".", help="git dir of the manuscript, relative to --root (scaffold)")
    ap.add_argument("--file", help="file inside that git dir (scaffold)")
    ap.add_argument("--base", help="commit before the pass (scaffold)")
    ap.add_argument("--head", help="implementation commit (scaffold)")
    ap.add_argument("--ledger", action="append", default=[], help="ledger path relative to --root (repeatable, scaffold)")
    ap.add_argument("--implementer", default="ai", help="claude / codex / human / <vendor> (scaffold)")
    ap.add_argument("--date", default=_dt.date.today().isoformat(), help="date for the sidecar (scaffold)")
    ap.add_argument("--out", help="write the scaffold here (refuses to overwrite); default stdout")
    ap.add_argument("--fill", metavar="SIDECAR", help="fill the empty 種類/ID/意図 cells of a scaffolded sidecar in place, then check it")
    ap.add_argument("--intents", help='JSON for --fill: {"<hunk>" or "L<old start>": {"kind": ..., "id": ..., "intent": ...}}')
    ap.add_argument("--discretion", help="text for the ## 裁量 section when filling (default なし)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.fill:
        if not a.intents:
            ap.error("--fill needs --intents FILE.json")
        target = Path(a.fill).expanduser().resolve()
        intents = json.loads(Path(a.intents).expanduser().read_text(encoding="utf-8"))
        try:
            new = fill_sidecar(target.read_text(encoding="utf-8"), intents, a.discretion)
        except ValueError as e:
            raise SystemExit(f"✗ --fill: {e}")
        target.write_text(new, encoding="utf-8")
        print(f"filled: {target}")
        a.sidecar = str(target)
    if a.scaffold:
        if not (a.file and a.base and a.head):
            ap.error("--scaffold needs --file, --base, --head")
        root = Path(a.root).expanduser().resolve() if a.root else Path.cwd()
        text = scaffold(root, a.repo, a.file, a.base, a.head, a.ledger or ["review/author-decisions.md"], a.implementer, a.date)
        if a.out:
            out = Path(a.out).expanduser()
            out = out if out.is_absolute() else root / out
            if out.exists():
                raise SystemExit(f"✗ refusing to overwrite {out}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            print(f"scaffold written: {out} ({text.count(chr(10))} lines) — fill 種類 / ID / 意図, then check")
        else:
            sys.stdout.write(text)
        return 0
    if not a.sidecar:
        ap.error("give a sidecar path, or --scaffold / --selftest")
    sidecar = Path(a.sidecar).expanduser().resolve()
    root = resolve_root(sidecar, a.root)
    results, infos = check(sidecar, root)
    passed = all(r["passed"] for r in results)
    if a.json:
        print(json.dumps({"passed": passed, "sidecar": str(sidecar), "root": str(root), "checks": results, "info": infos}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"[{'PASS' if r['passed'] else 'FAIL'}] {r['name']}: {r['detail']}")
        for line in infos:
            print(f"[INFO] {line}")
        print(f"\n{'ALL PASS' if passed else 'FAILED'} ({sum(r['passed'] for r in results)}/{len(results)})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
