---
# TEMPLATE-retro.md — the retro of one round (written by the receiver after receipt).
# Copy to campaigns/retros/<date>-round<N>.md. The front matter is read by the tools
# (verification-campaign-report.py --index / --surface):
round: N
date: YYYY-MM-DD
campaigns: [<campaign dir name>, ...]             # campaigns this retro closes (state → retro'd)
contamination: {<campaign dir name>: <hits>}      # post-receipt grep hits + the worker's own admissions; 0 if none
gate_violations: {<campaign dir name>: <count>}   # lines in hygiene.txt + scope-gate escapes; 0 if none
hoist: {}                                         # after the hoist station (§7): {<campaign dir name>: "<date> <where>"}; until then --surface says 📤
---

# round N retro — <one line>

> Discipline (layer-1 `verification-cycle-ops.md`): numbers are copied from the AUTO block / INDEX.md, never self-reported. "It worked" means "what was observed", not "what did not break". Every proposal gets **one of three fates** (gate = mechanised / rule = convention + revisit trigger + review_by / rejected = reason) and an id in `improvements.yaml`. No proposal without a fate.

## 1. Numbers (machine-derived)

| campaign | items | verified / refuted / unverified | novel (receiver) | duration | items/commit max | contamination |
|---|---|---|---|---|---|---|
| | | | | | | |

## 2. What worked (observed facts)

- 

## 3. What did not work / what broke

- 

## 4. What cannot be said yet (limits of the efficacy proxy)

- 

## 5. Proposals → fate

| # | proposal | fate | improvements.yaml id | evidence |
|---|---|---|---|---|
| 1 | | gate / rule / rejected | R<N>-xx | |

## 6. Questions carried to the next round

- 

## 7. Hoist station (`verification-cycle-ops.md#hoist-station`) — fill in, then record in the front matter `hoist:`

| campaign | scripts kept (checks / notes / scratch / receipt committed?) | functions promoted to the layer-1 library | kernels promoted to layer-1 conventions (§ / anchor) | reference notes | DESIGN / SESSION |
|---|---|---|---|---|---|
| | | | | | |
