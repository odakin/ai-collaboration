# UNATTENDED-TICK — what a daily unattended run does (and never does)

This is the procedure an unattended session (a scheduled `claude -p` run, a cron job, any headless
agent) follows in a verification repo. It is the **partial** adoption of a fully autonomous loop:
surfacing, indexing and heartbeat are always on; *executing* a queued campaign is behind a kill
switch; the human gates are never crossed (layer-1 `conventions/verification-cycle-ops.md#autonomous-layer`).

**Prime rule**: no irreversible, outward-facing or source-of-truth-changing action. The tick may
write only under `campaigns/` (the campaign dir it expanded, `campaigns/INDEX.md`, `carryover.yaml`)
and its heartbeat file. It never writes to layer-1 conventions or libraries, bibliographic sources
of truth, DESIGN / SESSION, or other repositories; never mails, posts, or contacts authors; stops
(`--status partial`) when there are no grounds.

## Step 0 — sync and kill switch

1. In the verification repo: `git fetch -q`; if the tree is clean and behind, `git pull --ff-only`. If dirty or diverged, do not pull (a human is working) and **skip Step 3**.
2. Read the kill-switch config (suggested file: `verification-cycle-config.yaml` in your private layer): `autorun` (default false), `max_campaigns_per_tick` (1), `default_cap` (items / minutes), `writable_repos`.

## Step 1 — derived state and index

```
python3 scripts/campaign-report.py --surface
python3 scripts/campaign-report.py --carryover --write
python3 scripts/campaign-report.py --index --write
```

If `campaigns/INDEX.md` / `carryover.yaml` changed: commit them with a path-specific `git add` and push. Copy the surface lines into the Step 4 report; do not "handle" them — delivering them to the next human session is the job of your session-start hook or dashboard.

## Step 2 — heartbeat

Write the UTC timestamp to your heartbeat file (e.g. `~/.local/state/verification-cycle/heartbeat.txt`) plus two lines: the `autorun` value and the Step 3 outcome (`ran <dir>` / `skipped: <reason>`). A separate checker reports a stale heartbeat.

## Step 3 — run one queued campaign (only if `autorun: true`)

If `autorun` is false, do nothing here and report "autorun OFF". Otherwise:

1. Read `campaigns/QUEUE.yaml`; take the first entry with `autorun: true` and no `consumed`, up to `max_campaigns_per_tick` (normally 1). Skip entries for another vendor.
2. Read its spec. **If the spec contains an expected verdict, skip it and report a spec defect** (isolation discipline). Create the campaign dir, copy the spec to `spec.md`, create `ledger.yaml` as `[]`. If the spec asks for the sandbox variant, cut the sandbox with `make-review-sandbox.py create` and write only there (collect at the end).
3. Execute under worker discipline: `export CAMPAIGN_WORKER_DIR=campaigns/<dir>`; itemise → derive from definitions → `checks/check_<id>.py` + `foil_<id>.py` → three-state ledger → commit every 1–3 items. Stop at `cap.items` / `cap.minutes`. A suspected error is written up as a refuted item with its derivation and the run stops there (no contact).
4. Finish: `campaign-report.py campaigns/<dir> --run --write` → `results.md` (verdicts / checked / NOT / confidence / questions) → commit + push (path-specific) → stamp `consumed: <today>` in the queue entry and commit → drop the return marker with your harness's return command (`--status done` or `partial`). Generate a token if the entry has none.

## Step 4 — report (stdout, kept in the log)

Surface lines, whether INDEX changed, the `autorun` value, Step 3 outcome, the files touched — and, explicitly, **what was not done**: receipt (`novel_to_requester`) is a human's, no author contact, no hoist.

## Stopping conditions (reported as normal completion)

- repo dirty / diverged → Step 3 skipped
- spec contains a verdict → skipped
- paper cannot be fetched / definitions cannot be read → items unverified; if nothing can proceed, `partial`
- cap reached → `partial`
