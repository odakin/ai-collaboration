#!/usr/bin/env python3
"""Refuse a blind-review target that carries its own history (comment text in .tex / .md); warn on self-reference that reads as revision history; --staged-warn flags review history written into tex comments at commit time; --selftest.

Why: isolation by file lists (a deny list in the spec, a read-order instruction) cannot stop history written inside
the target itself.  A header comment that records the previous round's verdict, the list of corrections and the path
of the results note reaches every reviewer who opens the target, on any route.  The sealed sandbox strips comments
(strip-tex-comments.py); a route without that step (a board request answered in the repository) carried the
history to the reviewer unchanged (measured).  So this checks the artifact, not the route:
board/board.py request --review-target and make-review-sandbox.py create call it
(conventions/cold-eyes-isolation.md#contamination-channels (d)).

Target check (exit 0 = referee copy, 1 = refused, 2 = usage).  The predicate is the output contract of
strip-tex-comments.py, so a stripped copy always passes and a paraphrase does not:
  .tex  any comment with non-blank text (a line whose first non-blank char is %, or text after an unescaped %)
  .md   any HTML comment with text
  both  a body sentence that tells the reader the target was reviewed before (a receipt of a blind review and of
        the corrections taken from it, 「盲検」) — kind body-history.  Stripping cannot remove it;
        the author edits the body (measured: such a sentence passed the comment check and the blind
        session stopped on its exposure rule, correctly).  Ordinary uses (a cited review article, "an earlier
        version of this work") do not match.
Warnings (printed, exit unchanged = the target is not refused; the author disambiguates before the request):
  revision-deixis  a body sentence that names the document itself ("the present draft", "this version", "the current
                   draft", "earlier version of this") together with a revision verb ("has removed", "no longer",
                   "now uses"). It may be the subject (a note about another paper's drafts) or the target's own
                   history; a judging session that stops on history reads it as the latter (measured: a sentence about
                   a companion paper's draft, written with a self-naming phrase and a revision verb, stopped a blind run).
  self-noun        the target calls itself "this note" (or memo / report) and elsewhere "this paper" (or manuscript /
                   article), or the other way round: a reader takes both as the target itself (synonyms within one
                   class do not warn) (measured: in a note, "this paper" meant
                   the companion paper and was read as the note's own history).
  Rewrite such sentences to name the work they mean ("the draft of the companion paper ... does not contain"), and
  define history and subject in the spec (template/REVIEW-SPEC-blind-manuscript.md §0).
Review vocabulary and pointers (plans/, notes/, SESSION.md, DESIGN, request tokens) are reported to say how bad a
hit is; they are not the predicate.  The comment text itself is never printed.  Other suffixes (pdf, aux, png) are
listed as not scanned and do not fail: comments do not reach a typeset page.

--staged-warn (pre-commit, warn only, exit 0): staged added lines of .tex files whose comment carries review
vocabulary or a pointer to review records.  Writing a review receipt into the source puts it into the next round's
target; the receipt belongs in the results note (claude-config conventions/latex.md#source-comment-scope).
Exit 3 = the check could not run (not a git work tree, git failed), so a caller can tell failure from a finding.

Usage: check-review-target.py FILE [FILE ...] [--json]
       check-review-target.py --staged-warn [--repo DIR]
       check-review-target.py --selftest
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TEX_COMMENT = re.compile(r'(?<!\\)%(.*)$')            # same boundary as strip-tex-comments.py
MD_COMMENT = re.compile(r'<!--(.*?)-->', re.S)
REVIEW_WORDS = re.compile(
    r'(?i)\b(?:blind|review(?:ed|er|s)?|verdict|referee|cold-?eyes|findings?|rebuttal|erratum)\b'
    r'|盲検|査読|指摘|訂正|撤回|受領|判定|レビュー')
BODY_HISTORY = re.compile(   # typeset text that tells the reader the target was reviewed before (measured:
    # a receipt sentence left in the body passed the comment check and stopped the blind session on arrival)
    r'(?i)\b(?:reviewed\s+blind|blind(?:ly)?\s+review(?:ed)?|independent\s+session|corrections?\s+of\s+(?:that|the|this)\s+review'
    r'|(?:earlier|previous|first|second)\s+(?:review|round\s+of\s+review)|referee\s+reports?|review\s+records?)\b'
    r'|盲検|査読を受け|査読の指摘|査読で')
SELF_DEIXIS = re.compile(   # the document naming itself (or its own versions)
    r'(?i)\b(?:the|this)\s+present\s+(?:draft|version|paper|note|manuscript|article|work)\b'
    r'|\bthis\s+(?:draft|version|revision)\b|\bthe\s+current\s+(?:draft|version)\b'
    r'|\b(?:earlier|previous|former|original|first)\s+(?:version|draft)\s+of\s+this\b')
REVISION_VERB = re.compile(
    r'(?i)\b(?:has|have|had|was|were|been)\s+(?:now\s+)?(?:removed|dropped|deleted|corrected|revised|replaced|changed'
    r'|rewritten|withdrawn|retracted)\b|\bno\s+longer\b|\bnow\s+(?:uses|keeps|contains|includes|states|reads|drops)\b')
SELF_NOUN = re.compile(r'(?i)\b(?:this|the\s+present)\s+(note|paper|manuscript|article|report|memo)\b')
NOUN_CLASS = {'paper': 'paper', 'manuscript': 'paper', 'article': 'paper', 'note': 'note', 'memo': 'note', 'report': 'note'}
POINTERS = re.compile(
    r'\bplans/|\bnotes/|\breviews?/|\bSESSION\.md\b|\bDESIGN\.md\b|\bDESIGN \(|\b[A-Z][A-Z0-9]{2,}-\d{8}-[A-Z0-9]{6}\b')
REMEDY = ("→ make the referee copy: strip-tex-comments.py IN.tex OUT.tex (rebuild, compare the PDF text), commit it "
          "where the receiver can read it, and name OUT as the target "
          "(ai-collaboration conventions/cold-eyes-isolation.md#contamination-channels (d))")


def _describe(body: str) -> dict:
    words = sorted({m.group(0).lower() for m in REVIEW_WORDS.finditer(body)})
    return {'review_words': words, 'pointer': bool(POINTERS.search(body)), 'chars': len(body.strip())}


def body_warnings(lines: list[tuple[int, str]]) -> list[dict]:
    """Warnings on body lines [(line number, text without comments)]: revision-deixis and self-noun (see the docstring).
    Only the matched words are reported, never the sentence."""
    out = []
    nouns: dict[str, list[int]] = {}
    for i, body in lines:
        d, v = SELF_DEIXIS.search(body), REVISION_VERB.search(body)
        if d and v:
            out.append({'line': i, 'kind': 'revision-deixis', 'words': [d.group(0).lower(), v.group(0).lower()]})
        for m in SELF_NOUN.finditer(body):   # synonyms count as one self-name (a paper says "this paper" and "this manuscript")
            nouns.setdefault(NOUN_CLASS[m.group(1).lower()], []).append(i)
    if len(nouns) > 1:
        ranked = sorted(nouns.items(), key=lambda kv: -len(kv[1]))
        top, n_top = ranked[0][0], len(ranked[0][1])
        tie = sum(1 for _, v in ranked if len(v) == n_top) > 1
        for noun, where in ranked[(0 if tie else 1):]:
            for i in sorted(set(where)):
                out.append({'line': i, 'kind': 'self-noun',
                            'words': [f'a "this {noun}"-class self-name', f'elsewhere "this {top}" x{n_top}' if not tie else 'self-nouns tied']})
    return sorted(out, key=lambda w: w['line'])


def scan(path: Path, text: str | None = None) -> dict:
    """{'file', 'scanned', 'hits': [{'line', 'kind', 'review_words', 'pointer', 'chars'}], 'warnings': [{'line', 'kind', 'words'}]}"""
    suffix = path.suffix.lower()
    if suffix not in ('.tex', '.md'):
        return {'file': str(path), 'scanned': False, 'hits': [], 'warnings': []}
    if text is None:
        text = path.read_text(encoding='utf-8', errors='replace')
    hits = []
    bodies: list[tuple[int, str]] = []
    if suffix == '.tex':
        for i, line in enumerate(text.split('\n'), 1):
            m = TEX_COMMENT.search(line)
            if m and m.group(1).strip():
                full = line.lstrip().startswith('%')
                hits.append({'line': i, 'kind': 'comment-line' if full else 'trailing-comment', **_describe(m.group(1))})
            body = TEX_COMMENT.sub('%', line)
            bodies.append((i, body))
            b = BODY_HISTORY.search(body)
            if b:
                hits.append({'line': i, 'kind': 'body-history', 'review_words': [b.group(0).lower()], 'pointer': False,
                             'chars': len(body.strip())})
    else:
        for m in MD_COMMENT.finditer(text):
            if m.group(1).strip():
                hits.append({'line': text.count('\n', 0, m.start()) + 1, 'kind': 'html-comment', **_describe(m.group(1))})
        for i, line in enumerate(MD_COMMENT.sub('', text).split('\n'), 1):
            bodies.append((i, line))
            b = BODY_HISTORY.search(line)
            if b:
                hits.append({'line': i, 'kind': 'body-history', 'review_words': [b.group(0).lower()], 'pointer': False,
                             'chars': len(line.strip())})
    return {'file': str(path), 'scanned': True, 'hits': hits, 'warnings': body_warnings(bodies)}


def _warning_lines(r: dict) -> list[str]:
    ws = r.get('warnings') or []
    if not ws:
        return []
    out = [f"  ⚠️ {len(ws)} warning(s), not refused: a sentence that may read as the target's own revision history. "
           "Name the work it means, or define history and subject in the spec (§0)"]
    for w in ws[:12]:
        out.append(f"    line {w['line']} ({w['kind']}): [{'; '.join(w['words'])}]")
    if len(ws) > 12:
        out.append(f"    … {len(ws) - 12} more")
    return out


def report(results: list[dict]) -> str:
    out = []
    for r in results:
        if not r['scanned']:
            out.append(f"- {r['file']}: not scanned (binary or typeset output; comments do not reach the page)")
            continue
        if not r['hits']:
            out.append(f"- {r['file']}: referee copy (no comment text)")
            out.extend(_warning_lines(r))
            continue
        bad = [h for h in r['hits'] if h['review_words'] or h['pointer']]
        nbody = sum(1 for h in r['hits'] if h['kind'] == 'body-history')
        out.append(f"- {r['file']}: NOT a referee copy: {len(r['hits']) - nbody} comment(s) with text, "
                   f"{len(bad) - nbody} with review words or pointers, {nbody} body sentence(s) telling the reader "
                   f"the target was reviewed before (stripping cannot remove these: edit the body)")
        for h in (bad or r['hits'])[:12]:
            tag = ', '.join(h['review_words']) or '-'
            out.append(f"    line {h['line']} ({h['kind']}, {h['chars']} chars): review words [{tag}]"
                       f"{', pointer to records' if h['pointer'] else ''}")
        out.extend(_warning_lines(r))
    if any(r['hits'] for r in results):
        out.append(REMEDY)
    if any(h['kind'] == 'body-history' for r in results for h in r['hits']):
        out.append("→ body-history: a receipt sentence in the typeset text reaches every reader; move it to the results "
                   "note, rebuild, and re-run this check (strip-tex-comments.py does not touch the body)")
    return '\n'.join(out)


# ---------- --staged-warn ----------

def staged_review_comments(repo: Path) -> list[dict]:
    """Added lines of staged .tex files whose comment carries review words or a pointer to review records.

    Reads the diff as bytes (a binary or textconv'd file must not crash a warn-only hook; claude-config
    conventions/hook-authoring.md#staged-diff-binary).  Raises RuntimeError when git cannot produce the diff."""
    p = subprocess.run(['git', '-C', str(repo), '-c', 'core.quotepath=false', 'diff', '--cached', '-U0', '--no-color',
                        '--no-ext-diff', '--diff-filter=ACMR', '--', '*.tex'], capture_output=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode('utf-8', 'replace').strip()[:300] or f'git diff rc={p.returncode}')
    hits, path, lineno = [], None, 0
    for raw in p.stdout.split(b'\n'):
        line = raw.decode('utf-8', 'replace')
        if line.startswith('+++ '):
            path = line[6:] if line.startswith('+++ b/') else None
            continue
        if line.startswith('@@'):
            m = re.search(r'\+(\d+)', line)
            lineno = int(m.group(1)) if m else 0
            continue
        if path and line.startswith('+') and not line.startswith('+++'):
            body = line[1:]
            m = TEX_COMMENT.search(body)
            if m and m.group(1).strip():
                d = _describe(m.group(1))
                if d['review_words'] or d['pointer']:
                    hits.append({'file': path, 'line': lineno, **d})
            lineno += 1
    return hits


def staged_warn(repo: Path) -> int:
    try:
        hits = staged_review_comments(repo)
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        print(f"⚠️ check-review-target --staged-warn: could not read the staged diff ({e}); not checked", file=sys.stderr)
        return 3
    if not hits:
        return 0
    print("⚠️ review history in tex comments (commit is not blocked): a review receipt written into the source "
          "enters the next round's target. Put verdicts, finding lists and paths to results in the results note "
          "(claude-config conventions/latex.md#source-comment-scope).", file=sys.stderr)
    for h in hits[:20]:
        tag = ', '.join(h['review_words']) or '-'
        print(f"    {h['file']}:{h['line']} review words [{tag}]{', pointer to records' if h['pointer'] else ''}",
              file=sys.stderr)
    if len(hits) > 20:
        print(f"    … {len(hits) - 20} more", file=sys.stderr)
    return 0


# ---------- selftest ----------

def _selftest() -> int:
    header = ('% !TEX TS-program = lualatex\n'
              '% Blind review (token ABC-20991231-XYZ123, plans/x-results.md): verdict "incorrect"; corrected (1)-(8)\n'
              '\\documentclass{article}\n')
    r = scan(Path('n.tex'), header)
    assert len(r['hits']) == 2 and r['hits'][1]['pointer'] and 'verdict' in r['hits'][1]['review_words'], r
    assert 'incorrect' not in report([r]), 'comment text must never be printed'
    stripped = '\\section{A} %\nfoo\\% not a comment\n\\newcommand{\\z}{%\n  bar}%\ntext'
    assert scan(Path('s.tex'), stripped)['hits'] == [], 'strip-tex-comments output must pass'
    para = '% earlier pass said the peak was wrong; fixed\nx\n'
    assert scan(Path('p.tex'), para)['hits'], 'a paraphrase without review words still fails (predicate = any text)'
    body = ('\\section{Purpose}\nAn independent session reviewed this draft blind; we took the corrections '
            'of that review.\nWe take the results from the review article of Smith and Jones.\n')
    rb = scan(Path('b.tex'), body)
    assert [h['kind'] for h in rb['hits']] == ['body-history'] and rb['hits'][0]['line'] == 2, rb
    assert 'body sentence' in report([rb])
    assert scan(Path('c.tex'), 'from the review article of Smith and Jones~\\cite{x}, and an earlier version of this work')['hits'] == [], \
        'ordinary uses of "review" and "earlier version" in the text are not history'
    assert scan(Path('d.md'), 'This draft was reviewed blind by a second session.')['hits'][0]['kind'] == 'body-history'
    deixis = '\\section{B}\nThe present version retains form A and has dropped form B.\n'
    rd = scan(Path('e.tex'), deixis)
    assert rd['hits'] == [] and [w['kind'] for w in rd['warnings']] == ['revision-deixis'], rd
    assert rd['warnings'][0]['line'] == 2 and 'not refused' in report([rd])
    static = 'The draft of the companion paper retains form A and does not contain form B.\n'
    assert scan(Path('f.tex'), static)['warnings'] == [], 'a static description of another work is not flagged'
    nouns = 'This note derives X.\nA prior version of this paper~\\cite{a} assumed Y.\nWithin this note we keep Z.\n'
    rn = scan(Path('g.tex'), nouns)
    assert rn['hits'] == [] and [(w['line'], w['kind']) for w in rn['warnings']] == [(2, 'self-noun')], rn
    assert scan(Path('h.tex'), 'In this paper we show X.\nThis manuscript is organized as follows.\n')['warnings'] == [], 'synonyms'
    md = 'text\n<!-- reviewer 2 verdict: reject -->\nmore'
    assert scan(Path('a.md'), md)['hits'][0]['line'] == 2
    assert scan(Path('b.pdf'), '')['scanned'] is False
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'n.tex'
        f.write_text(header, encoding='utf-8')
        assert main(['x', str(f)]) == 1
        g = Path(td) / 's.tex'
        g.write_text(stripped, encoding='utf-8')
        assert main(['x', str(g)]) == 0
        w = Path(td) / 'w.tex'
        w.write_text(deixis, encoding='utf-8')
        assert main(['x', str(w)]) == 0, 'warnings do not refuse the target'
        repo = Path(td) / 'repo'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        (repo / 'note.tex').write_text('% version history: section 2 rewritten\n\\section{A}\ntext % layout note\n'
                                       '% received review: verdict major revision, see plans/r-results.md\n',
                                       encoding='utf-8')
        (repo / 'fig.pdf').write_bytes(b'%PDF-1.4\n\xff\xfe binary')
        subprocess.run(['git', '-C', str(repo), 'add', 'note.tex', 'fig.pdf'], check=True)
        got = staged_review_comments(repo)
        assert [h['line'] for h in got] == [4] and got[0]['pointer'] and 'verdict' in got[0]['review_words'], got
        assert staged_warn(repo) == 0, 'warn only: a finding never blocks'
        assert staged_warn(Path(td) / 'not-a-repo') == 3, 'a check that could not run says so'
    print('selftest OK (22 checks)')
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args == ['--selftest']:
        return _selftest()
    if args[:1] == ['--staged-warn']:
        repo = Path(args[args.index('--repo') + 1]) if '--repo' in args else Path.cwd()
        return staged_warn(repo)
    files = [a for a in args if a != '--json']
    if not files or any(a.startswith('--') for a in files):
        print(__doc__)
        return 2
    results = [scan(Path(a).expanduser()) for a in files]
    if '--json' in args:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        print(report(results))
    return 1 if any(r['hits'] for r in results) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
