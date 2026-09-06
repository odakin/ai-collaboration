#!/usr/bin/env python3
"""Shim → layer-1 `ledger-commit-cadence-gate.py` with this repo's defaults:
ledger glob `campaigns/*/ledger.yaml`, at most 3 entries per commit, escape env `CAMPAIGN_BATCH_OK`,
log `hygiene.txt`. The gate logic and its selftest live in layer 1."""
import subprocess
import sys

from _layer1 import REPO, tool

DEFAULTS = ["--repo", str(REPO), "--glob", "campaigns/*/ledger.yaml", "--max", "3",
            "--escape-env", "CAMPAIGN_BATCH_OK", "--log-name", "hygiene.txt"]

if __name__ == "__main__":
    argv = sys.argv[1:]
    extra = [] if "--selftest" in argv else DEFAULTS
    sys.exit(subprocess.call([sys.executable, str(tool("ledger-commit-cadence-gate.py")), *argv, *extra]))
