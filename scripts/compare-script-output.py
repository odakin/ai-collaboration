#!/usr/bin/env python3
"""Compare what scripts print at an old git revision and in the working tree, byte for byte after masking timings, to gate a refactor that must change nothing (an engine moved behind a shim); --selftest.

Why: when an engine moves to a shared module, ALL PASS on the new side says less than "the output did not change".
Checks that compute exactly print exact values, so the whole stdout is the stronger gate, and every script that imports
the moved names has to be on the list, not only the ones that were edited.  The old side comes out of git into a temp
dir, so nothing has to be saved before the change and the comparison can be rerun later from the record.

What it does: `git archive <rev>` of the given pathspecs into a temp dir, run each script there and in the working tree
(each with its own root as cwd, stdout and stderr merged), replace the two roots by <root>, apply the masks, compare the
text and the exit code.  Exit 0 only when every script has the same text and exit code and exited 0.

  --link NAME   a directory or file the scripts read that is not in the archive (a nested clone, data): symlinked into
                the old side, so both sides read the same input
  --mask REGEX  extra pattern replaced by <masked> (repeatable).  Default mask = timings such as "[12 s]" and "[0.3 s]".
                Add a mask only after naming the cause of a difference; do not widen it until the difference goes away.
  --files SPEC  git pathspec of what to extract (repeatable, default '*.py')

A file under git-crypt comes out of `git archive` as ciphertext; extract only what is readable.  To see that the
comparison has teeth on the real scripts, run it once with one input broken (for a shim: point the engine's location at
a copy with one sign flipped) and watch it report DIFF.  Procedure: claude-config/conventions/script-layer-placement.md#migration-gate.

Usage
  python3 compare-script-output.py --repo . --rev <old> --link external -- audit_a.py audit_b.py
  python3 compare-script-output.py --selftest
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TIMING = r"\[ *\d+(?:\.\d+)? ?s\]"


def extract(repo: Path, rev: str, specs, dest: Path) -> None:
    archive = subprocess.Popen(["git", "-C", str(repo), "archive", rev, "--", *specs], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", str(dest)], stdin=archive.stdout, check=True)
    archive.stdout.close()
    if archive.wait() != 0:
        raise SystemExit(f"✗ git archive {rev} failed in {repo}")


def run(script: str, root: Path, timeout: int):
    argv = [sys.executable, script] if script.endswith(".py") else [str(root / script)]
    r = subprocess.run(argv, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    return r.returncode, r.stdout


def normalize(text: str, root: Path, masks) -> str:
    for form in {str(root), os.path.realpath(root)}:
        text = text.replace(form, "<root>")
    for m in masks:
        text = re.sub(m, "<masked>", text)
    return text


def compare(repo: Path, rev: str, scripts, links=(), masks=(), specs=("*.py",), timeout=1800) -> int:
    repo = repo.resolve()
    masks = [TIMING, *masks]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp)
        extract(repo, rev, specs, old)
        for name in links:
            os.symlink(repo / name, old / name)
        for s in scripts:
            rc_old, out_old = run(s, old, timeout)
            rc_new, out_new = run(s, repo, timeout)
            a, b = normalize(out_old, old, masks), normalize(out_new, repo, masks)
            last = (out_new.strip().splitlines() or [""])[-1][:60]
            if a == b and rc_old == rc_new == 0:
                print(f"SAME  rc=0  {s}  ({last})")
                continue
            bad += 1
            if a == b and rc_old == rc_new:
                print(f"SAME but both failed  rc={rc_new}  {s}  ({last})")
                continue
            print(f"DIFF  rc={rc_old}->{rc_new}  {s}")
            for line in list(difflib.unified_diff(a.splitlines(), b.splitlines(), "old", "new", lineterm="", n=0))[:14]:
                print("    " + line[:170])
    print(f"{len(scripts) - bad} of {len(scripts)} the same as {rev}")
    return 1 if bad else 0


def selftest() -> int:
    failed: list = []

    def check(label, ok):
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failed.append(label)

    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid", GIT_AUTHOR_DATE="2001-01-01T00:00:00Z",
               GIT_COMMITTER_DATE="2001-01-01T00:00:00Z")

    def git(repo, *a):
        subprocess.run(["git", "-C", str(repo), *a], check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "r"
        repo.mkdir()
        git(repo, "init", "-q")
        (repo / "same.py").write_text('print("value", 2 + 2)\nprint("[0.12 s]")\n')
        (repo / "changed.py").write_text('print("value", 7)\n')
        (repo / "where.py").write_text('import os\nprint(os.getcwd())\n')
        (repo / "broken.py").write_text('print("no")\nraise SystemExit(3)\n')
        (repo / "reads.py").write_text('print(open("input/x.txt").read())\n')
        (repo / "exitcode.py").write_text('print("x")\n')
        (repo / "stamp.py").write_text('print("run 41")\n')
        (repo / "input").mkdir()
        (repo / "input" / "x.txt").write_text("shared\n")
        git(repo, "add", "same.py", "changed.py", "where.py", "broken.py", "reads.py", "exitcode.py", "stamp.py")
        git(repo, "commit", "-q", "-m", "old")
        rev = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        (repo / "same.py").write_text('# a refactor\nx = 2 + 2\nprint("value", x)\nprint("[31.7 s]")\n')
        (repo / "changed.py").write_text('print("value", 8)\n')
        (repo / "exitcode.py").write_text('print("x")\nraise SystemExit(1)\n')
        (repo / "stamp.py").write_text('print("run 42")\n')

        def one(script, **kw):
            return compare(repo, rev, [script], **kw)
        check("a refactor with the same output and a different timing is SAME", one("same.py") == 0)
        check("a changed value is reported", one("changed.py") == 1)
        check("the two roots are not a difference", one("where.py") == 0)
        check("a script that fails on both sides does not pass", one("broken.py") == 1)
        check("a changed exit code with the same text is reported", one("exitcode.py") == 1)
        check("an input outside the archive is shared with --link", one("reads.py", links=["input"]) == 0)
        check("a file left out of the archive fails without --link (foil)", one("reads.py") == 1)
        check("an extra --mask hides only what it names", one("stamp.py", masks=[r"run \d+"]) == 0 and one("stamp.py") == 1)
    print("selftest:", "ALL PASS" if not failed else f"FAILED ({len(failed)})")
    return 0 if not failed else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--rev")
    ap.add_argument("--link", action="append", default=[])
    ap.add_argument("--mask", action="append", default=[])
    ap.add_argument("--files", action="append", default=[])
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("scripts", nargs="*")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.rev or not a.scripts:
        ap.error("--rev and at least one script are required")
    return compare(a.repo, a.rev, a.scripts, a.link, a.mask, a.files or ["*.py"], a.timeout)


if __name__ == "__main__":
    sys.exit(main())
