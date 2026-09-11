#!/usr/bin/env python3
"""Sign-carrying printed claims: external-anchor coverage, end-to-end foil teeth, fleet-invariance scan, un-carried convention deferrals.

Why (2026-09).  A paper's check fleet -- Ward-Takahashi-type identities, ratios, channel
decompositions, calibrations that use the same diagram-to-effective-action dictionary on both
sides, and a Euclidean cross-check declared to have "the same sign" -- passed with the overall
sign of a loop-induced effective action reversed.  Every one of those checks is invariant under
Gamma -> -Gamma; only an external absolute quantity (a textbook one-loop vacuum-energy pole)
broke the invariance.  A check fleet is blind to every transformation under which all of its
checks still pass: the global sign, the overall normalization, a factor i, the orientation of
the Levi-Civita symbol, the epsilon convention of dimensional regularization.  This script
makes that blindness testable.  Rules: claude-config conventions/paper-audit.md
#absolute-sign-external-anchor and #convention-difference-closure; ai-collaboration
conventions/physics-verification-cycle.md #foil-negative-control.

A project keeps a JSON registry (default ./sign-anchors.json; relative paths resolve against
the registry's own directory; unknown keys are ignored, so "note" / "about" fields are free):

  {"schema": "sign-anchors/1",
   "manuscript": "path/to/paper.tex",          # the input that the foils transform
   "copy": ["*.py", "scripts/*.py"],            # copied into scratch trees; the rest is symlinked
   "claims": [
     {"id": "...", "quantity": "<what the sign means physically>",
      "invariances": ["global-sign"],           # transformations the anchor must break
      "anchors": [
        {"audit": "audit_x.py", "args": ["{manuscript}"],
         "external": "<the external absolute quantity the audit compares with>",
         "foils": [
           {"id": "...", "invariance": "global-sign", "kind": "revision",
            "git_dir": "path/to/manuscript/repo", "rev": "abc1234", "file": "paper.tex"},
           {"id": "...", "invariance": "global-sign", "kind": "file", "path": "fixtures/flip.tex"},
           {"id": "...", "invariance": "global-sign", "kind": "substitution",
            "subs": [{"literal": "=J_3", "replace": "=-J_3", "count": 1},
                     {"regex": "(?<=x)y", "replace": "z", "count": 1}]}]}]}],
   "fleet": ["audit_*.py"],                     # --fleet-scan only
   "deferrals": {"paths": ["DESIGN.md", "notes/*.tex"], "exclude": ["^notes/\\\\d{4}-"],
                 "patterns": ["(?i)convention tracking"], "carrier": "carrier:|audit_\\\\w+\\\\.py",
                 "baseline": [{"file": "DESIGN.md", "contains": "<unique substring>",
                               "status": "open", "note": "<why it is still open / who closes it>"}]}}

Substitutions replace each match by `replace` VERBATIM (no group references: LaTeX is full of
backslashes); keep context with lookarounds or with a longer literal.  Each must match exactly
`count` times (default 1): a drifted manuscript makes the foil a finding, never a silent no-op.

Modes (combine freely; default = static only):
  (static)      every claim declares >= 1 invariance and >= 1 anchor; every anchor names an
                existing audit and its external quantity; every declared invariance is covered
                by >= 1 foil; foils are well formed (revision resolvable, fixture present).
  --run         every anchor PASSES on the current manuscript (exit 0) and FAILS on every foiled
                manuscript by an assertion: an exit != 0 accompanied by a Python traceback is a
                crash, not teeth.  A foil that leaves the manuscript unchanged is a finding.
  --fleet-scan  for every foil, run every `fleet` script on the current and on the foiled
                manuscript and tabulate which scripts can tell them apart (the answer to "which
                of our checks are blind to this transformation?").  Scripts that fail on the
                current manuscript are findings.
  --deferrals   every line in `paths` matching a `pattern` (sign / convention deferral wording)
                must carry a carrier on the same line (`carrier` regex) or be baselined; open
                baseline items are listed on every run; a baseline entry that no longer matches
                any scanned line is stale (finding).
  --selftest    builds throwaway repositories and asserts every verdict above, including the
                negative cases (blind anchor, crash, drifted and no-op substitutions, uncovered
                invariance, missing external, failing baseline, un-carried deferral, stale
                baseline, unreadable registry).

Scratch trees: top-level entries are symlinked, `copy` globs (a name pattern at the top level or
"dir/pattern" one level down) are copied, directories on the manuscript's path are mirrored as
real directories, and the manuscript is written there -- so an audit that finds the manuscript
from its own __file__ reads the foiled text, and nothing is ever written through a symlink into
the real tree.  Audits that WRITE files into symlinked directories would write into the real
tree; the scratch runs are meant for read-only audits.  `{manuscript}` in `args` expands to the
manuscript's path inside the tree being run.

Exit 0 = no finding, 1 = findings, 2 = the registry cannot be read.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import fnmatch
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCHEMA = "sign-anchors/1"
KINDS = ("revision", "file", "substitution")
TRACEBACK = "Traceback (most recent call last)"
TEXT_SUFFIXES = {".md", ".tex", ".py", ".txt", ".rst", ".sh"}
DEFAULT_TIMEOUT = 300.0


class RegistryError(Exception):
    """The registry cannot be used at all (exit 2)."""


# --------------------------------------------------------------------------- registry
def load_registry(path):
    p = Path(path)
    if not p.is_file():
        raise RegistryError(f"registry not found: {p}")
    try:
        reg = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"registry is not valid JSON ({p}): {exc}")
    if not isinstance(reg, dict) or reg.get("schema") != SCHEMA:
        raise RegistryError(f"{p}: 'schema' must be {SCHEMA!r}")
    return reg, p.resolve().parent


def claims_of(reg):
    c = reg.get("claims")
    return c if isinstance(c, list) else []


def iter_foils(reg):
    for c in claims_of(reg):
        for a in c.get("anchors") or []:
            for fo in a.get("foils") or []:
                yield c, a, fo


def run_git(args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True)
    except OSError:
        return None


# --------------------------------------------------------------------------- static
def foil_form(fo, root, tag):
    kind = fo.get("kind")
    if kind not in KINDS:
        return [f"{tag}: 'kind' must be one of {', '.join(KINDS)}"]
    if kind == "revision":
        rev, fil = fo.get("rev"), fo.get("file")
        if not rev or not fil:
            return [f"{tag}: a revision foil needs 'rev' and 'file'"]
        r = run_git(["-C", str(root / fo.get("git_dir", ".")), "cat-file", "-e", f"{rev}:{fil}"])
        if r is None:
            return [f"{tag}: git is not available"]
        if r.returncode != 0:
            return [f"{tag}: {rev}:{fil} not found in {fo.get('git_dir', '.')}"]
        return []
    if kind == "file":
        if not fo.get("path") or not (root / fo["path"]).is_file():
            return [f"{tag}: fixture file not found: {fo.get('path')!r}"]
        return []
    subs = fo.get("subs")
    if not isinstance(subs, list) or not subs:
        return [f"{tag}: a substitution foil needs a non-empty 'subs' list"]
    out = []
    for i, s in enumerate(subs):
        if ("literal" in s) == ("regex" in s):
            out.append(f"{tag}: subs[{i}] needs exactly one of 'literal' / 'regex'")
        if "replace" not in s:
            out.append(f"{tag}: subs[{i}] has no 'replace'")
        if "regex" in s:
            try:
                re.compile(s["regex"])
            except re.error as exc:
                out.append(f"{tag}: subs[{i}] bad regex: {exc}")
    return out


def static_findings(reg, root):
    out = []
    man = reg.get("manuscript")
    if not man or not (root / man).is_file():
        out.append(f"manuscript not found: {man!r}")
    claims = claims_of(reg)
    if not claims:
        return out + ["no claims registered (an empty registry certifies nothing)"]
    ids = set()
    for c in claims:
        cid = c.get("id") or "<no id>"
        if cid in ids:
            out.append(f"{cid}: duplicate claim id")
        ids.add(cid)
        if not str(c.get("quantity", "")).strip():
            out.append(f"{cid}: 'quantity' is empty (say what the sign means physically)")
        inv = c.get("invariances") or []
        if not inv:
            out.append(f"{cid}: no invariance declared (which transformation must the anchor break?)")
        anchors = c.get("anchors") or []
        if not anchors:
            out.append(f"{cid}: no anchor")
        covered = set()
        for a in anchors:
            aud = a.get("audit") or "<no audit>"
            tag = f"{cid}/{aud}"
            if not (root / aud).is_file():
                out.append(f"{tag}: audit script not found")
            if not str(a.get("external", "")).strip():
                out.append(f"{tag}: 'external' is empty (a consistency check is not an external anchor)")
            for fo in a.get("foils") or []:
                ftag = f"{tag}/{fo.get('id') or '<no id>'}"
                if fo.get("invariance") in inv:
                    covered.add(fo["invariance"])
                else:
                    out.append(f"{ftag}: invariance {fo.get('invariance')!r} is not declared by the claim")
                out.extend(foil_form(fo, root, ftag))
        for i in inv:
            if i not in covered:
                out.append(f"{cid}: invariance {i!r} has no foil (the anchor's teeth against it are untested)")
    return out


# --------------------------------------------------------------------------- foils and trees
def foiled_text(fo, root, current):
    """Return (text, problem); exactly one of them is None."""
    kind = fo.get("kind")
    if kind == "revision":
        r = run_git(["-C", str(root / fo.get("git_dir", ".")), "show", f"{fo.get('rev')}:{fo.get('file')}"])
        if r is None or r.returncode != 0:
            return None, f"git show {fo.get('rev')}:{fo.get('file')} failed in {fo.get('git_dir', '.')}"
        text = r.stdout
    elif kind == "file":
        fp = root / (fo.get("path") or "")
        if not fp.is_file():
            return None, f"fixture not found: {fo.get('path')!r}"
        text = fp.read_text(encoding="utf-8")
    elif kind == "substitution":
        text = current
        for s in fo.get("subs") or []:
            pattern = re.escape(s["literal"]) if "literal" in s else s.get("regex", "")
            shown = s.get("literal", s.get("regex"))
            want = int(s.get("count", 1))
            repl = s.get("replace", "")
            text, n = re.subn(pattern, lambda _m, _r=repl: _r, text)
            if n != want:
                return None, (f"substitution {shown!r} matched {n} time(s), registered {want} "
                              f"(the manuscript drifted: update the foil)")
    else:
        return None, f"unknown foil kind {kind!r}"
    if text == current:
        return None, "the foiled manuscript is identical to the current one (a no-op foil proves nothing)"
    return text, None


def build_tree(root, manuscript, text, copy_globs, dest):
    """Scratch tree under `dest` (see the module docstring)."""
    man = Path(manuscript)
    mirror = {Path(*man.parts[:i]) for i in range(1, len(man.parts))}
    for g in copy_globs:
        gp = Path(g)
        if len(gp.parts) > 1:
            mirror.add(Path(*gp.parts[:-1]))

    def walk(rel):
        src = root / rel
        (dest / rel).mkdir(parents=True, exist_ok=True)
        for name in sorted(os.listdir(src)):
            if rel == Path(".") and name == ".git":
                continue
            r = rel / name
            if r == man:
                continue
            s = src / name
            if r in mirror and s.is_dir():
                walk(r)
            elif s.is_file() and any(fnmatch.fnmatchcase(r.as_posix(), g) for g in copy_globs):
                shutil.copy2(s, dest / r)
            else:
                os.symlink(s, dest / r)

    walk(Path("."))
    target = dest / man
    p = target.parent
    while p != dest and dest in p.parents:
        if p.is_symlink():
            raise RuntimeError(f"refusing to write the manuscript through a symlink: {p}")
        p = p.parent
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return dest


def run_script(script, args, cwd, timeout):
    try:
        p = subprocess.run([sys.executable, script, *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT after {timeout:g} s"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def classify(rc, out):
    if rc is None:
        return "timeout"
    if rc == 0:
        return "blind"
    return "crash" if TRACEBACK in (out or "") else "detected"


def expand(args, manuscript_path):
    return [str(x).replace("{manuscript}", str(manuscript_path)) for x in (args or [])]


def tail(out, n=4):
    lines = [ln for ln in (out or "").strip().splitlines() if ln.strip()]
    return "\n".join("        | " + ln[:160] for ln in lines[-n:])


# --------------------------------------------------------------------------- --run
def run_anchors(reg, root, timeout, log):
    findings = []
    man = reg.get("manuscript") or ""
    mpath = root / man
    if not man or not mpath.is_file():
        return [f"--run: manuscript not found: {man!r}"]
    current = mpath.read_text(encoding="utf-8")
    copy_globs = reg.get("copy") or ["*.py"]
    for c in claims_of(reg):
        for a in c.get("anchors") or []:
            aud = a.get("audit") or ""
            tag = f"{c.get('id')}/{aud}"
            if not aud or not (root / aud).is_file():
                continue  # already a static finding
            rc, out = run_script(aud, expand(a.get("args"), mpath), root, timeout)
            if rc != 0:
                findings.append(f"{tag}: does not PASS on the current manuscript "
                                f"({'exit ' + str(rc) if rc is not None else out}); its foils were not run")
                log(tail(out))
                continue
            log(f"  [PASS ] {tag} on the current manuscript")
            for fo in a.get("foils") or []:
                ftag = f"{tag}/{fo.get('id')} [{fo.get('invariance')}]"
                text, problem = foiled_text(fo, root, current)
                if problem:
                    findings.append(f"{ftag}: {problem}")
                    continue
                with tempfile.TemporaryDirectory(prefix="sign-anchor-") as td:
                    tree = build_tree(root, man, text, copy_globs, Path(td))
                    rc2, out2 = run_script(aud, expand(a.get("args"), tree / man), tree, timeout)
                verdict = classify(rc2, out2)
                if verdict == "detected":
                    log(f"  [TEETH] {ftag}: the anchor fails on the foiled manuscript")
                    continue
                findings.append(f"{ftag}: " + {
                    "blind": "the anchor PASSES on the foiled manuscript (it is blind to this transformation)",
                    "crash": "the anchor crashed on the foiled manuscript (a traceback is not teeth; "
                             "make the parse fail by an assertion)",
                    "timeout": "the anchor timed out on the foiled manuscript"}[verdict])
                log(tail(out2))
    return findings


# --------------------------------------------------------------------------- --fleet-scan
def fleet_scan(reg, root, timeout, jobs, log):
    scripts = sorted({os.path.relpath(p, root) for g in (reg.get("fleet") or [])
                      for p in glob.glob(str(root / g)) if p.endswith(".py")})
    if not scripts:
        return ["--fleet-scan: no script matches the 'fleet' globs"], []
    man = reg.get("manuscript") or ""
    if not man or not (root / man).is_file():
        return [f"--fleet-scan: manuscript not found: {man!r}"], []
    current = (root / man).read_text(encoding="utf-8")
    copy_globs = reg.get("copy") or ["*.py"]
    findings, rows = [], []
    with tempfile.TemporaryDirectory(prefix="sign-anchor-fleet-") as td:
        trees = {"<current>": build_tree(root, man, current, copy_globs, Path(td) / "current")}
        for _c, _a, fo in iter_foils(reg):
            fid = fo.get("id") or "<no id>"
            if fid in trees:
                continue
            text, problem = foiled_text(fo, root, current)
            if problem:
                findings.append(f"--fleet-scan/{fid}: {problem}")
                continue
            trees[fid] = build_tree(root, man, text, copy_globs, Path(td) / f"foil-{len(trees)}")
        pairs = [(s, k) for s in scripts for k in trees]
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            futures = {(s, k): ex.submit(run_script, s, [], trees[k], timeout) for s, k in pairs}
            results = {key: fut.result() for key, fut in futures.items()}
    foil_ids = [k for k in trees if k != "<current>"]
    for s in scripts:
        rc, out = results[(s, "<current>")]
        row = {"script": s, "current": "PASS" if rc == 0 else classify(rc, out).replace("detected", "FAIL")}
        for fid in foil_ids:
            if rc != 0:
                row[fid] = "n/a"
                continue
            v = classify(*results[(s, fid)])
            row[fid] = {"detected": "sees", "blind": "blind"}.get(v, v)
        rows.append(row)
        if rc != 0:
            findings.append(f"--fleet-scan: {s} does not PASS on the current manuscript ({row['current']})")
            log(tail(out))
    width = max(len(s) for s in scripts)
    log("  " + "script".ljust(width) + "  current  " + "  ".join(foil_ids))
    for row in rows:
        log("  " + row["script"].ljust(width) + f"  {row['current']:7s}  " +
            "  ".join(row[f].ljust(len(f)) for f in foil_ids))
    for fid in foil_ids:
        sees = [r["script"] for r in rows if r[fid] == "sees"]
        log(f"  -> {fid}: {len(sees)} of {len(rows)} scripts see it" + (f": {', '.join(sees)}" if sees else ""))
    return findings, rows


# --------------------------------------------------------------------------- --deferrals
def deferral_scan(reg, root):
    d = reg.get("deferrals")
    if not isinstance(d, dict):
        return ["--deferrals: the registry has no 'deferrals' section"], [], 0
    try:
        pats = [re.compile(p) for p in d.get("patterns") or []]
        carrier = re.compile(d["carrier"]) if d.get("carrier") else None
        excl = [re.compile(x) for x in d.get("exclude") or []]
    except re.error as exc:
        return [f"--deferrals: bad regex: {exc}"], [], 0
    if not pats:
        return ["--deferrals: no 'patterns'"], [], 0
    files = {}
    for spec in d.get("paths") or []:
        for hit in glob.glob(str(root / spec), recursive=True):
            hp = Path(hit)
            cands = [q for q in hp.rglob("*") if q.is_file()] if hp.is_dir() else [hp]
            for q in cands:
                rel = os.path.relpath(q, root).replace(os.sep, "/")
                if q.suffix in TEXT_SUFFIXES and not any(x.search(rel) for x in excl):
                    files[rel] = q
    baseline = d.get("baseline") or []
    used = [False] * len(baseline)
    findings, open_items, carried = [], [], 0
    for rel in sorted(files):
        try:
            lines = files[rel].read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            findings.append(f"{rel}: unreadable ({exc})")
            continue
        for ln, line in enumerate(lines, 1):
            if not any(p.search(line) for p in pats):
                continue
            if carrier is not None and carrier.search(line):
                carried += 1
                continue
            hit = next((i for i, b in enumerate(baseline)
                        if b.get("file") == rel and b.get("contains") and b["contains"] in line), None)
            if hit is None:
                findings.append(f"{rel}:{ln}: un-carried sign/convention deferral: {line.strip()[:150]}")
                continue
            used[hit] = True
            if baseline[hit].get("status", "open") == "open":
                open_items.append(f"{rel}:{ln}: {baseline[hit].get('note', '')}")
    for i, b in enumerate(baseline):
        if not used[i]:
            findings.append(f"stale baseline entry (matches no scanned line): {b.get('file')}: {b.get('contains')!r}")
    return findings, open_items, carried


# --------------------------------------------------------------------------- driver
def evaluate(registry, run=False, fleet=False, deferrals=False, timeout=DEFAULT_TIMEOUT, jobs=4,
             log=print):
    reg, root = load_registry(registry)
    res = {"static": static_findings(reg, root), "run": [], "fleet": [], "fleet_rows": [],
           "deferrals": [], "open": [], "carried": 0}
    if run:
        log("--run: each anchor on the current manuscript, then on every foil")
        res["run"] = run_anchors(reg, root, timeout, log)
    if fleet:
        log("--fleet-scan: which fleet scripts can tell each foil from the current manuscript")
        res["fleet"], res["fleet_rows"] = fleet_scan(reg, root, timeout, jobs, log)
    if deferrals:
        res["deferrals"], res["open"], res["carried"] = deferral_scan(reg, root)
        log(f"--deferrals: {res['carried']} carried line(s), {len(res['open'])} open baseline item(s), "
            f"{len(res['deferrals'])} finding(s)")
        for item in res["open"]:
            log(f"  [OPEN ] {item}")
    res["findings"] = res["static"] + res["run"] + res["fleet"] + res["deferrals"]
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 epilog="See the module docstring for the registry schema.")
    ap.add_argument("--registry", default="sign-anchors.json", help="JSON registry (default ./sign-anchors.json)")
    ap.add_argument("--run", action="store_true", help="run anchors on the current and on every foiled manuscript")
    ap.add_argument("--fleet-scan", action="store_true", help="tabulate which fleet scripts see each foil")
    ap.add_argument("--deferrals", action="store_true", help="un-carried sign/convention deferral ratchet")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="per-script timeout in seconds")
    ap.add_argument("-j", "--jobs", type=int, default=4, help="parallel scripts in --fleet-scan")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    try:
        res = evaluate(a.registry, a.run, a.fleet_scan, a.deferrals, a.timeout, a.jobs)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if res["findings"]:
        print(f"FINDINGS ({len(res['findings'])}):")
        for f in res["findings"]:
            print(f"  x {f}")
        return 1
    done = ["static"] + [m for m, on in (("run", a.run), ("fleet-scan", a.fleet_scan),
                                         ("deferrals", a.deferrals)) if on]
    print(f"no finding ({', '.join(done)})")
    return 0


# --------------------------------------------------------------------------- selftest
_HEAD = '''import os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "paper", "paper.tex")
t = open(path, encoding="utf-8").read()
'''
AUD_ANCHOR = _HEAD + '''sd = 1 if "Gamma = +J" in t else -1
sp = -1 if "prefactor = -1" in t else 1
ok = sd * sp == -1 and sd == 1      # sd == 1 plays the external (textbook) statement
print("[PASS] anchored" if ok else "[FAIL] external anchor violated")
sys.exit(0 if ok else 1)
'''
AUD_BLIND = _HEAD + '''sd = 1 if "Gamma = +J" in t else -1
sp = -1 if "prefactor = -1" in t else 1
ok = sd * sp == -1                   # internal consistency only: invariant under the global flip
print("[PASS]" if ok else "[FAIL]")
sys.exit(0 if ok else 1)
'''
AUD_CRASH = _HEAD + '''re.search(r"Gamma = [+]J", t).group(0)   # AttributeError on the flipped text
print("[PASS]")
'''
RIGHT = "Gamma = +J\nprefactor = -1\n"
WRONG = "Gamma = -J\nprefactor = +1\n"


def _git_fixture(repo, texts):
    env = dict(os.environ, GIT_AUTHOR_NAME="selftest", GIT_AUTHOR_EMAIL="selftest",
               GIT_COMMITTER_NAME="selftest", GIT_COMMITTER_EMAIL="selftest")
    base = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
            "-c", "user.useConfigOnly=false", "-c", "init.defaultBranch=main"]
    try:
        subprocess.run(base + ["init", "-q"], cwd=repo, env=env, check=True, capture_output=True)
        revs = []
        for t in texts:
            (repo / "paper.tex").write_text(t, encoding="utf-8")
            subprocess.run(base + ["add", "paper.tex"], cwd=repo, env=env, check=True, capture_output=True)
            subprocess.run(base + ["commit", "-q", "-m", "fixture"], cwd=repo, env=env, check=True,
                           capture_output=True)
            revs.append(subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                                       text=True, check=True).stdout.strip())
        return revs[0]
    except (OSError, subprocess.CalledProcessError):
        return None


def selftest():
    failed = []

    def expect(name, cond, detail=""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   <- {detail}" if detail and not cond else ""))
        if not cond:
            failed.append(name)

    quiet = lambda _s: None  # noqa: E731
    with tempfile.TemporaryDirectory(prefix="sign-anchors-selftest-") as td:
        root = Path(td) / "proj"
        for sub in ("paper", "fixtures", "notes"):
            (root / sub).mkdir(parents=True)
        (root / "paper" / "paper.tex").write_text(RIGHT, encoding="utf-8")
        (root / "fixtures" / "wrong.tex").write_text(WRONG, encoding="utf-8")
        (root / "audit_anchor.py").write_text(AUD_ANCHOR, encoding="utf-8")
        (root / "audit_blind.py").write_text(AUD_BLIND, encoding="utf-8")
        (root / "audit_crash.py").write_text(AUD_CRASH, encoding="utf-8")
        (root / "DESIGN.md").write_text(
            "- the absolute sign needs convention tracking (carrier: TODO-7)\n"
            "- sign vs textbook: convention tracking later\n", encoding="utf-8")
        (root / "notes" / "2026-01-01-old.md").write_text("convention tracking in a dated snapshot\n",
                                                          encoding="utf-8")
        rev = _git_fixture(root / "paper", [WRONG, RIGHT])
        foils = [
            {"id": "flip", "invariance": "global-sign", "kind": "substitution",
             "subs": [{"literal": "Gamma = +J", "replace": "Gamma = -J"},
                      {"regex": r"(?<=prefactor = )-1", "replace": "+1"}]},
            {"id": "fixture", "invariance": "global-sign", "kind": "file", "path": "fixtures/wrong.tex"}]
        if rev:
            foils.append({"id": "old", "invariance": "global-sign", "kind": "revision",
                          "git_dir": "paper", "rev": rev, "file": "paper.tex"})
        else:
            print("  [SKIP] revision foil: git unavailable or the fixture commit failed")
        good = {"schema": SCHEMA, "manuscript": "paper/paper.tex", "copy": ["*.py"],
                "claims": [{"id": "sign", "quantity": "overall sign", "invariances": ["global-sign"],
                            "anchors": [{"audit": "audit_anchor.py", "args": ["{manuscript}"],
                                         "external": "textbook sign", "foils": foils}]}],
                "fleet": ["audit_*.py"],
                "deferrals": {"paths": ["DESIGN.md", "notes/*.md"], "exclude": [r"^notes/\d{4}-"],
                              "patterns": ["(?i)convention tracking"], "carrier": "carrier:",
                              "baseline": []}}

        def write(name, mutate=None):
            r = copy.deepcopy(good)
            if mutate:
                mutate(r)
            p = root / f"{name}.json"
            p.write_text(json.dumps(r, indent=1), encoding="utf-8")
            return p

        def anchor(r):
            return r["claims"][0]["anchors"][0]

        nfo = len(foils)
        res = evaluate(write("good"), run=True, deferrals=True, log=quiet)
        expect("good registry: no static finding", res["static"] == [], res["static"])
        expect(f"good registry: anchor passes and all {nfo} foils are detected", res["run"] == [], res["run"])
        expect("deferrals: one un-carried line found, the carried one and the dated note are not",
               len(res["deferrals"]) == 1 and "later" in res["deferrals"][0] and res["carried"] == 1,
               res["deferrals"])

        def baselined(r):
            r["deferrals"]["baseline"] = [{"file": "DESIGN.md", "contains": "tracking later",
                                           "status": "open", "note": "owner closes"}]
        res = evaluate(write("baselined", baselined), deferrals=True, log=quiet)
        expect("baselined deferral: no finding, listed as open", res["deferrals"] == [] and len(res["open"]) == 1,
               (res["deferrals"], res["open"]))

        def stale(r):
            baselined(r)
            r["deferrals"]["baseline"].append({"file": "DESIGN.md", "contains": "no such line", "status": "open"})
        res = evaluate(write("stale", stale), deferrals=True, log=quiet)
        expect("stale baseline entry is a finding", any("stale" in f for f in res["deferrals"]), res["deferrals"])

        res = evaluate(write("blind", lambda r: anchor(r).update(audit="audit_blind.py")), run=True, log=quiet)
        expect(f"blind anchor: all {nfo} foils reported as not detected",
               len(res["run"]) == nfo and all("PASSES on the foiled" in f for f in res["run"]), res["run"])
        res = evaluate(write("crash", lambda r: anchor(r).update(audit="audit_crash.py")), run=True, log=quiet)
        expect("crashing anchor: a traceback is not counted as teeth",
               len(res["run"]) == nfo and all("crashed" in f for f in res["run"]), res["run"])
        res = evaluate(write("noext", lambda r: anchor(r).update(external="")), log=quiet)
        expect("missing external quantity is a static finding", any("'external' is empty" in f for f in res["static"]),
               res["static"])
        res = evaluate(write("uncovered", lambda r: r["claims"][0].update(invariances=["global-sign", "normalization"])),
                       log=quiet)
        expect("declared invariance without a foil is a static finding",
               any("'normalization' has no foil" in f for f in res["static"]), res["static"])
        res = evaluate(write("noaudit", lambda r: anchor(r).update(audit="audit_missing.py")), log=quiet)
        expect("missing audit script is a static finding", any("audit script not found" in f for f in res["static"]),
               res["static"])

        def drift(r):
            anchor(r)["foils"] = [copy.deepcopy(foils[0])]
            anchor(r)["foils"][0]["subs"][0]["literal"] = "Gamma = +K"
        res = evaluate(write("drift", drift), run=True, log=quiet)
        expect("drifted substitution (0 matches) is a finding", any("matched 0 time" in f for f in res["run"]), res["run"])

        def noop(r):
            anchor(r)["foils"] = [{"id": "noop", "invariance": "global-sign", "kind": "substitution",
                                   "subs": [{"literal": "Gamma = +J", "replace": "Gamma = +J"}]}]
        res = evaluate(write("noop", noop), run=True, log=quiet)
        expect("no-op substitution is a finding", any("identical" in f for f in res["run"]), res["run"])
        res = evaluate(write("basefail", lambda r: r.update(manuscript="fixtures/wrong.tex")), run=True, log=quiet)
        expect("an anchor failing on the current manuscript is a finding",
               any("does not PASS on the current manuscript" in f for f in res["run"]), res["run"])

        res = evaluate(write("fleet"), fleet=True, log=quiet)
        rows = {r["script"]: r for r in res["fleet_rows"]}
        fids = [f["id"] for f in foils]
        expect("fleet scan: the anchor sees every foil",
               all(rows.get("audit_anchor.py", {}).get(f) == "sees" for f in fids), rows.get("audit_anchor.py"))
        expect("fleet scan: the consistency-only audit is blind to every foil",
               all(rows.get("audit_blind.py", {}).get(f) == "blind" for f in fids), rows.get("audit_blind.py"))
        expect("fleet scan: the crashing audit is reported as crash, not as seeing",
               all(rows.get("audit_crash.py", {}).get(f) == "crash" for f in fids), rows.get("audit_crash.py"))
        expect("fleet scan: no finding when every script passes on the current manuscript", res["fleet"] == [],
               res["fleet"])

        bad = root / "bad.json"
        bad.write_text(json.dumps({"schema": "nope"}), encoding="utf-8")

        def quiet_main(argv):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return main(argv)
        expect("unreadable registry exits 2", quiet_main(["--registry", str(bad)]) == 2)
        expect("main: good registry with --run exits 0",
               quiet_main(["--registry", str(root / "good.json"), "--run"]) == 0)
        expect("main: un-carried deferral exits 1",
               quiet_main(["--registry", str(root / "good.json"), "--deferrals"]) == 1)
        expect("the real manuscript was never overwritten by a foil",
               (root / "paper" / "paper.tex").read_text(encoding="utf-8") == RIGHT)
    print(f"selftest: {'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
