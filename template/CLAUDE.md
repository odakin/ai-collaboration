# CLAUDE.md — <your verification repo>

Home of **verify-to-learn campaigns**: papers you are about to *use* are read claim by claim, each
claim is derived independently from definitions, anchored by a machine check with a foil, and
recorded in a three-state ledger (verified / refuted / unverified). Audits of your own manuscripts
stay in their paper repos; this repo is for other people's papers and for second eyes on new results.

⚠️ **Keep this repo private.** Findings include suspected errors in other people's papers; an
unconfirmed error claim cannot be un-published. Default = private; author contact only after the
*owner* has understood the counterexample by hand (an AI-refuted item, however many independent
passes agree, is not grounds — `conventions/physics-verification-cycle.md#verify-to-learn`).

## Where the rules live (layer 1, public)

- What to check: `ai-collaboration/conventions/physics-verification-cycle.md` (4 stations, machine anchor + foil, tiers 🔧👁📄, three claim states, verify-to-learn, independent second eye, rubric before run, stop when there are no grounds, cross-vendor passes, campaign tooling A–L)
- How it keeps running: `ai-collaboration/conventions/verification-cycle-ops.md` (six principles, derived campaign state machine, three ledgers + retro, unattended layer with human gates, fresh-session procedure, hoist station)
- Keeping a second eye blind: `ai-collaboration/conventions/cold-eyes-isolation.md`

## Layout

```
campaigns/<YYYY-MM-DD>-<slug>/
  spec.md        # hand-off spec (token / target / pre-registered rubric / stop rules / return command)
  ledger.yaml    # claim ledger: a top-level list, one item per entry, three states
  results.md     # human summary; the stats table is an AUTO block written by campaign-report.py
  checks/        # check_<id>.py (exit 0 = PASS) and foil_<id>.py (prints FOIL-TEETH exit 0 / FOIL-BROKEN exit 1)
  notes/         # derivations, listed readings, scratch that may be promoted later
  receipt/       # the requester's *own* re-derivation scripts (never the worker's)
  pdfs/          # paper PDFs (.gitignore; re-fetchable)
campaigns/retros/<date>-round<N>.md   # retro per round; its front matter is read by the tools
campaigns/QUEUE.yaml                  # unattended-tick queue (autorun: false by default)
campaigns/INDEX.md                    # generated: derived state + efficacy dataset (do not edit)
carryover.yaml                        # generated: 👁 items still waiting for a second eye
improvements.yaml                     # fate ledger of retro proposals
```

## ledger.yaml — one item

```yaml
- id: A-03                        # <paper letter>-<number>
  source: "<bibkey> Thm 2"        # bibliographic key + label inside the paper
  statement: "..."                # the claim, in your words
  class: machine | prose
  tier: "🔧" | "👁" | "📄"          # machine-verified / own derivation only / read only
  status: verified | refuted | unverified
  check: checks/check_A03.py      # machine items only; foil = checks/foil_A03.py
  readings: []                    # if the statement admits several readings, list them and split the verdict
  note: "..."                     # refuted → key of the independent derivation; unverified → what is missing
  novel_to_requester: true        # written by the RECEIVER at receipt, never by the worker (efficacy proxy)
  second_eye: "done <date> <where>"   # 👁 items closed by another pass → drop out of carryover.yaml
```

## The cycle (four steps + receipt + hoist)

1. **Itemise**: every definition / theorem / example / displayed equation / numerical claim becomes one ledger item (in the paper's label order, after reading the whole paper).
2. **Classify**: machine (equations, limits, numbers, small-dimensional counterexamples) or prose.
3. **Machine check**: derive each machine item *from definitions* (re-typing the paper's formula is not a check) → fix it in `checks/check_<id>.py` → prove the check has teeth with `checks/foil_<id>.py` → commit every 1–3 items (the pre-commit gate refuses more than 3 ledger entries per commit).
4. **Ledger + results**: three states; never build on an unverified item; `results.md` closes with "what was checked / NOT checked / where confidence ends". The stats table is written by `scripts/campaign-report.py <dir> --run --write`, never by hand.
5. **Receipt (requester)**: contamination grep → re-derive the main findings yourself in `receipt/` (do not run the worker's scripts as your check) → fill `novel_to_requester` → `--run --write`, `--carryover --write`, `--index --write` → consume the return marker → propagate verdicts downstream.
6. **Retro → hoist station**: write `campaigns/retros/<date>-round<N>.md` from the template (every proposal gets a fate in `improvements.yaml`); then keep every script the worker made, promote reusable functions to the layer-1 library and kernels to the layer-1 conventions, update reference notes / DESIGN / SESSION, and record it in the retro front matter `hoist:`. Until that record exists `campaign-report.py --surface` keeps saying 📤.

**Stop rules**: no grounds → unverified, hand it to a human. Looks refuted → write the independent derivation and *stop* (author contact and publication are the owner's decisions). One item per turn; commit partial results before continuing (output-cap discipline).

## Tools (shims to layer 1)

| command | role |
|---|---|
| `scripts/install-hooks.sh` | install the pre-commit gate once after cloning |
| `scripts/campaign-report.py <dir> --run --write` | run checks/foils, write git-derived stats into `results.md` |
| `scripts/campaign-report.py --carryover --write` / `--index --write` / `--surface` | regenerate `carryover.yaml`, `campaigns/INDEX.md`, or print only the stations that are stuck |
| `AI_COLLABORATION_ROOT=<path> …` | where the layer-1 tools are (default: sibling clone of `ai-collaboration`) |

## How to resume

1. `python3 scripts/campaign-report.py --surface` → go to the station that is stuck (layer-1 ops §5).
2. `python3 scripts/campaign-report.py --index` → every campaign's derived state and numbers.
3. For a campaign in progress: its `ledger.yaml` (state distribution) and `spec.md` (rubric, stop rules).
