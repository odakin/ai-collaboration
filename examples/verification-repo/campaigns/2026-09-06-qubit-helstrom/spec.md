# Qubit Helstrom bound in Bloch form — worked-example campaign spec

- token: `VERIFY-EXAMPLE-20260906-QH0001`
- filed: 2026-09-06, as the worked example shipped with `ai-collaboration/template/`
- deliverable (this dir): `ledger.yaml` + `results.md` + `checks/check_<id>.py` + `checks/foil_<id>.py`
- return: none (example); a real campaign runs its harness's return command once (`--status done|partial`)
- **You are the worker.** `export CAMPAIGN_WORKER_DIR=campaigns/2026-09-06-qubit-helstrom`. Do not write outside this dir; proposals go to "questions for the requester" in `results.md`.

## Role and isolation

- Role: a reader who wants to *use* the bound in a first-year quantum-information chapter. Refutation framing.
- May read: this dir, any standard textbook treatment of minimum-error state discrimination (web), layer-1 `physics-verification-cycle.md` §1–§9.
- Must not read: the requester's draft chapter (it contains the requester's own derivation).

## Target

Standard result (no single source; e.g. Helstrom 1976, Nielsen–Chuang §9.2): for states ρ₀, ρ₁ with priors p, 1−p and a two-outcome POVM {M₀, M₁},

  Err = p Tr ρ₀M₁ + (1−p) Tr ρ₁M₀ ≥ ½ − ½ ‖pρ₀ − (1−p)ρ₁‖₁ ,

with equality for the projector onto the positive part of pρ₀ − (1−p)ρ₁.

## Pre-registered rubric

Integrity: every item in one of three states; the machine item has a check built from the definitions (optimise over POVMs directly, do not transcribe the closed form) and a foil that proves the check has teeth. Efficacy proxy: `novel_to_requester`, filled by the receiver. Undecidable: an item whose derivation you cannot close stays unverified. Cap: 4 items / 30 minutes.

## What to look at

- E-01 For qubits ρᵢ = (I + rᵢ·σ)/2: write ½‖pρ₀ − (1−p)ρ₁‖₁ in closed form in terms of r₀, r₁, p, and confirm it equals the minimum error over all POVMs (numerically, from the definition of the optimum).
- E-02 Does the same closed form (with a generalised Bloch vector) hold for qutrits?

## Output format

`ledger.yaml` = top-level list (schema in CLAUDE.md). `checks/check_E-01.py`: no arguments, PASS/FAIL, fixed seed. `checks/foil_E-01.py`: broken input rejected → print `FOIL-TEETH`, exit 0; not rejected → `FOIL-BROKEN`, exit 1. `results.md`: leave the stats table to `campaign-report.py --run --write`; close with checked / NOT checked / confidence boundary / questions.

## Stop rules

Several readings → list them. No grounds → unverified. Never build on an unverified item.
