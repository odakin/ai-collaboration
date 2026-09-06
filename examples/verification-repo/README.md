# examples/verification-repo — a complete, tiny campaign you can read in ten minutes

A miniature verification repo (same layout as `template/`) containing **one finished campaign**,
so you can see every artifact of the cycle side by side:

| artifact | file |
|---|---|
| hand-off spec (role, isolation, pre-registered rubric, items, stop rules) | `campaigns/2026-09-06-qubit-helstrom/spec.md` |
| three-state claim ledger with receiver annotations (`novel_to_requester`) | `campaigns/2026-09-06-qubit-helstrom/ledger.yaml` |
| machine check built from definitions, and its foil | `campaigns/2026-09-06-qubit-helstrom/checks/` |
| results with the AUTO stats block written by the tool | `campaigns/2026-09-06-qubit-helstrom/results.md` |
| retro with proposals → fates and the hoist record | `campaigns/retros/2026-09-06-round1.md` |
| derived state index (generated) | `campaigns/INDEX.md` |

The subject is deliberately harmless: the closed form of the Helstrom bound for two qubit states in
Bloch-vector form — a textbook fact, no claim about anyone's paper. Real campaigns look the same but
their content stays in a private repo.

Regenerate everything from this directory:

```bash
python3 ../../scripts/verification-campaign-report.py campaigns/2026-09-06-qubit-helstrom --run --write --root .
python3 ../../scripts/verification-campaign-report.py --index --write --root .
python3 ../../scripts/verification-campaign-report.py --surface --root .     # silent: nothing is stuck
```
