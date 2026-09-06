#!/usr/bin/env python3
"""Create a private verify-to-learn repo from `template/`: copy the skeleton, `git init`, install the
pre-commit gate, and run the shims' selftests so the layer-1 tools are known to be reachable.

Usage
  init-verification-repo.py <dest-dir> [--no-git]
  init-verification-repo.py --selftest

The skeleton is documented in template/README.md; the cycle it runs is conventions/verification-cycle-ops.md.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "template"


def create(dest: Path, git: bool = True) -> Path:
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"✗ refuse: {dest} exists and is not empty")
    shutil.copytree(TEMPLATE, dest, dirs_exist_ok=True)
    for sub in ("campaigns/retros", "campaigns/QUEUE-specs"):
        (dest / sub).mkdir(parents=True, exist_ok=True)
        (dest / sub / ".gitkeep").write_text("", encoding="utf-8")
    (dest / "SESSION.md").write_text("# SESSION\n\n(created by init-verification-repo.py; keep only resume highlights here — state is derived by campaign-report.py)\n", encoding="utf-8")
    (dest / "DESIGN.md").write_text("# DESIGN\n\nDecisions that cannot be derived from the files (why a campaign was cut this way, what was rejected and why).\n", encoding="utf-8")
    os.chmod(dest / "hooks" / "pre-commit", 0o755)
    os.chmod(dest / "scripts" / "install-hooks.sh", 0o755)
    if git:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=True)
        subprocess.run(["bash", "scripts/install-hooks.sh"], cwd=dest, check=True)
    return dest


def selfcheck(dest: Path) -> None:
    env = dict(os.environ, AI_COLLABORATION_ROOT=str(HERE.parent))
    for shim, args in (("scripts/campaign_hygiene.py", ["--selftest"]), ("scripts/campaign-report.py", ["--selftest"])):
        pr = subprocess.run([sys.executable, str(dest / shim), *args], cwd=dest, capture_output=True, text=True, env=env)
        if pr.returncode != 0:
            raise SystemExit(f"✗ {shim} --selftest failed:\n{pr.stdout}{pr.stderr}")
        print(f"  ✓ {shim}: {(pr.stdout.strip().splitlines() or ['ok'])[-1]}")


def selftest() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = create(Path(td) / "vr", git=False)
        assert (d / "CLAUDE.md").exists() and (d / "campaigns" / "TEMPLATE-spec.md").exists() and (d / "hooks" / "pre-commit").exists()
        selfcheck(d)
        try:
            create(d); raise AssertionError("should refuse non-empty")
        except SystemExit as e:
            assert "refuse" in str(e)
    print("selftest OK (4 checks)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dest", nargs="?")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.dest:
        ap.error("dest is required")
    d = create(Path(a.dest).expanduser().resolve(), git=not a.no_git)
    print(f"✓ created {d}")
    selfcheck(d)
    print("next: read CLAUDE.md, copy campaigns/TEMPLATE-spec.md for your first campaign, keep the repo private.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
