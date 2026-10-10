#!/usr/bin/env python3
"""Refuse a blind-review target that carries its own history (comment text in .tex / .md / .bib, a body sentence saying the document was reviewed or corrected); warn on review vocabulary and self-reference that may read as history; --staged-warn flags review history written into tex comments at commit time; --selftest.

Why: isolation by file lists (a deny list in the spec, a read-order instruction) cannot stop history written inside
the target itself.  A header comment that records the previous round's verdict, the list of corrections and the path
of the results note reaches every reviewer who opens the target, on any route.  The sealed sandbox strips comments
(strip-tex-comments.py); a route without that step (a board request answered in the repository) carried the
history to the reviewer unchanged (measured).  So this checks the artifact, not the route:
board/board.py request --review-target and make-review-sandbox.py create call it
(conventions/cold-eyes-isolation.md#contamination-channels (d)).

Target check (exit 0 = referee copy, 1 = refused, 2 = usage).  Two predicates refuse:
  comments  .tex = any comment with non-blank text (a line whose first non-blank char is %, or text after an unescaped
            %); .md = any HTML comment with text.  This predicate is the output contract of strip-tex-comments.py, so a
            stripped copy always passes the comment check and a paraphrase in a comment does not.
  body-history  a body sentence that says this document itself was reviewed or corrected: a passive "this / the
            <note|paper|manuscript|draft|…> was reviewed blind / by an independent …", an active "… reviewed this
            manuscript", corrections or comments of a review that "are / have been incorporated", "we incorporated the
            referee's comments", 「本稿は盲検で査読を受け」「査読の指摘を反映」.  Stripping cannot remove it; the author
            moves it to the results note (measured: such a sentence passed the comment check and the blind session
            stopped on its exposure rule, correctly).
Body text is read by sentence, not by line: the lines are joined and split at sentence ends and blank lines (with
common abbreviations such as "Sec." or "et al." kept inside), so a sentence wrapped across a line break is matched as
one, and a finding names the line where its match starts.
Warnings (printed, exit unchanged = the target is not refused; the author decides before the request, rewriting the
sentence or naming the work it means in the spec's subject slot, template/REVIEW-SPEC-blind-manuscript.md §0):
  review-mention   review vocabulary that does not say this document was reviewed ("previous review", "referee
                   reports", "independent session", 「盲検」「査読」): a cited review article, a study of peer review,
                   repeated trials and double-blind trials are content.  Needs a look, never a refusal.
  revision-deixis  a clause whose subject names the document itself ("the present draft", "this version", "the current
                   draft") with a revision verb ("has removed", "no longer uses", "now contains"), without a relative
                   clause in between ("the present paper shows that particles no longer diffuse" does not warn).  It may
                   be the subject (a note about another paper's drafts) or the target's own history; a judging session
                   that stops on history reads it as the latter (measured: such a sentence about a companion paper's
                   draft stopped a blind run).
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
_DOC = r'(?:note|paper|manuscript|draft|version|article|document|text|memo|report)'
_SELF_DOC = r'(?:this|the\s+present|the\s+current|our|the)\s+' + _DOC
BODY_HISTORY = re.compile(   # a body sentence saying this document itself was reviewed or corrected (refused)
    r'(?i)\b' + _SELF_DOC + r'\s+(?:\([^()]{0,80}\)\s+)?(?:\w+\s+){0,2}?(?:was|were|has\s+been|have\s+been|had\s+been|is)\s+(?:\w+\s+){0,2}?'
    r'(?:blind(?:ly)?\s+)?(?:reviewed|refereed)\s+(?:blind(?:ly)?\b|independently\b|by\s+an?\s+(?:independent|separate|second|blind)\b)'
    r'|\b(?:reviewed|refereed)\s+(?:this|the\s+present|our)\s+' + _DOC + r'\b'
    r'|\b(?:corrections?|comments?|suggestions?|findings?)\s+(?:of|from)\s+(?:that|the|this|its|an?)\s+(?:\w+\s+){0,2}?'
    r'(?:review|referee|reviewer|session)s?\b[\s\S]{0,60}?\b(?:are|were|have\s+been|has\s+been)\s+(?:\w+\s+){0,1}?'
    r'(?:incorporated|addressed|implemented|adopted|included)\b'
    r'|\bits\s+(?:corrections?|comments?|findings?)\s+(?:are|were|have\s+been|has\s+been)\s+(?:incorporated|addressed|implemented|adopted)\b'
    r'|\b(?:we|the\s+authors?)\s+(?:have\s+)?(?:incorporated|addressed|implemented|adopted)\s+(?:all\s+)?(?:the\s+)?'
    r'(?:\w+\s+)?(?:referee|reviewer|review)(?:\'s|s\'|s)?\s+(?:comments?|corrections?|suggestions?|findings?|reports?)\b'
    r'|(?:本稿|本ノート|本論文|この(?:ノート|論文|原稿|文書|稿))[^。]{0,40}?(?:盲検|査読|レビュー)[^。]{0,20}?(?:を受け|を経|された|受けた)(?!て?い?な[いく]|ず|ぬ)'
    r'|(?:盲検|査読|レビュー)(?:の|で受けた|で)(?:指摘|訂正|コメント)[^。]{0,20}?(?:反映|取り込|組み込)')
REVIEW_MENTION = re.compile(   # review vocabulary that may be content or history (warned, never refused)
    r'(?i)\b(?:reviewed\s+blind|blind(?:ly)?\s+review(?:ed)?|independent\s+session|corrections?\s+of\s+(?:that|the|this)\s+review'
    r'|(?:earlier|previous|first|second)\s+(?:review|round\s+of\s+review)|referee\s+reports?|review\s+records?)\b'
    r'|盲検|査読を受け|査読の指摘|査読で')
_DEIXIS = (r'(?:the|this)\s+present\s+(?:draft|version|paper|note|manuscript|article|work)'
           r'|this\s+(?:draft|version|revision)|the\s+current\s+(?:draft|version)')
REVISION_DEIXIS = re.compile(   # the document as subject of a revision verb in the same clause (warned)
    r'(?i)\b(?P<d>' + _DEIXIS + r')(?:\s+(?!(?:whose|which|that|who|where|when)\b)\S+){0,6}?\s+'
    r'(?P<v>(?:has|have|had|was|were)\s+(?:now\s+)?(?:been\s+)?(?:removed|dropped|deleted|corrected|revised|replaced|rewritten|withdrawn|retracted)'
    r'|no\s+longer\s+(?:uses?|keeps?|contains?|includes?|states?|reads?|assumes?|has)'
    r'|now\s+(?:uses|keeps|contains|includes|states|reads|drops|omits))\b')
ABBREV = {'al', 'e.g', 'i.e', 'cf', 'vs', 'ref', 'refs', 'eq', 'eqs', 'sec', 'secs', 'fig', 'figs', 'ch', 'app', 'no', 'resp', 'viz',
          'tab', 'thm', 'prop', 'def', 'dr', 'prof', 'mr', 'ms', 'st', 'approx'}
SENT_END = re.compile(r'(?<=[.!?])\s+(?=[A-Z\\(\[“"\'])|(?<=。)|\n[ \t]*\n|\n(?=[ \t]*(?:\\(?:section|subsection|subsubsection|paragraph|begin|end|item|caption)\b|#|[-*+] |\|))')
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


def sentences(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Body lines [(line number, text)] -> sentences [(start offset, text)] over the joined body, so a sentence wrapped
    across a line break is one unit (measured gap: "reviewed" at a line end and "blind" on the next line passed a
    line-by-line scan).  Splits at sentence ends (not after common abbreviations), blank lines and structural line
    starts (sectioning, list items, table rows)."""
    joined = '\n'.join(t for _, t in lines)
    cuts, start = [], 0
    for m in SENT_END.finditer(joined):
        before = joined[max(0, m.start() - 12):m.start()]
        w = re.search(r'([A-Za-z][A-Za-z.]*)\.$', before)
        if w and w.group(1).lower() in ABBREV:
            continue
        cuts.append((start, joined[start:m.start()]))
        start = m.end()
    cuts.append((start, joined[start:]))
    return [(o, t) for o, t in cuts if t.strip()]


def _line_at(lines: list[tuple[int, str]], offset: int) -> int:
    """Line number of a character offset in the joined body."""
    pos = 0
    for n, t in lines:
        if offset <= pos + len(t):
            return n
        pos += len(t) + 1
    return lines[-1][0] if lines else 1


def body_findings(lines: list[tuple[int, str]]) -> tuple[list[dict], list[dict]]:
    """(hits, warnings) for body lines [(line number, text without comments)], matched per sentence.  Hits = body-history
    (refused); warnings = review-mention, revision-deixis, self-noun.  Only matched words are reported, never the sentence."""
    hits, out = [], []
    nouns: dict[str, list[int]] = {}
    for off, sent in sentences(lines):
        b = BODY_HISTORY.search(sent)
        if b:
            hits.append({'line': _line_at(lines, off + b.start()), 'kind': 'body-history',
                         'review_words': [' '.join(b.group(0).lower().split())[:60]], 'pointer': False, 'chars': len(sent.strip())})
        else:
            r = REVIEW_MENTION.search(sent)
            if r:
                out.append({'line': _line_at(lines, off + r.start()), 'kind': 'review-mention',
                            'words': [' '.join(r.group(0).lower().split()), 'content or this document\'s history? decide']})
        d = REVISION_DEIXIS.search(sent)
        if d:
            out.append({'line': _line_at(lines, off + d.start()), 'kind': 'revision-deixis',
                        'words': [' '.join(d.group('d').lower().split()), ' '.join(d.group('v').lower().split())]})
        for m in SELF_NOUN.finditer(sent):   # synonyms count as one self-name (a paper says "this paper" and "this manuscript")
            nouns.setdefault(NOUN_CLASS[m.group(1).lower()], []).append(_line_at(lines, off + m.start()))
    if len(nouns) > 1:
        ranked = sorted(nouns.items(), key=lambda kv: -len(kv[1]))
        top, n_top = ranked[0][0], len(ranked[0][1])
        tie = sum(1 for _, v in ranked if len(v) == n_top) > 1
        for noun, where in ranked[(0 if tie else 1):]:
            for i in sorted(set(where)):
                out.append({'line': i, 'kind': 'self-noun',
                            'words': [f'a "this {noun}"-class self-name', f'elsewhere "this {top}" x{n_top}' if not tie else 'self-nouns tied']})
    return hits, sorted(out, key=lambda w: w['line'])


def scan(path: Path, text: str | None = None) -> dict:
    """{'file', 'scanned', 'hits': [{'line', 'kind', 'review_words', 'pointer', 'chars'}], 'warnings': [{'line', 'kind', 'words'}]}"""
    suffix = path.suffix.lower()
    if suffix not in ('.tex', '.md', '.bib'):
        return {'file': str(path), 'scanned': False, 'hits': [], 'warnings': []}
    if text is None:
        text = path.read_text(encoding='utf-8', errors='replace')
    hits = []
    bodies: list[tuple[int, str]] = []
    if suffix == '.bib':
        # comment lines between entries and @comment entries carry the author's reasons for a reference (which
        # round asked for it, where the source note is); inside an entry % is a literal, so only whole lines count
        for i, line in enumerate(text.split('\n'), 1):
            if line.lstrip().startswith('%') and line.lstrip('% \t'):
                hits.append({'line': i, 'kind': 'comment-line', **_describe(line.lstrip().lstrip('%'))})
            elif re.match(r'^\s*@comment\b', line, re.IGNORECASE):
                hits.append({'line': i, 'kind': 'comment-entry', **_describe(line)})
        return {'file': str(path), 'scanned': True, 'hits': hits, 'warnings': []}   # no body prose in a .bib
    if suffix == '.tex':
        for i, line in enumerate(text.split('\n'), 1):
            m = TEX_COMMENT.search(line)
            if m and m.group(1).strip():
                full = line.lstrip().startswith('%')
                hits.append({'line': i, 'kind': 'comment-line' if full else 'trailing-comment', **_describe(m.group(1))})
            bodies.append((i, TEX_COMMENT.sub('', line)))
    else:
        for m in MD_COMMENT.finditer(text):
            if m.group(1).strip():
                hits.append({'line': text.count('\n', 0, m.start()) + 1, 'kind': 'html-comment', **_describe(m.group(1))})
        kept = MD_COMMENT.sub(lambda m: '\n' * m.group(0).count('\n'), text)   # keep line numbers
        bodies = list(enumerate(kept.split('\n'), 1))
    body_hits, warnings = body_findings(bodies)
    return {'file': str(path), 'scanned': True, 'hits': sorted(hits + body_hits, key=lambda h: h['line']), 'warnings': warnings}


def _warning_lines(r: dict) -> list[str]:
    ws = r.get('warnings') or []
    if not ws:
        return []
    out = [f"  ⚠️ {len(ws)} warning(s), not refused: a sentence that may read as the target's own history. "
           "Decide whether it is content or history: rewrite it to name the work it means, or name that work in the spec's subject slot (§0)"]
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
    bib = '% added after round 2 asked for it (plans/x.md)\n@article{k,\n  title = "{A}",\n  note = "{p.3 % literal}",\n}\n'
    rbib = scan(Path('r.bib'), bib)
    assert [h['kind'] for h in rbib['hits']] == ['comment-line'] and rbib['hits'][0]['line'] == 1, rbib
    assert scan(Path('c.bib'), bib.split('\n', 1)[1])['hits'] == [], 'a % inside a field value is not a comment'
    assert scan(Path('e.bib'), '@Comment{see the referee report}\n')['hits'][0]['kind'] == 'comment-entry'
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
    # pairs (synthetic): each sentence on one line and wrapped across a line break must give the same result
    def kinds(text, key='hits'):
        return [h['kind'] for h in scan(Path('x.tex'), text)[key]]
    receipts = ['This manuscript was reviewed blind and revised accordingly.',
                'An independent session reviewed this manuscript blind; its corrections have been incorporated.',
                'The corrections of that review have been incorporated throughout.',
                '本稿は盲検で査読を受け、その指摘を反映した。']
    for r in receipts:
        wrapped = r.replace(' blind', '\nblind', 1) if ' blind' in r else r.replace('盲検で', '盲検で\n', 1).replace(' have been', '\nhave been', 1)
        assert kinds(r) == ['body-history'] and kinds(wrapped) == ['body-history'], (r, kinds(r), kinds(wrapped))
    content = ['The previous review by Smith gives an exhaustive account of finite-size corrections.',
               'We analyze anonymized referee reports to quantify reviewer disagreement.',
               'We estimate independent session effects in repeated psychometric trials.',
               '二重盲検試験により治療効果を推定する。',
               '本稿は査読前の preprint で、独立追試・査読を経ていない。',
               'The protocol of Ref.~\\cite{x} was reviewed by its own ethics board.']
    for c in content:
        assert kinds(c) == [] and kinds(c.replace(' ', '\n', 2)) == [], (c, kinds(c))   # never refused, wrapped or not
    assert kinds(content[0], 'warnings') == ['review-mention'], 'general review words get a look, not a refusal'
    deixis_pair = ['The present draft has removed the disputed assumption.', 'The present draft\nhas removed the disputed assumption.']
    assert all(kinds(t, 'warnings') == ['revision-deixis'] for t in deixis_pair), [kinds(t, 'warnings') for t in deixis_pair]
    for plain in ['The present paper shows that particles no longer diffuse after freezing.',
                  'The present work derives a limit in which the medium no longer amplifies fluctuations.',
                  'The present manuscript models particles whose charge has changed after a collision.']:
        assert kinds(plain, 'warnings') == [], (plain, kinds(plain, 'warnings'))   # the document is not the subject
    assert kinds('This note (see Sec. 2 and Ref.~\\cite{y}) was reviewed blind by a second session.') == ['body-history'], \
        'an abbreviation does not split the sentence'
    assert scan(Path('w.tex'), 'Intro text.\n\nThis manuscript was reviewed\nblind.')['hits'][0]['line'] == 3, 'line of the match'
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
    print('selftest OK (28 checks)')
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
