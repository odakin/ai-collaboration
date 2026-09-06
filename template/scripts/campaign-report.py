#!/usr/bin/env python3
"""Shim → layer-1 `verification-campaign-report.py`, root pinned to this repo so it works from any cwd.
Usage: `campaign-report.py <campaign-dir> [--run] [--write]` / `--carryover [--write]` / `--index [--write]` / `--surface` / `--selftest`."""
import subprocess
import sys

from _layer1 import REPO, tool

if __name__ == "__main__":
    argv = sys.argv[1:]
    extra = [] if ("--selftest" in argv or "--root" in argv) else ["--root", str(REPO)]
    sys.exit(subprocess.call([sys.executable, str(tool("verification-campaign-report.py")), *argv, *extra]))
