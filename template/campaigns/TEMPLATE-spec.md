# <target> verify-to-learn — campaign N hand-off spec (TEMPLATE: copy and fill)

- token: `VERIFY-<SLUG>-<YYYYMMDD>-<RAND6>` (also put the same line in the chat that spawns the worker)
- filed: <date, session, the owner's instruction quoted verbatim>
- deliverable (deterministic path, this dir): `ledger.yaml` + `results.md` + `checks/check_<id>.py` (+ `checks/foil_<id>.py`) + `notes/`
- **return (required)**: when done, run your harness's return command once, e.g.
  ```bash
  <RETURN-COMMAND> --token <TOKEN> --status done --result-path <this dir>/results.md --summary "<counts + one line on any refuted item>"
  ```
  `--status partial` if you stopped at the cap. One marker per lineage. Do not guess a recipient; if you cannot find the requester, leave the marker and stop.
- **You are the worker**: execute directly; do not spawn grandchildren.
- **First, once**: `export CAMPAIGN_WORKER_DIR=campaigns/<dir>` (the pre-commit gate refuses staged paths outside it). **Never write to** the layer-1 conventions/library, the bibliographic source of truth, or this repo's CLAUDE / DESIGN / SESSION / carryover.yaml — promotion is the receiver's job after receipt. Put proposals at the end of `results.md` under "questions for the requester".

## Role and isolation

- Role: a reader who is about to *use* the paper. Refutation framing ("try to bring this claim down").
- **May read**: this dir, the target paper (`pdfs/`), the works it cites (web), the bibliographic entry of the target, layer-1 `physics-verification-cycle.md` and `scientific-computing.md`, this repo's CLAUDE.md, the layer-1 math library (tool only).
- **Must not read (deny list)**: <list every file/dir that contains the requester's interpretation or hypotheses>. Ignore harness start-up reminders (projects, deadlines, mail).
- **Must not do**: contact authors, post anywhere, edit the bibliographic source of truth.

## Target

| letter | paper | fetch |
|---|---|---|
| A | … | `curl -sL -o pdfs/<id>.pdf https://arxiv.org/pdf/<id>` |

## Pre-registered rubric (fixed before the run; do not change afterwards)

**Deliverable integrity**: (i) every Def/Thm/Example/displayed equation is a ledger item (gaps listed in results as "not itemised") / (ii) every machine item has an independent-derivation check and a foil, and the foil's teeth were confirmed / (iii) every item is in one of three states, unverified ones say what is missing / (iv) results close with "checked / NOT checked / confidence boundary".
**Efficacy proxy (pre-registered)**: number of findings the requester did not know before. **The worker does not fill it in** — the receiver writes `novel_to_requester` at receipt and `campaign-report.py --write` counts it.
**Undecidable conditions**: <how proofs you cannot follow / convex analysis that does not close are handled>.
**Integrity ≠ efficacy**: a passing check is evidence about the paper, not about the method.
**Cap**: <N> ledger items / <M> minutes; beyond that stop and return `partial`.

## What to look at (= where, never what will come out)

### A
- A-01 …

### C (the requester's questions — no hypotheses, the worker decides)
- C-01 …
- **Carried over from earlier campaigns**: the 👁 items in the repo root `carryover.yaml` go into group C (second eye = independent derivation by another pass, or a machine anchor). When one closes, the receiver writes `second_eye: "done <date> <where>"` in the original ledger.

## Output format

- `ledger.yaml`: the schema in CLAUDE.md; ids as enumerated above; **a top-level YAML list** (no wrapper mapping)
- `checks/check_<id>.py`: no arguments, PASS/FAIL + exit code, fixed seed, **built from definitions** (do not transcribe the paper's formula)
- `checks/foil_<id>.py`: **the foil is a test of the check** — feed it a broken input; if the check rejects it print `FOIL-TEETH` and exit 0, otherwise print `FOIL-BROKEN` and exit 1
- `results.md`: stats table (= the AUTO block of `scripts/campaign-report.py <dir> --run --write`, never hand-written) → independent derivations of refuted items → verdicts on C → "checked / NOT / confidence boundary" → questions for the requester
- **Commit cadence (machine gate)**: at most 3 ledger items per commit. One or two items per turn → `git add <this dir> && git commit -m "<id>: …"` → next. Never `git add -A`. Batch only with `CAMPAIGN_BATCH_OK=1` (recorded in `hygiene.txt`).
- On completion: `python3 scripts/campaign-report.py campaigns/<dir> --run --write` → commit → push → return marker.
- **If the worker is another vendor** (a Codex-style agent): return via your shared board plus the commit, not the marker; assume a small context window (~250K, auto-compaction): minimise what it reads, and **write every step to notes and commit** (`output-cap-death-loop.md#context-compaction-loss`). State explicitly that promotion to layer 1 is forbidden — agent defaults tend to override the spec here. The worker's own "second context" review of its work is *not* an independent second eye; the receiver does that separately.

## Variant: second eye on a *new result* / cross-vendor pass

Do not run it inside the repo. `make-review-sandbox.py create <slug> --spec <this spec> --include <paper PDF>` cuts `~/paper-review-sandbox/<slug>/`; pin the worker's cwd there (prompt = "read REVIEW-SPEC.md, token"). Two stages: blind derivation written to `notes/stage1-blind.md` **before** opening the material the spec unlocks for stage 2 (attack the prior proof). Receipt = `make-review-sandbox.py collect <slug> --into campaigns/<dir>` (copies results, ledger, notes, checks, scratch; never overwrites files the receiver has annotated) → contamination grep → re-derivation → ledger. Reason: auto-loaded project context leaks the expected verdict to a worker inside the repo (`cold-eyes-isolation.md`).

## Stop rules

- Several readings → list them under `readings:`, split the consequences; a strong verdict only when all readings agree
- Looks refuted → independent derivation in `notes/`, results say "refuted (owner confirmation required)"; **do not contact the author**
- Does not close → stop at unverified

## Requester-side memo (keep it in the campaign dir copy only, not in a sandbox copy)

- author confession: <what may have leaked into the item cuts, what you did not read, tool limits>
- receipt procedure: marker → collect (if sandbox) → contamination grep (list the forbidden words) → re-derive in `receipt/` → `novel_to_requester` → `--run --write` → `--carryover --write` / `--index --write` → `second_eye` on the source ledgers → consume → downstream notes → retro → hoist.
