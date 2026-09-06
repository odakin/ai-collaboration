# results — 2026-09-06-qubit-helstrom (worked example)

<!-- AUTO-CAMPAIGN-STATS (verification-campaign-report.py --write; 手編集しない) -->
**campaign stats (git-derived)**

| 指標 | 値 |
|---|---|
| item | 2 = unverified 1 / verified 1 |
| tier | 📄 1 / 🔧 1 (readings 列挙 1) |
| checks / foils | 1 / 1 |
| **efficacy proxy** = 起票者が知らなかった finding | **0** (—) |
| 👁 で第二の目待ち (carryover) | 0 (—) |
| **実走 (--run)** | checks 1/1 PASS, foils 1/1 teeth (contract: standard) |
<!-- /AUTO-CAMPAIGN-STATS -->

## Verdicts

| id | statement | status | tier | grounds |
|---|---|---|---|---|
| E-01 | qubit Helstrom bound = ½ − ½ max(\|2p−1\|, \|p r₀ − (1−p) r₁\|) and it is the POVM optimum | verified | 🔧 | eigenvalues of X = pρ₀ − (1−p)ρ₁ from the Bloch form; optimum over random POVMs + Helstrom projector matches to 1e−9 on 600 instances; foil (non-positive "effect" beating the bound) rejected |
| E-02 | same closed form for qutrits | unverified | 📄 | the 3×3 trace norm depends on all eigenvalues, not only on the Bloch-vector norm; no counterexample built within the cap |

## Checked / NOT checked / confidence boundary

- Checked: the closed form against the definition of the minimum error (random POVMs plus the Helstrom projector), all priors in (0.02, 0.98), mixed and near-pure states.
- NOT checked: the optimality proof itself (we rely on the standard argument that the Helstrom projector is optimal; the numerical optimum only *confirms* nothing beats it among 200 random POVMs per instance). Qutrits (E-02).
- Confidence boundary: E-01 high (closed form is elementary; the check is independent of it). E-02 no grounds.

## Questions for the requester

1. Is the qutrit question (E-02) wanted at all, or was it only a probe of the stop rule?
