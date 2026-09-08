# ai-collaboration

Conventions, mechanical gates, and tooling for doing research **with** AI agents — what to hand to the machine, what a human must still check, and how the cycle keeps running across sessions and vendors (Claude Code, Codex, or any other pass).

## Why this exists

Verification-first collaboration: every claim an AI produces is either machine-anchored, seen by an independent second eye, or explicitly marked unverified — and the human keeps the judgement calls (meaning, publication, promotion into shared sources of truth). This repository holds the vendor-neutral kernel of that practice, split out of [`claude-config`](https://github.com/odakin/claude-config) (which remains the Claude Code harness) on 2026-09-06.

## The loop

1. **Read to use** a paper → itemise claims → derive each from definitions → machine check with a *foil* (a deliberately broken input that the check must reject) → three-state ledger (verified / refuted / unverified).
2. **Second eye** in a sealed sandbox: blind re-derivation first, then attack the original proof.
3. **Receipt** by the requester: contamination grep, independent re-implementation, efficacy proxy, carry-over of unanchored claims.
4. **Retro** whose every proposal gets a fate: gate (mechanised), rule (with a review date), or rejected.
5. Derived state and findings are surfaced to the next session automatically; an unattended tick can run queued campaigns behind a kill switch, never crossing the human gates.

## What's where

- `conventions/physics-verification-cycle.md` — what to check (kernels, campaign tooling A–K)
- `conventions/verification-cycle-ops.md` — how it keeps running (principles, state machine, ledgers, autonomous layer)
- `conventions/cold-eyes-isolation.md` — how to keep a second eye actually blind
- [Session coordination and board receipt](https://github.com/odakin/claude-config/blob/main/conventions/multi-session-coordination.md#git-immutable-event-board) — session identities, submission versus acceptance, explicit handover and one receipt carrier. The authoritative convention remains in `claude-config` pending the Phase 2 trigger in `DESIGN.md`.
- [Binary state discrimination](docs/state-discrimination.md) — derivations, equality and cone certificates, coordinate scope and biased qubits; code in `scripts/state_discrimination.py`.
- `scripts/` — `verification-campaign-report.py`, `ledger-commit-cadence-gate.py`, `make-review-sandbox.py`, `gpt_measurements.py`, `state_discrimination.py`, `hpd-credible-level.py`, `svg-contour-extract.py`, `floquet-monodromy.py`, `nstar-fixed-point.py`, `expanding-mode-growth.py`, `dilaton-spectator-growth.py` (each has `--selftest`)

## Quick start

Start your own (private) verification repo from the shipped skeleton, then read the worked example:

```bash
python3 scripts/init-verification-repo.py ~/my-verification   # template/ → git init → pre-commit gate → selftests
```

- [`template/`](template/) — the runnable skeleton (CLAUDE.md, spec/retro templates, queue + fate ledger schema, hooks, shims, unattended-tick procedure)
- [`examples/verification-repo/`](examples/verification-repo/) — one complete tiny campaign: spec → ledger → check + foil → results with the generated stats block → retro with hoist record


```bash
set -e
for s in scripts/*.py; do python3 "$s" --selftest; done
```

Then read `CLAUDE.md` for the minimal setup of your own verification repo.

## Credits

The four-station framing (investigate → machine check → another AI doubts → a human judges), the name *verify-to-learn*, and the "stop when there are no grounds" motto come from Yoshimasa Hidaka's public talk *AI による理論物理研究の自動化* (PPP2026, 2026-08). The practice here converged on it independently; the boundary is recorded at the top of `conventions/physics-verification-cycle.md`.

## License

MIT (see `LICENSE`).
