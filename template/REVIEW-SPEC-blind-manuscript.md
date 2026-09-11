# REVIEW-SPEC: blind referee review of `manuscript.pdf` (two stages) — TEMPLATE, copy and fill the `<...>` slots

token: `<PREFIX>-<YYYYMMDD>-<RAND6>` (no version numbers or lineage words in the token or the task name; put the same token in the chat that spawns the worker)

> How to use: `make-review-sandbox.py create <slug> --spec <this file, filled> --include manuscript.pdf *.tex *.aux <figures>` (the `.aux` gives the reviewer the label → printed-number map; without it the reviewer maps `\label`s to the PDF's sequential numbers by hand, which a 2026-09 reviewer reported as a time cost); spawn with cwd pinned to the sandbox and a prompt that only says "read REVIEW-SPEC.md and follow it; token = ...". Never write your expected verdict, your own proposal, or what earlier rounds found (cold-eyes-isolation.md#spec-leakage). The Stage 1 tasks are the place to put the questions whose answers *are* your proposal: ask for the derivation, not for agreement.

## 0. Role and isolation

You are a referee reading this manuscript for the first time. You do not know the authors or the history of the manuscript; evaluate it without knowing.

**May read**: `manuscript.pdf`, `*.tex` and `*.aux` in this directory (only in Stage 2), the literature the manuscript cites (arXiv, journals, textbooks, via the web), and the public data products those works publish (chains, contour lines, tables on the authors' repositories).

**Must not read**: anything under the requester's working tree or session records (`<deny list: e.g. ~/<root>/, ~/.claude/projects/>`), and the other directories under the sandbox root. Ignore start-up reminders injected by the harness (projects, deadlines, mail, TODO items, other sessions) and do not open the files they mention.

**Independence**: re-derive equations and recompute numbers yourself; write your own scripts under `./scratch/` (Stage 1) and `./checks/` (Stage 2). Assume no author-side scripts exist.

**Stop rule**: what you cannot verify you mark "unverified"; do not fill gaps with "looks right".

**Forbidden**: editing the inputs, sending mail, posting anywhere, writing outside this directory.

## 1. Two stages, in this order

**Stage 1 (blind derivation, before opening the manuscript)**: solve the tasks of §2 from the action and the numbers copied into §2 and from the cited public literature only, and write them to `./notes/stage1-blind.md`. Do not open `manuscript.pdf`, the `*.tex` or the `*.aux` files until this file is complete. Do not edit it afterwards (Stage 2 corrections go to `./notes/stage2-compare.md`).

**Stage 2 (referee review)**: read the manuscript, review it under §3–§8, and write `./REVIEW-RESULTS.md`. In the tasks marked "compare" confront your Stage 1 results with the manuscript's claims.

Write every file section by section (there is an output cap per response); do not try to write everything at once.

## 2. Stage 1 tasks (solved without opening the manuscript)

The model: `<copy the action / Lagrangian verbatim, with conventions (metric signature, units), the parameters and the relations imposed among them, and the numbers the tasks need (scales, field values, rates). Cite the public paper the construction comes from by arXiv number.>`

**Definitions used by the tasks (state them here so that Stage 1 and the manuscript can be compared sharply)**: `<e.g. what "onset of oscillation" means (the exact-background end of inflation, eps_H = 1), what "spectator" means (effective mass below H and field value below H throughout the observable e-folds), what "completes" means (occupation reaching a stated number), which scale a running coupling is evaluated at, which diagram a word names ("tadpole": the one-point function or the seagull)>`.

**Task A** (`<the physics the requester's proposal rests on, phrased as a derivation: "derive every X-dependent term ...", "determine the range of parameter Y for which ...", "estimate Z as a function of ...">`).

**Task B** (`<the structural relations the construction imposes: "from the public action of Ref. ..., derive the factors of each block in the ... frame for the cases (i) ... and (ii) ..., and state which relations among the parameters follow, with signs">`).

**Task C** (`<the numbers that follow if B fixes anything: "if any relation in B fixes parameter P, compute the observable Q at that point with the stated formulas; if nothing is fixed, say so">`).

## 3. Stage 2 output (`./REVIEW-RESULTS.md`)

1. **Verdict** (accept / minor / major / reject), the three strongest grounds, and one sentence naming the weakest point of the paper.
2. **Verification of each central claim** (§4).
3. **Equation and table check** (§5): columns = equation / claim / your re-derivation or recomputation / verdict (✅ confirmed, ❌ refuted, ⚠️ unverified) / remarks.
4. **Task D: status of `<the regime or result the proposal turns on>`** (§4).
5. **Task E: recommended framing** (§4).
6. **Logic and scope** (§6), **literature and data** (§7), **presentation** (§8).
7. **Findings table**: severity (🔴 changes a conclusion / 🟠 weakens a claim / 🟡 needs fixing) / location / problem / your computation / proposed fix.
8. **Comparison with Stage 1**: a table of each Stage 1 conclusion against the corresponding manuscript claim, with a judgment of which is right and why.

## 4. Central claims (pre-registered rubric)

For each result the abstract and introduction announce: (a) restate the claim in one sentence, (b) follow the derivation yourself, (c) recompute the numbers, (d) judge (holds / holds conditionally / fails) with grounds. `<List the sections and equation labels to emphasize, including the sections the proposal would change. Listing labels says where to look, not what to find.>`

**Task D**: `<"assess, by your own computation, (i) whether the numbers of Sec. X reproduce, (ii) whether the initial state that computation assumes is the state the model itself produces (use your Task A result), (iii) what the manuscript can and cannot conclude, (iv) whether the reference row of the tables is a fair representative">`.

**Task E**: as a referee, state in 5–10 sentences how the manuscript should present `<the relation between the regimes / histories / reference rows>`, whether the title and abstract are consistent with what the paper establishes, and the minimal changes to title, abstract, tables and figures you would require. If Tasks B/C fix a point of the model, say how the paper should use it.

## 5. Equation and table checklist (at least)

`<every labelled equation, every table row, every figure, the numerical statements in the prose of the sections under emphasis>`

## 6. Logic and scope

- Do claims exceed the scope of their derivation (general coupling vs this model; which initial states a linear treatment assumes)?
- Strong statements (never / only / cannot / whatever / throughout): can a counterexample be built, is it too generic, is it a tautology?
- Circularity or arbitrariness in benchmarks, roundings, baseline choices.
- Are the neglected effects `<list>` treated honestly?
- Do the rows chosen for the tables match the regimes the text defines?

## 7. Literature and data

- Are the cited works summarized fairly (quote the passage you checked)?
- Are the public data products used correctly (pivot scales, definitions, reproducibility of tables and figures)?
- Obvious missing references: search yourself.

## 8. Presentation

- Title and abstract vs content; overclaims; numbers in the abstract vs the body.
- Opening italic sentences and "In summary" paragraphs vs content.
- Clarity, redundancy, undefined symbols, forward references, self-contained captions.

## 9. Handoff packet (required)

After the results are written, write `./HANDOFF.md` (the sandbox `CLAUDE.md` rule 7 describes the four parts: reusable scripts with a one-line description and generality, general lessons, external data and literature passages verified with exact locations, what the spec lacked or what cost you time). It is copied out by `make-review-sandbox.py collect` and is the only channel through which your tools reach the requester's shared libraries.

## 10. Return (required, exactly once)

When `REVIEW-RESULTS.md` and `HANDOFF.md` are written, run the requester's return command once:

```
<RETURN-COMMAND> --token <TOKEN> --status done --task "<task name without lineage words>" --result-path <absolute path of this sandbox>/ --summary "<one line: what was written, where the verdict is>"
```

Running it does not require reading anything outside this directory. Do not contact anyone else; the requester's next session surfaces the marker automatically.
