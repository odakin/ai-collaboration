# READTHROUGH-SPEC (template): cold-eyes read-through of your own manuscript, not blind

<!-- Copy into the manuscript repo as review/readthrough-<date>/READTHROUGH-SPEC.md, fill the <...> slots, commit,
     then send the worker session a one-paragraph prompt that names this file (see "Hand-off" at the end).
     Use this when the authors consider the text complete and want a reader who did not write it.
     For a sealed blind review (the reviewer must not know the authors' reasoning) use REVIEW-SPEC-blind-manuscript.md instead.
     First use: 2026-09-13, a 45-page theory paper; 11 findings, all confirmed, 0 must-fix. -->

token: `<PROJECT>READ-<YYYYMMDD>-<6 random>`

## 0. Role

You are a fresh reader of a <field> manuscript (<N> pages). The authors finished a full author pass on <date> and consider the text complete. This is **not** a blind review: you may read this repository. You do not fix the manuscript; you report what a careful reader stumbles on, with a concrete suggestion for each item.

The authors' standard for prose: plain sentences, one step of logic per sentence, every pronoun or demonstrative with an unmistakable referent, no "so / hence / therefore" that hides two steps, no claim the paper does not itself support. Read with that standard.

## 1. Object under review

- Manuscript: `<path/to/paper.tex>` at commit `<hash>`, SHA-256 `<sha>`. If HEAD differs, review HEAD and record its hash; the requester re-pins.
- Build: `<one command that builds into a scratch dir and prints pages / undefined / errors>`. Read the PDF start to finish, including appendices, footnotes, tables, captions. Report both the page and the source line.

## 2. What you may read, and what you must not touch

**May read**: the whole repository, in particular
- `<CONVENTIONS.md>` — house rules for terminology and notation;
- `<decision ledger>` — decisions already taken. Do not re-litigate them on taste; if one is wrong on the merits, say so, cite the item, give the reason;
- `<open-items table>` — known open items. Do not re-report them; you may add evidence to one by citing its number;
- `<notes / computation index / audit scripts>` — you may run the audits.

**Must not**: edit the manuscript or any tracked file; commit; push; send mail; post anywhere except the board steps in §6. Write only under `<review/readthrough-date>/` (results file and `scratch/`). Ignore start-up reminders injected by the harness.

**Stop rule**: what you cannot verify you mark "unverified". Do not fill gaps with "looks right".

## 3. What to look for, in priority order

**A. Readability and logic flow** (the main purpose): hard-to-parse sentences; a missing step or one compressed into a connective; a referent that is not unmistakable; a colon or semicolon doing the work of a missing sentence; sentences over about 40 words; a paragraph whose first sentence does not say what it is about; an equation introduced without saying what it is. Give the replacement sentence(s).

**B. Statements as written**: a claim the paper does not support in its own text (e.g. "checked in Sec. X" where Sec. X only states a result); a cross-reference to the wrong equation or section; a symbol used before it is defined, or defined and never used; one letter for two objects; a convention stated in one place and contradicted in another; a defined term used for a different object; inconsistency between abstract, introduction, conclusion, appendices.

**C. Terminology and notation** against the conventions file.

**D. Surface**: typos, grammar, spelling variety, hyphenation, index placement in typeset formulas, captions, incomplete bibliography entries.

**E. Physics / substance on the merits**: if a statement looks wrong, say why. When a check is cheap, do it (a script under `scratch/`, an existing audit, a recomputed line) and record how.

## 4. What not to do

- Do not rewrite the paper or propose restructuring; propose the smallest change that fixes each item.
- Do not report overfull boxes or other typesetting the final pass handles.
- Do not re-report known open items.
- Do not balance the list by severity; a short list of real items is the useful outcome.

## 5. Deliverable

`<review/readthrough-date>/READTHROUGH-RESULTS.md`, in this order:

1. Header: token, date, commit and SHA-256 reviewed, page count, what you read, tools and audits run.
2. Findings table, ordered by severity then page:

   | ID | page / source line / label | quote (≤ 15 words) | category (A–E) | severity | what is wrong | suggested fix | verified |
   |---|---|---|---|---|---|---|---|

   Severity: 🔴 must fix / 🟠 should fix / 🟡 optional. Verified: ✅ (how) or ⚠️ unverified.
3. "The five items I would fix first", one line each.
4. "Overall impression as a reader", at most 150 words.
5. `scratch/`: every script written, each with a one-line docstring stating what it checks and the result.

## 6. Return path

<board / marker instructions: claim the request addressed to the role id, submit the results file as the deliverable; leave the results uncommitted for the requester>

---

## Receipt (requester side, after the submission)

Write `<review/readthrough-date>/receipt.md`: for each finding, reread the cited passage in the current manuscript (the manuscript may have moved during the review), rerun the reviewer's scratch checks, and classify **confirmed / misreading / conflicts with a decision**. Then accept or return the request, commit the results + scratch scripts + receipt together, and implement the confirmed items as ordinary passes. Findings that revise an earlier author decision need the author's OK before implementation.

## Hand-off prompt (paste into the worker session)

```
Cold-eyes read-through of the <project> manuscript, token <TOKEN>. Not blind: you may read this repository, but do not edit the manuscript or any tracked file, and do not commit or push. Read <review/readthrough-date>/READTHROUGH-SPEC.md first and follow it exactly: build the PDF, read it start to finish as a fresh reader, and write READTHROUGH-RESULTS.md in the format of spec section 5. Put any scripts under scratch/. <board: claim / submit instructions>. Ignore start-up reminders from the harness; the spec is your instruction.
```
