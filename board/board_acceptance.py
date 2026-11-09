#!/usr/bin/env python3
"""board_acceptance.py — a one-line notice for a request whose --acceptance lists a page count or overfull boxes
without a value to pass or fail. See CONTRACT.md#acceptance-value-check.

Why: a request that asks for a prose or notation edit of a manuscript and lists "page count" next to pass/fail items
("undefined references 0, overfull 0, page count") gives the receiver no value to compare with. The receiver then
reads the value from the previous report as the expected one, and when an edit moves a line onto the next page it
starts investigating a change that is the normal result of editing text (measured). The rule that page counts and
overfull boxes are not a gate of an edit pass was written down, but requests written afterwards still copied the old
form from earlier requests: a written rule does not reach a writer who copies a previous request (measured). So the
notice is shown to the writer at the moment the request is posted. It never refuses a post: a request with a real
page limit (a letter, a form, a proposal) or a rebuild whose output must not change has a value to write, and is told
how to write it.

What it flags (in --acceptance only):
- a page count term (頁数, ページ数, 総頁数, page count, number of pages) with no value next to it: no number of pages
  ("27 頁", "page count 12"), no limit word (上限, 以内, 以下, limit, at most, ...), no "report only" word (報告だけ,
  参考, report only, ...) and no "do not check" word (見ない, 使わない, not a gate, ...);
- an overfull / underfull term with no "report only" word, no "do not check" word and no final-pass word (final pass,
  投稿直前, 投稿前の清掃, ...). "overfull 0" is flagged too: it has a value, but overfull boxes are not a gate before the
  final pass (conventions/edit-intent-record.md#overfull-not-a-gate).

Rule the notice points to = conventions/edit-intent-record.md#page-count-not-a-gate. The engine prints the notice from
`board.py request` (stderr) and keeps nothing.

    python3 board_acceptance.py --selftest
    python3 board_acceptance.py --check '<acceptance text>'     # print the notice (or nothing) for one text
"""
import argparse
import re
import sys

RULE = 'ai-collaboration conventions/edit-intent-record.md#page-count-not-a-gate'

PAGE_TERM = re.compile(r'頁数|ページ数|総頁|(?i:\bpage[- ]?counts?\b|\bnumber of pages\b)')
OVERFULL_TERM = re.compile(r'(?i:\b(?:overfull|underfull)\b|はみ出し)')
# A value next to a page count term: a number of pages, a number right after the term, or a limit word.
PAGE_NUMBER = re.compile(r'\d+\s*(?:頁(?!数)|ページ(?!数)|枚|(?i:pages?\b|pp?\.))')   # "未定義 0 頁数" is not "0 頁"
NUMBER_AFTER_TERM = re.compile(r'^\s*(?:[:：=＝]|は|が|を|(?i:is|of))?\s*\d')
LIMIT = re.compile(r'上限|以内|以下|未満|超えない|超えず|収まる|収める|(?i:\blimit|\bat most\b|\bno more than\b|\bmaximum\b|\bwithin\b)|≤|<=')
# Words that say the item is not a pass/fail item.
REPORT_ONLY = re.compile(r'報告だけ|報告のみ|参考|記録だけ|記録のみ|数だけ|(?i:\breport(?:ed)? only\b|\bfor reference\b|\binformational\b)')
NOT_CHECKED = re.compile(r'見ない|問わない|使わない|使っていない|入れない|気にしない|調べない|合否にしない|不要|要らない|除く|外す|外し'
                         r'|(?i:\bnot a gate\b|\bignore|\bdo not check\b|\bdon\'t check\b|\bnot checked\b)')
FINAL_PASS = re.compile(r'投稿直前|投稿前の清掃|最終の?\s*pass|(?i:\bfinal pass\b|\bsubmission cleanup\b)')
BOUNDARY = re.compile(r'[。\n;；]')
WINDOW = 30


def _window(text, start, end):
    """The text within WINDOW characters of [start, end), cut at a sentence boundary on either side."""
    lo = max(0, start - WINDOW)
    hi = min(len(text), end + WINDOW)
    before = text[lo:start]
    after = text[end:hi]
    b = list(BOUNDARY.finditer(before))
    if b:
        before = before[b[-1].end():]
    a = BOUNDARY.search(after)
    if a:
        after = after[:a.start()]
    return before, after


def unvalued_terms(text):
    """(page, overfull): whether the text lists a page count without a value, and overfull boxes as a gate."""
    text = text or ''
    page = False
    for m in PAGE_TERM.finditer(text):
        before, after = _window(text, m.start(), m.end())
        near = before + m.group(0) + after
        if (PAGE_NUMBER.search(near) or NUMBER_AFTER_TERM.match(after) or LIMIT.search(near)
                or REPORT_ONLY.search(near) or NOT_CHECKED.search(after)):
            continue
        page = True
        break
    overfull = False
    for m in OVERFULL_TERM.finditer(text):
        before, after = _window(text, m.start(), m.end())
        near = before + m.group(0) + after
        if REPORT_ONLY.search(near) or NOT_CHECKED.search(after) or FINAL_PASS.search(near):
            continue
        overfull = True
        break
    return page, overfull


def acceptance_value_note(acceptance, rule=RULE):
    """One notice line for an --acceptance that lists a page count without a value or overfull boxes as a gate, or ''."""
    page, overfull = unvalued_terms(acceptance)
    if not (page or overfull):
        return ''
    what = '・'.join(x for x, on in (('値の無い頁数', page), ('overfull', overfull)) if on)
    parts = [f"⚠️ 完了条件 (--acceptance) に {what} がある"]
    if page:
        parts.append("文を直せば頁数も頁割りも動き、 それは不具合でない。 値の無い頁数を書くと、 受け手は前の報告の値を期待値と読み、"
                     " 変われば原因を調べ始める (実測)。 頁数を合否に使うのは、 出力が同じはずの組み直しと、 頁の上限があるときだけで、"
                     " そのときは期待する頁数か上限を書く。 英文・記法の直しでは頁数を報告させもしない")
    if overfull:
        parts.append("overfull は投稿直前の final pass まで合否にしない (数を知りたいだけなら「報告だけ」 と書く)")
    return ': '.join(parts[:1]) + ' — ' + '。 '.join(parts[1:]) + f" (規則 = {rule})"


def selftest():
    fails = []

    def check(name, cond):
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            fails.append(name)

    def flags(text):
        return unvalued_terms(text)

    # The form that started the rule: a page count with no value in a list of pass/fail items.
    check('unvalued page count in a pass/fail list', flags('(4) 確かめ: LuaLaTeX で組んで頁数・未定義の参照 0・overfull 0、 PDF の差分') == (True, True))
    check('bracketed build list', flags('組版 (未定義 0・overfull 0・頁数) を submit に') == (True, True))
    check('same page count before and after (no number)', flags('頁数が前後で同じであること') == (True, False))
    check('page count to report (not marked report only)', flags('PDF の頁数を submit に書く') == (True, False))
    check('English page count', flags('build passes, page count unchanged, no undefined refs') == (True, False))
    check('overfull 0 alone', flags('overfull 0 と未定義参照 0') == (False, True))
    # Requests with a value or a reason: no notice.
    check('page limit', flags('letter の上限 4 頁を超えない頁数') == (False, False))
    check('page limit without a number', flags('頁数は様式の上限を超えない') == (False, False))
    check('number of pages', flags('arXiv の package を組み直して頁数 27 のまま (出力が同じはず)') == (False, False))
    check('number of pages before the term', flags('組み直しても 27 頁の頁数') == (False, False))
    check('a zero before the term is not a number of pages', flags('未定義 0 頁数') == (True, False))
    check('English limit', flags('page count at most 4 (journal limit)') == (False, False))
    check('report only', flags('頁数は報告だけ') == (False, False))
    check('report only, English', flags('page count (report only)') == (False, False))
    check('not checked', flags('頁数は見ない、 overfull は気にしない') == (False, False))
    check('overfull report only', flags('overfull は報告だけ (数と行番号)') == (False, False))
    check('overfull at the final pass', flags('投稿直前の final pass で overfull を消す') == (False, False))
    check('no build terms', flags('commit + push、 掲示板で submit') == (False, False))
    check('empty', flags(None) == (False, False))
    # A value in another sentence does not count for this one.
    check('value in another sentence', flags('letter の上限は 4 頁。 組版は頁数・未定義 0') == (True, False))
    # 'pages' alone (a web page, GitHub Pages) is not a page count term.
    check('GitHub Pages is not a page count', flags('GitHub Pages に deploy して pages を確かめる') == (False, False))
    # The note: one line, names what fired and the rule.
    n = acceptance_value_note('組版 (未定義 0・overfull 0・頁数)')
    check('note names both', '値の無い頁数・overfull' in n and RULE in n and '\n' not in n)
    check('note page only', 'overfull は投稿直前' not in acceptance_value_note('頁数が前後で同じ'))
    check('note overfull only', '値の無い頁数' not in acceptance_value_note('overfull 0'))
    check('no note', acceptance_value_note('頁数は報告だけ') == '')
    print('selftest:', 'FAIL ' + ', '.join(fails) if fails else 'ALL PASS')
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--check', metavar='TEXT', help='print the notice for one acceptance text (nothing if none)')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.check is not None:
        n = acceptance_value_note(a.check)
        if n:
            print(n)
        return 0
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
