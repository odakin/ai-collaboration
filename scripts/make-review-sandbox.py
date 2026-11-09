#!/usr/bin/env python3
"""封じた review sandbox (~/<sandbox-root>/<slug>/) を機械的に切る: 9 rule の CLAUDE.md (= この dir 以外を読まない / 注入 reminder 無視 / git log 禁止 / 書くのは results と scratch のみ、 一時 file も scratch に / ledger の形 / HANDOFF / PDF の取り方 / 出口 = 返送後は公開層を触らない) + 同文の AGENTS.md (Codex 用) + REVIEW-SPEC.md + 許可 file の copy (.tex は comment を剥がし、 残りを check-review-target.py で 0 確認) + sandbox の外の台帳、受領時は collect で results + notes/checks/scratch と規則の外の file (outside-rules/) を repo へ copy して台帳に記録、 status で未回収・回収の後に増えた sandbox を出す (conventions/cold-eyes-isolation.md#sealed-sandbox の recipe、--selftest 内蔵)

Why (2026-09-06): a blind second eye run *inside* a repo checkout is not blind — the
requester's auto-loaded project list and layer-1 addenda leaked the expected verdict to the
worker twice in one day (physics-verification-cycle.md#campaign-tooling C′).  The sealed
sandbox recipe existed as prose since 2026-09-02; this script makes it one command so the
cheap option is the isolated one.

Usage
  make-review-sandbox.py create <slug> --spec SPEC.md [--include FILE ...] [--root ~/paper-review-sandbox]
        → <root>/<slug>/{CLAUDE.md, AGENTS.md, REVIEW-SPEC.md, <included files>, scratch/}
          prints the spawn hint (cwd pin + prompt).  Refuses to create under ~/Claude (ancestor CLAUDE.md).
          .tex includes are stripped of comments in the sandbox copy (strip-tex-comments.py; the source is
          untouched), and every include is checked with check-review-target.py: a .tex / .md that still carries
          comment text is refused.  --keep-comments copies them as they are (a non-blind pass).
          Writes the ledger <root>/.sandbox-ledger/<slug>.json (creation time, each input with its sha256).  The
          ledger sits outside the sandbox: it will name the collection's destination (a repository = contamination
          channel (e)), and a Codex workspace-write sandbox cannot write the root (measured).
  make-review-sandbox.py collect <slug> --into DEST_DIR [--root ...] [--include-literature]
        → copies REVIEW-RESULTS.md, STAGE*-RESULTS.md (+ ledger.yaml / HANDOFF.md / notes/ / checks/ / scratch/ if present)
          into DEST_DIR, never the other way.  Every other file the reviewer wrote anywhere in the sandbox (the root,
          other directories, deeper levels) goes to DEST_DIR/outside-rules/<its relative path>, and is listed: copied and
          announced, not refused (measured: files outside those places were dropped without a word, and a refusing
          collect stops an unattended receipt before anything is kept).  A file is the reviewer's when it is not an input
          unchanged since create (the ledger's sha256; a sandbox without a ledger falls back to file times).
          Third-party and generated trees (venv, .venv, site-packages, node_modules, __pycache__, .ipynb_checkpoints,
          tool caches, *.egg-info, .git) are not copied; their file counts are printed.  The collection (time, destination,
          every file with its sha256) is appended to the ledger, so status can name a sandbox written to after it.
          Collect again after each further round with the same reviewer.  Prints the contamination-grep reminder.
          Pass the same --root as create.
          When DEST_DIR is inside a git work tree, it warns about collected files the repository ignores (a LaTeX `*.out`
          rule drops checker outputs and `git add <dir>` skips them silently; add them with `git add -f`).
          The literature the reviewer downloaded (in scratch/ or outside the rule places: PDF, e-print archives, saved web
          pages, and their text extracts and page images = the same stem, or <stem>-… / <stem>_… / <stem>v…; an unpacked
          e-print = a directory with the name of an archive) is not copied: it is someone else's copyrighted work and
          DEST_DIR is often a repository or a synced folder shared with collaborators (measured).  Code (.py .sh .wl .m
          .jl .ipynb .nb …) and the reviewer's prose (.tex .md) are kept even when named after a paper, and so is a
          directory named after a PDF (the reviewer's working directory; measured: the earlier rule dropped a check script
          inside one, and a re-derivation .tex); these are listed as "named like literature".  Derived files under names the
          reviewer chose are not recognized: look through DEST_DIR before committing.  The originals stay in the sandbox;
          --include-literature copies them anyway.
  make-review-sandbox.py status [<slug> ...] [--root ...] [--find-in DIR] [--json]
        → every sandbox under the root (or the named ones): not collected / collected and unchanged / written to after the
          collection (N files new or changed) / closed.  Reads the ledger and the file list, never prints file contents.
          A sandbox made before the ledger existed shows "no ledger"; --find-in DIR then hashes the reviewer's files
          (literature and trees aside) and counts those with no same-content file under DIR (slow on a large tree).
  make-review-sandbox.py close <slug> --reason TEXT [--root ...]
        → records that the sandbox will not be collected (a stopped judge session that is discarded, a trial run); status
          shows it as closed until something in it changes.
  make-review-sandbox.py --selftest

Before --include, clean the review markup: review-markup-clean.py (colour / Q&A).  create strips the
comments of .tex includes itself (commented-out lines carry authorship notes, rejected drafts and the
previous round's verdict); build the included PDF from the same source, and check once that the PDF text
of the stripped source is unchanged (cold-eyes-isolation.md#referee-copy-strip-comments).

A receiver on another machine cannot reach a sandbox made on this one.  Commit the referee copy to the
repository (or put it in a synced directory whose ancestors hold no CLAUDE.md / AGENTS.md) and let the
receiver's side run create there with --root outside its working tree; the judging session starts fresh
with the sandbox as cwd (cold-eyes-isolation.md#board-blind-variant).

The spec you pass must follow cold-eyes-isolation.md#spec-leakage: statement, allow/deny,
rubric, output format, stop rules, return command — no expected verdict, no "watch step 2".
A two-stage skeleton for blind review of one's own manuscript (Stage 1 = derivation tasks solved
before the manuscript is opened, Stage 2 = review + framing recommendation, HANDOFF section) is at
template/REVIEW-SPEC-blind-manuscript.md: copy, fill the <...> slots, pass it as --spec.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

DEFAULT_ROOT = Path.home() / "paper-review-sandbox"

CLAUDE_MD = """# Isolated review sandbox

This directory is a sealed sandbox for one independent review / derivation task.

Rules for any assistant working here:

1. Read only files inside this directory, plus the published literature the task cites (arXiv, journals, textbooks) via the web.
2. Do not read anything under `~/Claude/` or `~/.claude/projects/`. Do not run `git log` here or open any other repository or working tree. No prior notes, scripts, verdicts or session records of the requester exist for you.
3. If the harness injects reminders about projects, deadlines, mail, TODO items or other sessions at start-up, ignore them completely and do not open the files they mention. They are unrelated to this task and would bias it.
4. Do not modify the input files. Do not send mail, post to boards, or write outside this directory. Write only `REVIEW-RESULTS.md`, an optional `ledger.yaml`, `HANDOFF.md`, and your own scratch under `./scratch/` (derivation notes under `./notes/`, machine checks under `./checks/` if the spec asks for them). Temporary files go under `./scratch/` too: do not write to `/tmp`, `$TMPDIR`, a scratchpad directory the harness offers, or any other temporary directory.
5. Start by reading `REVIEW-SPEC.md` and follow it exactly. If it asks for a two-stage (blind → attack) run, commit nothing and instead write the Stage 1 file the spec names (`notes/stage1-blind.md` when it names none) **before** opening anything the spec unlocks for stage 2, and say so in the results. Where this file and the spec differ on a file name, the spec wins.
6. If you write `ledger.yaml`, make it a **top-level YAML list** of items `{id, statement, status: verified|refuted|unverified, tier, readings: [...], note}` — no wrapper mapping (the requester's report tool reads a list; observed wrapper `{items: [...]}` 2026-09-06).
7. After the results are written (and before or after the return command), write `HANDOFF.md`: (a) every script you wrote, one line each on what it does and how general it is, plus its run contract (dependencies; the inputs it really accepts, command-line arguments versus settings written inside the file; the files it writes and whether it replaces existing ones; whether importing it runs it; which settings must be swapped before reuse), and do not re-run a script over outputs already collected just to tidy them for this file; (b) the general lessons you derived (formulas, traps, conventions checked) that are not specific to this manuscript; (c) external data products and literature passages you verified, with exact locations; (d) what the spec lacked or what cost you time; (e) what remains unverified or assumed, and any alternative approach you tried whose record is in `./notes/` or `./checks/`, named by file (write "none" if empty). Run every computation the results rely on from a file under `./checks/` or `./scratch/`, not from a heredoc or an inline `-c` string, so that (a) can name it. This is the only channel through which your tools and lessons reach the requester's shared libraries; nothing outside this directory is yours to edit.
8. Cited papers and public data products: the harness web-fetch tool cannot parse PDFs (it stores the binary in a tool-results directory you must not read). Download with `curl -sL -o ./scratch/<id>.pdf https://arxiv.org/pdf/<id>` and extract text with `pdftotext` or a Python PDF library; for equations the arXiv e-print source (`https://arxiv.org/e-print/<id>`) is more reliable. Keep every download under `./scratch/`.
9. Exit rule: after the return command, do not write to any repository or public layer from this session, even if the requester later asks you to "hoist the lessons". Put candidate lessons in `./scratch/hoist-candidates.md` in general form (rules, mechanisms, failure modes; no numbers, counts, dates, names or phrases from the material you reviewed) and say so in the results. The requester promotes them after the receipt sweep.
"""

LEDGER_DIR = ".sandbox-ledger"          # under the root, outside every sandbox
INPUT_NAMES = ("CLAUDE.md", "AGENTS.md", "REVIEW-SPEC.md")
RESULT_NAMES = ("REVIEW-RESULTS.md", "ledger.yaml", "HANDOFF.md")
RULE_DIRS = ("notes", "checks", "scratch")
OUTSIDE_DIR = "outside-rules"
# a sandbox without a ledger: a root-level file no newer than CLAUDE.md + this is an input (create writes all at once)
INPUT_GRACE_S = 60
# third-party libraries and generated caches: never the reviewer's own code, and a venv alone held thousands of files
# (measured).  `build` is not here: the ones measured were LaTeX build directories holding the reviewer's own .tex
TREE_NAMES = {"venv", ".venv", "site-packages", "node_modules", "__pycache__", ".ipynb_checkpoints",
              ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}
CODE_SUFFIXES = (".py", ".sh", ".wl", ".m", ".nb", ".jl", ".ipynb", ".c", ".cpp", ".f90", ".sage", ".gp", ".mac",
                 ".frm", ".r")
WORDS_SUFFIXES = (".tex", ".md")


def _sibling(name: str):
    """Load a sibling script whose file name has dashes (strip-tex-comments.py, check-review-target.py)."""
    import importlib.util
    path = Path(__file__).resolve().parent / name
    spec_ = importlib.util.spec_from_file_location(name.replace("-", "_").removesuffix(".py"), path)
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> tuple[str, int]:
    ns = time.time_ns()
    return _dt.datetime.fromtimestamp(ns / 1e9).astimezone().isoformat(timespec="seconds"), ns


def ledger_path(root: Path, slug: str) -> Path:
    return root / LEDGER_DIR / f"{slug}.json"


def read_ledger(root: Path, slug: str) -> dict | None:
    try:
        return json.loads(ledger_path(root, slug).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_ledger(root: Path, slug: str, data: dict) -> Path:
    p = ledger_path(root, slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p


def _inferred_ledger(sb: Path, slug: str) -> dict:
    cm = sb / "CLAUDE.md"
    at = _dt.datetime.fromtimestamp(cm.stat().st_mtime).astimezone().isoformat(timespec="seconds") if cm.exists() else None
    return {"version": 1, "slug": slug, "created": {"at": at, "inferred": "CLAUDE.md file time (made before the ledger)"},
            "inputs": None, "collections": []}


def create(root: Path, slug: str, spec: Path, includes: list[Path], keep_comments: bool = False) -> Path:
    if str(root.resolve()).startswith(str((Path.home() / "Claude").resolve())):
        raise SystemExit("✗ refuse: sandbox root is under ~/Claude (ancestor CLAUDE.md would be auto-loaded)")
    sb = root / slug
    if sb.exists() and any(sb.iterdir()):
        raise SystemExit(f"✗ refuse: {sb} exists and is not empty (pick another slug or clean it)")
    (sb / "scratch").mkdir(parents=True, exist_ok=True)
    (sb / "CLAUDE.md").write_text(CLAUDE_MD, encoding="utf-8")
    (sb / "AGENTS.md").write_text(CLAUDE_MD, encoding="utf-8")   # Codex reads AGENTS.md (cold-eyes-isolation.md §1 (a))
    shutil.copy2(spec, sb / "REVIEW-SPEC.md")
    strip = None if keep_comments else _sibling("strip-tex-comments.py").strip_for   # .tex and .bib (cold-eyes (d))
    for f in includes:
        if strip and f.suffix.lower() in (".tex", ".bib"):
            src = f.read_text(encoding="utf-8")
            out = strip(f.name, src)
            (sb / f.name).write_text(out, encoding="utf-8")
            print(f"  stripped {f.name}: {src.count(chr(10)) - out.count(chr(10))} comment line(s) removed in the sandbox copy "
                  "(build the included PDF from the same source)")
        else:
            shutil.copy2(f, sb / f.name)
    if not keep_comments:
        check = _sibling("check-review-target.py")
        left = [r for r in (check.scan(sb / f.name) for f in includes) if r["hits"]]
        if left:
            raise SystemExit("✗ refuse: referee copy still carries comments (cold-eyes-isolation.md#contamination-channels (d)):\n"
                             + check.report(left))
        warned = [r for r in (check.scan(sb / f.name) for f in includes) if r.get("warnings")]
        if warned:   # not refused: the author decides whether the sentence is subject or the target's own history
            print(check.report(warned))
    at, ns = _now()
    names = list(INPUT_NAMES) + [f.name for f in includes]
    write_ledger(root, slug, {"version": 1, "slug": slug, "created": {"at": at, "at_ns": ns},
                              "inputs": {n: _sha256(sb / n) for n in dict.fromkeys(names)}, "collections": []})
    return sb


LITERATURE_SUFFIXES = (".pdf", ".tar.gz", ".tgz", ".tar", ".tar.bz2", ".tar.xz", ".gz", ".zip", ".djvu", ".epub")
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar", ".tar.bz2", ".tar.xz", ".gz", ".zip")
# saved web pages (abstract pages, journal landing pages, API answers) are third-party text too
PAGE_SUFFIXES = (".html", ".htm", ".xml")
# what a reviewer derives from a downloaded file and names after it (text extracts, page images, saved pages);
# code and the reviewer's own prose named after a paper are not in this list (kept, listed as "named like literature")
DERIVED_SUFFIXES = (".txt", ".png", ".jpg", ".jpeg", ".ppm", ".pgm", ".html", ".htm", ".xml", ".bbl", ".ps", ".eps")
# the directory an e-print archive is unpacked into: its own name, or that name plus one of these
UNPACK_SUFFIXES = ("", "-src", "_src", "-source", "_source", "-eprint", "_eprint")


def literature_split(dirpath: Path, names) -> tuple[set, set, set]:
    """(directories that are unpacked e-prints, files that are literature, names kept although named like literature).

    Literature by name: the downloads (LITERATURE_SUFFIXES), saved web pages (PAGE_SUFFIXES), and a file named after a
    download (the same stem, or <stem><-_.v...>) whose suffix is a text extract or an image (DERIVED_SUFFIXES).  A
    directory is literature only when it has the name of an archive (the unpacked e-print source = third-party TeX).
    Code and the reviewer's prose named after a paper, and a directory named after a PDF, are kept and reported.
    Measured: the earlier rule kept unpacked `<id>-src/` directories, `<id>-abs.html` pages and page images with their
    OCR (third-party sources reached the destination repository); its replacement then dropped a check script inside a
    PDF-named directory, a `<id>-rederive/` directory and `<id>-notes.tex`."""
    names = list(names)
    bases = {n[: -len(suf)] for n in names for suf in LITERATURE_SUFFIXES + PAGE_SUFFIXES
             if n.lower().endswith(suf) and len(n) > len(suf)}
    archive_bases = {n[: -len(suf)] for n in names for suf in ARCHIVE_SUFFIXES
                     if n.lower().endswith(suf) and len(n) > len(suf)}

    def derived(n: str) -> bool:
        return any(n.startswith(b) and len(n) > len(b) and n[len(b)] in "-_.v" for b in bases if b)

    lit_dirs, lit_files, look = set(), set(), set()
    for n in names:
        low = n.lower()
        if (dirpath / n).is_dir():
            if any(n == b + s for b in archive_bases for s in UNPACK_SUFFIXES):
                lit_dirs.add(n)
            elif n in bases or derived(n):
                look.add(n)
            continue
        if low.endswith(LITERATURE_SUFFIXES + PAGE_SUFFIXES):
            lit_files.add(n)
        elif Path(n).stem in bases or derived(n):
            (lit_files if low.endswith(DERIVED_SUFFIXES) and not low.endswith(CODE_SUFFIXES + WORDS_SUFFIXES)
             else look).add(n)
    return lit_dirs, lit_files, look


def _is_tree(name: str) -> bool:
    return name in TREE_NAMES or name.endswith(".egg-info")


def _files_below(d: Path) -> list[Path]:
    return [Path(dp) / n for dp, _dn, fn in os.walk(d) for n in fn]


def inventory(sb: Path, ledger: dict | None) -> dict:
    """What is in the sandbox now, sorted by what collect does with it (paths relative to the sandbox, posix):

    results = the result files at the root / rules = files under notes/ checks/ scratch/ / outside = every other file
    the reviewer wrote (root or other directories) / literature = downloads by name (scratch/ and outside the rule
    places; notes/ and checks/ are copied whole) / lookalike = kept although named like literature / trees =
    {tree dir: file count}, not copied / inputs_changed = inputs whose sha256 differs from the ledger's /
    files = {path: sha256} of every file outside the trees (the collection's "seen", and the diff for status) /
    mtime = {path: file time} of the reviewer's files.  An unchanged input is in files and nowhere else."""
    inputs = (ledger or {}).get("inputs")
    base = None
    if inputs is None:
        cm = sb / "CLAUDE.md"
        base = cm.stat().st_mtime + INPUT_GRACE_S if cm.exists() else None
    out: dict = {"results": [], "rules": [], "outside": [], "literature": [], "lookalike": [], "trees": {},
                 "inputs_changed": [], "files": {}, "mtime": {}}

    def note(p: Path, rs: str) -> str | None:
        try:
            out["files"][rs] = _sha256(p)
            out["mtime"][rs] = p.stat().st_mtime
        except OSError:
            return None
        return out["files"][rs]

    for dirpath, dirnames, filenames in os.walk(sb):
        d = Path(dirpath)
        rel_d = d.relative_to(sb)
        top = rel_d.parts[0] if rel_d.parts else None
        if top in ("notes", "checks"):
            lit_dirs, lit_files, look = set(), set(), set()
        else:
            lit_dirs, lit_files, look = literature_split(d, dirnames + filenames)
        keep = []
        for n in sorted(dirnames):
            r = (rel_d / n).as_posix()
            if _is_tree(n) or (d / n / "pyvenv.cfg").is_file():   # a venv under any name
                out["trees"][r] = len(_files_below(d / n))
            elif n in lit_dirs:
                for f in sorted(_files_below(d / n)):
                    rs = f.relative_to(sb).as_posix()
                    if note(f, rs) is not None:
                        out["literature"].append(rs)
            else:
                if n in look:
                    out["lookalike"].append(r + "/")
                keep.append(n)
        dirnames[:] = keep
        for n in sorted(filenames):
            p, rs = d / n, (rel_d / n).as_posix()
            h = note(p, rs)
            if h is None:
                continue
            if top is None:   # the sandbox root
                if n in RESULT_NAMES or (n.startswith("STAGE") and n.endswith("-RESULTS.md")):
                    out["results"].append(rs)
                    continue
                if inputs is not None and rs in inputs:
                    if inputs[rs] == h:
                        out["mtime"].pop(rs, None)
                        continue
                    out["inputs_changed"].append(rs)
                elif inputs is None and (n in INPUT_NAMES or (base is not None and out["mtime"][rs] <= base)):
                    out["mtime"].pop(rs, None)
                    continue
            if n in lit_files:
                out["literature"].append(rs)
                continue
            if n in look:
                out["lookalike"].append(rs)
            (out["rules"] if top in RULE_DIRS else out["outside"]).append(rs)
    return out


def reviewer_files(inv: dict, literature: bool = True) -> list[str]:
    """Every file the reviewer wrote (results, rule places, outside them, and with literature=True the downloads)."""
    return inv["results"] + inv["rules"] + inv["outside"] + (inv["literature"] if literature else [])


def reviewer_code(inv: dict) -> list[str]:
    """The reviewer's code anywhere in the sandbox (any depth, any listed suffix), trees and literature aside."""
    return [r for r in reviewer_files(inv, literature=False) if r.lower().endswith(CODE_SUFFIXES)]


def _copy_keep(src: Path, dst: Path, kept: list[Path]) -> bool:
    """Copy unless the destination exists with other content (the requester may have annotated it). True = copied or same."""
    if dst.exists() and dst.read_bytes() != src.read_bytes():
        kept.append(dst)
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)
    return True


def _some(items, n: int = 12) -> str:
    items = list(items)
    return ", ".join(items[:n]) + (f", … (+{len(items) - n})" if len(items) > n else "")


def collect(root: Path, slug: str, into: Path, include_literature: bool = False) -> list[Path]:
    sb = root / slug
    if not sb.exists():
        raise SystemExit(f"✗ no sandbox at {sb} (made with another --root? pass the same --root as create)")
    ledger = read_ledger(root, slug)
    inv = inventory(sb, ledger)
    into.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    taken: list[str] = []
    order = {n: i for i, n in enumerate(RESULT_NAMES)}
    for rs in sorted(inv["results"], key=lambda r: (order.get(r, len(order)), r)):   # HANDOFF.md = hoist packet (2026-09-08)
        p, dest = sb / rs, into / rs
        if dest.exists() and dest.read_bytes() != p.read_bytes():
            # never clobber a file the requester has already annotated (novel_to_requester etc.);
            # observed 2026-09-06: a second collect silently reverted the ledger to the sandbox copy
            print(f"  ↷ kept existing {dest} (differs from sandbox copy; delete it first if you really want the sandbox version)")
            continue
        shutil.copy2(p, dest)
        copied.append(dest)
        taken.append(rs)
    kept: list[Path] = []
    lit = set(inv["literature"])
    groups: set[str] = set()
    for rs in inv["rules"] + inv["outside"] + (inv["literature"] if include_literature else []):   # scratch too: a
        top = rs.split("/", 1)[0]                                                           # worker's scripts are never discarded
        inside = "/" in rs and top in RULE_DIRS
        dest = into / rs if inside else into / OUTSIDE_DIR / rs
        if _copy_keep(sb / rs, dest, kept):
            taken.append(rs)
        groups.add(top if inside else OUTSIDE_DIR)
    copied.extend(into / g for g in (*RULE_DIRS, OUTSIDE_DIR) if g in groups)
    if kept:
        print(f"  ↷ kept {len(kept)} existing file(s) that differ from the sandbox copy, e.g. {kept[0]}"
              " (delete one first if you really want the sandbox version)")
    if inv["outside"]:
        print(f"  ⚠️ {len(inv['outside'])} file(s) the reviewer wrote outside the rule places (the root's result files,"
              f" notes/ checks/ scratch/) copied to {into / OUTSIDE_DIR} under their relative paths — read them before"
              f" committing and delete what the receipt does not need: {_some(inv['outside'])}")
    if inv["inputs_changed"]:
        print(f"  ⚠️ input file(s) changed in the sandbox since create (the copy is in {OUTSIDE_DIR}/):"
              f" {_some(inv['inputs_changed'])}")
    if inv["trees"]:
        print(f"  ↷ not copied: {len(inv['trees'])} third-party / generated tree(s), {sum(inv['trees'].values())} file(s):"
              f" {_some(f'{k} ({v})' for k, v in sorted(inv['trees'].items()))} — copy one by hand if it is the reviewer's own")
    if lit and not include_literature:
        print(f"  ↷ not copied: {len(lit)} literature file(s) (PDF / e-print / saved pages / what is named after them; the"
              f" originals stay in {sb}): {_some(sorted(lit))}. --include-literature copies them."
              f" Derived files under names the reviewer chose are not recognized: look through {into} before committing")
    if inv["lookalike"]:
        print(f"  ↷ kept {len(inv['lookalike'])} named like literature (the reviewer's code, prose or working directory;"
              f" check that none is third-party text): {_some(inv['lookalike'])}")
    at, ns = _now()
    led = ledger or _inferred_ledger(sb, slug)
    led.setdefault("collections", []).append({
        "at": at, "at_ns": ns, "into": str(into.resolve()), "copied": sorted(set(taken)), "outside_rules": inv["outside"],
        "literature_skipped": [] if include_literature else sorted(lit), "trees": inv["trees"], "seen": inv["files"]})
    lp = write_ledger(root, slug, led)
    print(f"  recorded the collection in {lp} (status names this sandbox if it is written to after now: collect again then)")
    ignored = git_ignored(into, copied)
    if ignored:
        names = ", ".join(sorted({p.suffix or p.name for p in ignored}))
        print(f"  ⚠️ {len(ignored)} collected file(s) are ignored by the destination repository ({names}): `git add` of the"
              f" directory skips them without a message. Add them by name with `git add -f` if the receipt cites them,"
              f" e.g. {ignored[0]}")
    return copied


def close(root: Path, slug: str, reason: str) -> Path:
    sb = root / slug
    if not sb.exists():
        raise SystemExit(f"✗ no sandbox at {sb} (made with another --root? pass the same --root as create)")
    if not reason.strip():
        raise SystemExit("✗ close needs --reason (why this sandbox will not be collected)")
    led = read_ledger(root, slug) or _inferred_ledger(sb, slug)
    at, ns = _now()
    led["closed"] = {"at": at, "at_ns": ns, "reason": reason.strip(), "seen": inventory(sb, led)["files"]}
    return write_ledger(root, slug, led)


def is_sealed_sandbox(d: Path) -> bool:
    """A sandbox create made (CLAUDE.md = "# Isolated review sandbox"), or one made by hand before the script with the
    same kind of heading ("# Isolated referee sandbox", "# Isolated check sandbox", measured), with or without a spec."""
    for name in ("CLAUDE.md", "AGENTS.md"):
        try:
            with open(d / name, encoding="utf-8", errors="replace") as fh:
                first = fh.readline().strip()
        except OSError:
            continue
        if first.startswith("# Isolated ") and first.endswith("sandbox"):
            return True
    return False


def _size_index(tree: Path) -> dict:
    """Every file under tree by size (trees left out); hashed on demand by _same_content_under."""
    by: dict[int, list[str]] = {}
    for dp, dn, fn in os.walk(tree.resolve()):   # resolved, as the sandbox path it is compared with
        dn[:] = [d for d in dn if not _is_tree(d)]
        for n in fn:
            p = os.path.join(dp, n)
            try:
                by.setdefault(os.path.getsize(p), []).append(p)
            except OSError:
                pass
    return {"by_size": by, "sha": {}}


def _same_content_under(index: dict, digest: str, size: int, skip_prefix: str) -> bool:
    for p in index["by_size"].get(size, ()):
        if p.startswith(skip_prefix):   # the sandbox itself, when the tree holds it
            continue
        if p not in index["sha"]:
            try:
                index["sha"][p] = _sha256(Path(p))
            except OSError:
                index["sha"][p] = None
        if index["sha"][p] == digest:
            return True
    return False


def sandbox_state(root: Path, slug: str, find_in: Path | None = None, _index: dict | None = None) -> dict:
    """The collection state of one sandbox, from its ledger and its file list (contents are hashed, never shown).

    state = not_sealed / empty (nothing written yet) / uncollected / collected / changed_after_collect / closed /
    changed_after_close / no_ledger.  changed = files new or with other content than at the last collection (or close).
    With find_in, a no_ledger sandbox also gets missing = its reviewer files (literature aside) with no same-content
    file under find_in."""
    sb = root / slug
    st: dict = {"slug": slug, "sandbox": str(sb)}
    if not is_sealed_sandbox(sb):
        st["state"] = "not_sealed"
        return st
    led = read_ledger(root, slug)
    inv = inventory(sb, led)
    mine = reviewer_files(inv)
    st.update(ledger=led is not None, written=len(mine), code=reviewer_code(inv), outside=inv["outside"],
              trees=inv["trees"], literature=len(inv["literature"]),
              last_write=max((inv["mtime"].get(r, 0) for r in mine), default=None))
    cols = (led or {}).get("collections") or []
    closed = (led or {}).get("closed")
    ref, kind = None, None
    if cols:
        ref, kind = cols[-1].get("seen") or {}, "collect"
        st.update(collected_at=cols[-1].get("at"), into=cols[-1].get("into"), collections=len(cols))
    if closed and (not cols or closed.get("at_ns", 0) > cols[-1].get("at_ns", 0)):
        ref, kind = closed.get("seen") or {}, "close"
        st.update(closed_at=closed.get("at"), reason=closed.get("reason"))
    if ref is not None:
        st["changed"] = [r for r in mine if ref.get(r) != inv["files"].get(r)]
        st["state"] = ({"collect": "collected", "close": "closed"} if not st["changed"] else
                       {"collect": "changed_after_collect", "close": "changed_after_close"})[kind]
    elif led is None:
        st["state"] = "no_ledger"
        if find_in is not None:
            want = {r: inv["files"][r] for r in reviewer_files(inv, literature=False)}
            if _index is None:
                _index = {}
            key = str(find_in)
            if key not in _index:   # one walk of the tree for every sandbox of a status run
                _index[key] = _size_index(find_in)
            skip = str(sb.resolve()) + os.sep
            st["missing"] = [r for r, h in want.items()
                             if not _same_content_under(_index[key], h, (sb / r).stat().st_size, skip)]
            st["missing_code"] = [r for r in st["missing"] if r.lower().endswith(CODE_SUFFIXES)]
    else:
        st["state"] = "uncollected" if mine else "empty"
    return st


def _age(ts) -> str:
    if not ts:
        return "never"
    s = max(0, time.time() - ts)
    return f"{s / 86400:.0f} day(s) ago" if s >= 86400 else f"{s / 3600:.0f} hour(s) ago"


def state_line(st: dict) -> str:
    s = st["state"]
    if s == "not_sealed":
        return f"{st['slug']}: not a sealed sandbox (no CLAUDE.md / AGENTS.md headed \"# Isolated … sandbox\")"
    tail = (f"the reviewer wrote {st['written']} file(s) (code {len(st['code'])}, outside the rule places"
            f" {len(st['outside'])}), last write {_age(st['last_write'])}")
    if s == "empty":
        return f"{st['slug']}: nothing written yet"
    if s == "uncollected":
        return f"{st['slug']}: NOT COLLECTED — {tail} → collect {st['slug']} --into <receipt dir>"
    if s == "collected":
        return f"{st['slug']}: collected {st['collected_at']} into {st['into']}, unchanged since"
    if s == "changed_after_collect":
        return (f"{st['slug']}: WRITTEN TO AFTER THE COLLECTION of {st['collected_at']} (into {st['into']}):"
                f" {len(st['changed'])} file(s) new or changed, e.g. {_some(st['changed'], 3)} → collect again")
    if s == "closed":
        return f"{st['slug']}: closed {st['closed_at']} ({st['reason']}), unchanged since"
    if s == "changed_after_close":
        return (f"{st['slug']}: WRITTEN TO AFTER IT WAS CLOSED ({st['closed_at']}): {len(st['changed'])} file(s) new or"
                f" changed → collect, or close again")
    line = f"{st['slug']}: no ledger (made before the ledger existed, or the ledger is on another machine) — {tail} by file time"
    if "missing" in st:
        line += (f"; {len(st['missing'])} of them (code {len(st['missing_code'])}) have no same-content file under the"
                 " --find-in tree")
    return line


def sandboxes(root: Path, slugs: list[str] | None = None) -> list[str]:
    if slugs:
        return list(slugs)
    try:
        return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []


def status(root: Path, slugs: list[str] | None = None, find_in: Path | None = None) -> list[dict]:
    index: dict = {}
    return [sandbox_state(root, s, find_in, index) for s in sandboxes(root, slugs)]


def git_ignored(into: Path, copied: list[Path]) -> list[Path]:
    """Files under the copied paths that git would not add (measured: a LaTeX `*.out` rule dropped the outputs of the
    reviewer's checks).  Empty when DEST is not in a git work tree or git is missing."""
    files = [f for p in copied for f in ([p] if p.is_file() else sorted(q for q in p.rglob("*") if q.is_file()))]
    if not files:
        return []
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(into), "check-ignore", "--stdin"], input="\n".join(str(f) for f in files),
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode not in (0, 1):   # 128 = not a work tree
        return []
    return [Path(line) for line in r.stdout.splitlines() if line.strip()]


def selftest() -> int:
    import tempfile
    import contextlib, io
    n_checks = 0

    def ok(cond, msg=""):
        nonlocal n_checks
        n_checks += 1
        assert cond, msg

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "sb"
        spec = Path(td) / "spec.md"; spec.write_text("# spec\n", encoding="utf-8")
        inc = Path(td) / "paper.pdf"; inc.write_bytes(b"%PDF")
        sb = create(root, "t1", spec, [inc])
        ok((sb / "CLAUDE.md").exists() and (sb / "REVIEW-SPEC.md").exists() and (sb / "paper.pdf").exists() and (sb / "scratch").is_dir())
        try:
            create(root, "t1", spec, []); raise AssertionError("should refuse non-empty")
        except SystemExit as e:
            ok("refuse" in str(e))
        try:
            create(Path.home() / "Claude" / "zz-sandbox-selftest", "x", spec, []); raise AssertionError("should refuse under ~/Claude")
        except SystemExit as e:
            ok("refuse" in str(e))
        # the ledger: outside the sandbox, with the inputs' sha256
        led = read_ledger(root, "t1")
        ok(led and set(led["inputs"]) == {"CLAUDE.md", "AGENTS.md", "REVIEW-SPEC.md", "paper.pdf"}, led)
        ok(not any(LEDGER_DIR in str(p) for p in sb.rglob("*")) and ledger_path(root, "t1").parent.parent == root)
        ok(sandbox_state(root, "t1")["state"] == "empty")
        (sb / "REVIEW-RESULTS.md").write_text("ok\n", encoding="utf-8")
        (sb / "STAGE2-RESULTS.md").write_text("stage 2\n", encoding="utf-8")
        (sb / "notes").mkdir(); (sb / "notes" / "stage1-blind.md").write_text("blind\n", encoding="utf-8")
        (sb / "scratch" / "try.py").write_text("print(1)\n", encoding="utf-8")
        (sb / "HANDOFF.md").write_text("# handoff\n", encoding="utf-8")
        ok(sandbox_state(root, "t1")["state"] == "uncollected")
        got = collect(root, "t1", Path(td) / "dest")
        ok((Path(td) / "dest" / "REVIEW-RESULTS.md").exists() and (Path(td) / "dest" / "notes" / "stage1-blind.md").exists(), got)
        ok((Path(td) / "dest" / "scratch" / "try.py").exists() and (Path(td) / "dest" / "HANDOFF.md").exists(), got)
        ok((Path(td) / "dest" / "STAGE2-RESULTS.md").read_text(encoding="utf-8") == "stage 2\n", got)
        ok(not (Path(td) / "dest" / "paper.pdf").exists() and not (Path(td) / "dest" / OUTSIDE_DIR).exists(), "inputs stay")
        ok("HANDOFF.md" in CLAUDE_MD)
        ok(sandbox_state(root, "t1")["state"] == "collected")
        (Path(td) / "dest" / "REVIEW-RESULTS.md").write_text("annotated\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            collect(root, "t1", Path(td) / "dest")
        ok((Path(td) / "dest" / "REVIEW-RESULTS.md").read_text(encoding="utf-8") == "annotated\n")  # second collect must not clobber
        (Path(td) / "dest" / "notes" / "stage1-blind.md").write_text("annotated\n", encoding="utf-8")
        (sb / "notes" / "later.md").write_text("later\n", encoding="utf-8")
        st = sandbox_state(root, "t1")
        ok(st["state"] == "changed_after_collect" and st["changed"] == ["notes/later.md"], st)   # a later round shows
        with contextlib.redirect_stdout(io.StringIO()):
            collect(root, "t1", Path(td) / "dest")
        ok((Path(td) / "dest" / "notes" / "stage1-blind.md").read_text(encoding="utf-8") == "annotated\n")  # nor below a directory
        ok((Path(td) / "dest" / "notes" / "later.md").exists())  # a file that is new in the sandbox still arrives
        ok(sandbox_state(root, "t1")["state"] == "collected" and len(read_ledger(root, "t1")["collections"]) == 3)
        # downloaded literature (PDF / e-print / same-stem text extract) stays in the sandbox unless asked for
        for name in ("cited_2401.00001.pdf", "cited_2401.00001.txt", "cited_src.tar.gz", "numbers.txt"):
            (sb / "scratch" / name).write_text("x\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            collect(root, "t1", Path(td) / "dest-lit")
        got_lit = sorted(q.name for q in (Path(td) / "dest-lit" / "scratch").iterdir())
        ok(got_lit == ["numbers.txt", "try.py"], got_lit)
        # unpacked e-print source, saved abstract page, page images / OCR and other versions are third-party too;
        # a script named after the paper is the reviewer's own
        (sb / "scratch" / "2401.00002-src.tgz").write_text("x\n", encoding="utf-8")
        (sb / "scratch" / "2401.00002-src").mkdir()
        (sb / "scratch" / "2401.00002-src" / "main.tex").write_text("x\n", encoding="utf-8")
        for name in ("2401.00002.pdf", "2401.00002-abs.html", "2401.00002_p-01.png", "2401.00002_p-01.txt",
                     "2401.00002v1.txt", "2401.00002_check.py", "journal_landing.html"):
            (sb / "scratch" / name).write_text("x\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            collect(root, "t1", Path(td) / "dest-lit2")
        got_lit2 = sorted(q.name for q in (Path(td) / "dest-lit2" / "scratch").iterdir())
        ok(got_lit2 == ["2401.00002_check.py", "numbers.txt", "try.py"], got_lit2)
        with contextlib.redirect_stdout(io.StringIO()):
            collect(root, "t1", Path(td) / "dest-all", include_literature=True)
        ok((Path(td) / "dest-all" / "scratch" / "cited_2401.00001.txt").exists())
        try:
            collect(Path(td) / "elsewhere", "t1", Path(td) / "dest-x"); raise AssertionError("should refuse a missing sandbox")
        except SystemExit as e:
            ok("--root" in str(e))
        # a destination repository whose .gitignore drops checker outputs (LaTeX `*.out`) gets a warning, not a silent loss
        import shutil as _sh, subprocess as _sp
        if _sh.which("git"):
            repo = Path(td) / "repo"; repo.mkdir()
            _sp.run(["git", "init", "-q", str(repo)], check=True)
            (repo / ".gitignore").write_text("*.out\n", encoding="utf-8")
            (sb / "checks").mkdir(exist_ok=True); (sb / "checks" / "c01.py").write_text("print(1)\n", encoding="utf-8")
            (sb / "checks" / "c01.out").write_text("1\n", encoding="utf-8")
            buf_g = io.StringIO()
            with contextlib.redirect_stdout(buf_g):
                got_g = collect(root, "t1", repo / "receipt")
            ok("ignored by the destination repository" in buf_g.getvalue() and ".out" in buf_g.getvalue(), buf_g.getvalue())
            ok([p.name for p in git_ignored(repo / "receipt", got_g)] == ["c01.out"])
            buf_n = io.StringIO()
            with contextlib.redirect_stdout(buf_n):
                collect(root, "t1", Path(td) / "dest-nogit")
            ok("ignored by the destination" not in buf_n.getvalue(), "no warning outside a work tree")
        # what the reviewer writes outside the rule places, deeper, and in code other than .py, with third-party trees
        # and the literature of a PDF-named working directory (the cases of a measured trial sandbox)
        sb6 = create(root, "t6", spec, [inc])
        files = {"REVIEW-RESULTS.md": "ok", "analysis.py": "print(3)", "RESULTS.md": "x", "stage1-blind.md": "x",
                 "tools/fit.py": "print(4)", "work/deep/run.jl": "x", "scratch/sub/deeper/deep.py": "print(5)",
                 "checks/run.sh": "echo hi", "scratch/calc.wl": "x", "checks/numerics/nb.ipynb": "{}",
                 "scratch/model.jl": "x", "checks/numerics/verify.nb": "x", "scratch/sym.m": "x",
                 "scratch/2401.00001.pdf": "pdf", "scratch/2401.00001/eq12_check.py": "print(6)",
                 "scratch/2401.00001-rederive/derivation.tex": "x", "scratch/2401.00001-notes.tex": "x",
                 "scratch/2401.00001_out.txt": "x", "scratch/2401.00001_check.py": "x", "scratch/2401.00001_check.wl": "x",
                 "scratch/venv/lib/site.py": "x", "scratch/venv/bin/python": "x", "checks/__pycache__/c.cpython-312.pyc": "x",
                 "work/node_modules/m/index.js": "x", "fetched.pdf": "pdf", "scratch/pyenv1/pyvenv.cfg": "home = x",
                 "scratch/pyenv1/lib/pkg.py": "x"}
        for rel, text in files.items():
            (sb6 / rel).parent.mkdir(parents=True, exist_ok=True)
            (sb6 / rel).write_text(text + "\n", encoding="utf-8")
        (sb6 / "AGENTS.md").write_text("edited\n", encoding="utf-8")   # an input the reviewer changed
        st6 = sandbox_state(root, "t6")
        want_code = {"analysis.py", "tools/fit.py", "work/deep/run.jl", "scratch/sub/deeper/deep.py", "checks/run.sh",
                     "scratch/calc.wl", "checks/numerics/nb.ipynb", "scratch/model.jl", "checks/numerics/verify.nb",
                     "scratch/sym.m", "scratch/2401.00001/eq12_check.py", "scratch/2401.00001_check.py",
                     "scratch/2401.00001_check.wl"}
        ok(set(st6["code"]) == want_code, sorted(set(st6["code"]) ^ want_code))   # every code file, no tree, no literature
        buf6 = io.StringIO()
        with contextlib.redirect_stdout(buf6):
            collect(root, "t6", Path(td) / "dest6")
        out6 = buf6.getvalue()
        d6 = Path(td) / "dest6"
        for rel in ("analysis.py", "RESULTS.md", "stage1-blind.md", "tools/fit.py", "work/deep/run.jl", "AGENTS.md"):
            ok((d6 / OUTSIDE_DIR / rel).exists(), rel)                                   # copied and announced, not refused
        ok("outside the rule places" in out6 and "tools/fit.py" in out6 and "input file(s) changed" in out6, out6)
        for rel in ("scratch/sub/deeper/deep.py", "checks/numerics/verify.nb", "scratch/2401.00001/eq12_check.py",
                    "scratch/2401.00001-rederive/derivation.tex", "scratch/2401.00001-notes.tex",
                    "scratch/2401.00001_check.wl"):
            ok((d6 / rel).exists(), rel)                                                 # the reviewer's work survives the name
        for rel in ("scratch/2401.00001.pdf", "scratch/2401.00001_out.txt", "scratch/venv/lib/site.py", "scratch/pyenv1/lib/pkg.py",
                    "checks/__pycache__/c.cpython-312.pyc", f"{OUTSIDE_DIR}/work/node_modules/m/index.js",
                    f"{OUTSIDE_DIR}/fetched.pdf", f"{OUTSIDE_DIR}/CLAUDE.md", f"{OUTSIDE_DIR}/paper.pdf", "paper.pdf"):
            ok(not (d6 / rel).exists(), rel)                                             # literature, trees, unchanged inputs
        ok("scratch/venv (2)" in out6 and "named like literature" in out6 and "scratch/2401.00001/" in out6, out6)
        ok(sandbox_state(root, "t6")["state"] == "collected")
        # a sandbox made before the ledger: file times decide the inputs; --find-in counts what reached a tree
        sb7 = create(root, "t7", spec, [inc])
        ledger_path(root, "t7").unlink()
        old = time.time() - 3600
        for n in ("CLAUDE.md", "AGENTS.md", "REVIEW-SPEC.md", "paper.pdf"):
            os.utime(sb7 / n, (old, old))
        (sb7 / "REVIEW-RESULTS.md").write_text("r\n", encoding="utf-8")
        (sb7 / "scratch" / "a.py").write_text("print('a')\n", encoding="utf-8")
        (sb7 / "scratch" / "b.py").write_text("print('b')\n", encoding="utf-8")
        tree = Path(td) / "tree"; tree.mkdir(); (tree / "copy-of-a.py").write_text("print('a')\n", encoding="utf-8")
        st7 = sandbox_state(root, "t7", find_in=tree)
        ok(st7["state"] == "no_ledger" and st7["written"] == 3 and st7["missing_code"] == ["scratch/b.py"], st7)
        ok("no ledger" in state_line(st7) and "code 1" in state_line(st7), state_line(st7))
        # one index serves every sandbox of a run, whatever the sizes of their files (measured: an index built from the
        # first sandbox's sizes reported almost every file of the others as missing)
        sb8 = root / "t8"; (sb8 / "scratch").mkdir(parents=True)
        (sb8 / "CLAUDE.md").write_text("# Isolated referee sandbox\n\nhand-made\n", encoding="utf-8")   # before the script
        os.utime(sb8 / "CLAUDE.md", (old, old))
        (sb8 / "scratch" / "longer_name.py").write_text("print('a much longer line than the others')\n", encoding="utf-8")
        (tree / "copy.py").write_text("print('a much longer line than the others')\n", encoding="utf-8")
        both = {s["slug"]: s for s in status(root, ["t7", "t8"], find_in=tree)}
        ok(both["t8"]["state"] == "no_ledger" and both["t8"]["missing"] == [], both["t8"])
        ok(both["t7"]["missing_code"] == ["scratch/b.py"], both["t7"])
        st8 = sandbox_state(root, "t8", find_in=root / "t8")
        ok(st8["missing"] == ["scratch/longer_name.py"], st8)                 # a file is not its own copy
        (root / "t9").mkdir(); (root / "t9" / "CLAUDE.md").write_text("# Notes\n", encoding="utf-8")
        ok(sandbox_state(root, "t9")["state"] == "not_sealed")
        # close: a discarded run leaves the list until it changes
        close(root, "t7", "trial run")
        ok(sandbox_state(root, "t7")["state"] == "closed")
        (sb7 / "scratch" / "c.py").write_text("print('c')\n", encoding="utf-8")
        ok(sandbox_state(root, "t7")["state"] == "changed_after_close")
        try:
            close(root, "t7", " "); raise AssertionError("close needs a reason")
        except SystemExit as e:
            ok("--reason" in str(e))
        ok({s["slug"] for s in status(root)} >= {"t1", "t6", "t7"} and LEDGER_DIR not in {s["slug"] for s in status(root)})
        ok(all(state_line(s) for s in status(root)))
        # referee copy: .tex includes are stripped in the sandbox (the source is untouched), AGENTS.md for Codex
        tex = Path(td) / "note.tex"
        tex.write_text("% previous round: verdict incorrect, see plans/r.md\n\\section{A} % layout\ntext\n", encoding="utf-8")
        sb2 = create(root, "t2", spec, [tex, inc])
        ok("verdict" not in (sb2 / "note.tex").read_text(encoding="utf-8") and "\\section{A} %" in (sb2 / "note.tex").read_text(encoding="utf-8"))
        ok("verdict" in tex.read_text(encoding="utf-8"), "the source file must not be modified")
        ok((sb2 / "AGENTS.md").read_text(encoding="utf-8") == (sb2 / "CLAUDE.md").read_text(encoding="utf-8"))
        ok(read_ledger(root, "t2")["inputs"]["note.tex"] == _sha256(sb2 / "note.tex"), "the ledger hashes the stripped copy")
        sb3 = create(root, "t3", spec, [tex], keep_comments=True)
        ok("verdict" in (sb3 / "note.tex").read_text(encoding="utf-8"))
        bib = Path(td) / "refs.bib"
        bib.write_text("% added after the referee asked (plans/r.md)\n@article{k,\n  title = \"{A 93\\% result}\",\n}\n", encoding="utf-8")
        sb3b = create(root, "t3b", spec, [bib])
        got_bib = (sb3b / "refs.bib").read_text(encoding="utf-8")
        ok("referee" not in got_bib and "93\\% result" in got_bib, "the .bib comment lines are stripped, entries kept")
        md = Path(td) / "note.md"; md.write_text("text\n<!-- reviewer verdict: reject -->\n", encoding="utf-8")
        try:
            create(root, "t4", spec, [md]); raise AssertionError("should refuse an include that still carries comments")
        except SystemExit as e:
            ok("referee copy" in str(e) and "reject" not in str(e))
        ok(read_ledger(root, "t4") is None, "a refused create writes no ledger")
        dx = Path(td) / "deixis.tex"; dx.write_text("\\section{B}\nThe present version retains form A and has dropped form B.\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sb5 = create(root, "t5", spec, [dx])
        ok((sb5 / "deixis.tex").exists() and "not refused" in buf.getvalue(), "a warning is shown, not a refusal")
        ok("the spec wins" in CLAUDE_MD)
        rule4 = next(line for line in CLAUDE_MD.splitlines() if line.startswith("4. "))
        ok("`/tmp`" in rule4 and "`$TMPDIR`" in rule4 and "scratchpad" in rule4, "temporary files stay in the sandbox")
        rule7 = next(line for line in CLAUDE_MD.splitlines() if line.startswith("7. "))
        ok("heredoc" in rule7 and "`./checks/`" in rule7, "computations run from files")
    print(f"selftest OK ({n_checks} checks)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", nargs="?", choices=["create", "collect", "status", "close"])
    ap.add_argument("slug", nargs="*")
    ap.add_argument("--spec", type=Path)
    ap.add_argument("--include", type=Path, nargs="*", default=[])
    ap.add_argument("--into", type=Path)
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--keep-comments", action="store_true",
                    help="create: copy .tex / .md includes as they are (a non-blind pass); the default strips and checks them")
    ap.add_argument("--include-literature", action="store_true",
                    help="collect: also copy the literature downloaded into scratch/ (PDF / e-print / their text extracts)")
    ap.add_argument("--find-in", type=Path, help="status: for a sandbox without a ledger, count the reviewer's files"
                    " whose content is nowhere under this tree")
    ap.add_argument("--json", action="store_true", help="status: one JSON list")
    ap.add_argument("--reason", default="", help="close: why the sandbox will not be collected")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    one = a.slug[0] if len(a.slug) == 1 else None
    if a.mode == "create":
        if not (one and a.spec):
            ap.error("create needs one <slug> --spec SPEC.md")
        sb = create(a.root, one, a.spec, a.include, keep_comments=a.keep_comments)
        print(f"✓ sandbox: {sb}")
        print("spawn hint: cwd を上の dir に pin し、prompt は「REVIEW-SPEC.md を読んで実行。token = <TOKEN>」だけ。")
        print("receipt: make-review-sandbox.py collect", one, "--into <campaign dir>  → 汚染 grep → 独立再実装 → ledger 記入 → HANDOFF.md を読んで hoist station")
        return 0
    if a.mode == "collect":
        if not (one and a.into):
            ap.error("collect needs one <slug> --into DEST_DIR")
        got = collect(a.root, one, a.into, include_literature=a.include_literature)
        for g in got:
            print(f"✓ copied {g}")
        print("次: 禁止 source の語彙で汚染 grep → 主要 finding を別 script で独立再実装 → novel_to_requester / second_eye 記入")
        return 0
    if a.mode == "status":
        rows = status(a.root, a.slug or None, a.find_in)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for st in rows:
                print(state_line(st))
            if not rows:
                print(f"(no sandbox under {a.root})")
        return 0
    if a.mode == "close":
        if not one:
            ap.error("close needs one <slug> --reason TEXT")
        print(f"✓ closed {one}: recorded in {close(a.root, one, a.reason)}")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
