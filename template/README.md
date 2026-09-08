# template/ — a verification repo you can clone and run

This directory is a **starter skeleton** for your own private verify-to-learn repo (the one that
holds campaigns: claim ledgers, machine checks with foils, results, retros). Everything here is
generic; the paper-specific content lives in *your* repo, which should stay private by default
(findings about other people's papers are irreversible once public — see
`conventions/physics-verification-cycle.md#verify-to-learn`).

One command:

```bash
python3 scripts/init-verification-repo.py ~/my-verification   # copies this skeleton, git init, installs the pre-commit gate, runs the selftests
```

What you get:

| file | role |
|---|---|
| `CLAUDE.md` | how the cycle runs in this repo (ledger schema, 4 steps, receipt, hoist station) — points at the layer-1 conventions for the "why" |
| `campaigns/TEMPLATE-spec.md` | the hand-off spec a worker session executes: role and isolation, pre-registered rubric, items to look at (never the expected verdict), output format, stop rules, return command |
| `campaigns/TEMPLATE-retro.md` | the retro written after receipt: machine-derived numbers, what worked, what broke, proposals with a 3-way fate, hoist checklist |
| `REVIEW-SPEC-blind-manuscript.md` | two-stage spec for a sealed-sandbox blind review of one's *own* manuscript (`scripts/make-review-sandbox.py create --spec`): Stage 1 = derivation tasks solved before the manuscript is opened (with the judgment criteria defined in the spec), Stage 2 = referee review + framing recommendation, HANDOFF packet, return command; the requester's proposal is never written into it |
| `campaigns/QUEUE.yaml` | queue for the unattended tick (schema in the header; `autorun: false` by default) |
| `improvements.yaml` | fate ledger of retro proposals (implemented / deferred with review_by / rejected) |
| `hooks/pre-commit` + `scripts/install-hooks.sh` | commit-cadence gate (≤ 3 ledger entries per commit) and worker scope gate (`CAMPAIGN_WORKER_DIR`) |
| `scripts/campaign_hygiene.py`, `scripts/campaign-report.py` | shims that pin repo-specific defaults and call the layer-1 tools (`ledger-commit-cadence-gate.py`, `verification-campaign-report.py`) |
| `UNATTENDED-TICK.md` | the procedure an unattended daily run follows (surface + index + heartbeat always; run a queued campaign only behind a kill switch; never cross the human gates) |

The layer-1 tools are located via the environment variable `AI_COLLABORATION_ROOT` (default: the
directory that contains this `template/`, i.e. a clone of this repository next to yours).

A worked example of a completed campaign (spec → ledger → check + foil → results with the AUTO
stats block → retro with a hoist record) is in [`../examples/campaign-qubit-helstrom/`](../examples/campaign-qubit-helstrom/).
