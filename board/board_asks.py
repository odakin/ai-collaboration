#!/usr/bin/env python3
"""board_asks.py — questions an agent puts to the board's owner, and the owner's answers. See CONTRACT.md#owner-asks.

Why: an agent that asks its owner several things in one reply labels them itself (1 2 3, A B C), and labels it
invents restart in every reply. The owner answers by label or by position ("1 and 2 OK"), often to an earlier reply
than the latest, and the same question re-asked in another window gets a different label each time. The agent then
binds the answer to the wrong item and acts on it in the same turn (measured). Answers also fade: a context
compaction folds answered questions into a one-line "done" (measured).

What it is:
- An **ask** is one question the owner must answer. The board, not the agent, gives it a label: a letter fixed per
  machine plus that machine's running number (`H12`), never reused, so the same question keeps one label in every
  window and on every day. The ask carries the question, the recommended answer, why it needs the owner (the
  **ground**), and keys naming the question (`todo:<repo>:<id>` = the one question a TODO carries, `plan:<path>#<item>`,
  `request:<id>`). **A key names one question**: an open ask with the same key is shown again under its label, and a
  question already answered under that key is not asked again (the earlier answer is printed; `--reask` with a reason
  asks anew).
- Before an ask is made it passes a **gate**: the ground must be one the owner alone can decide (GROUNDS); a policy
  check before implementation is asked once per request, by the session that posted the request; and a change named
  by `--evidence` is judged by a validator whatever the ground — a change that needs no ruling is refused ("apply it
  and report"), including asks to ratify such a change (measured). The validator is a separate program
  (`BOARD_ASKS_VALIDATOR`, default = `owner-ask-validate.py` in a sibling `claude-config/scripts/`) so this engine does
  not depend on any one user's protection engines: without one, such asks are made and the output says the gate could
  not judge.
- An **answer** records the owner's words verbatim, the labels it was bound to and how: `label` (the owner wrote a
  label this session showed), `order` (a position in the only ask block of the latest reply), `confirmed` (the owner
  confirmed the reading the agent stated), or `guess` (no safe binding: candidates listed). An answer that only defers
  ("H2 は後で") is recorded and leaves the ask open. While a session's latest answer is a guess with an open candidate,
  the tool check stops effective actions (sending, recording a decision, messaging or starting another session,
  closing a session); only the owner's next words settle it (the CLI refuses a settling answer while a guess is
  pending; the binding hook records the owner's words).
- A **withdraw** closes an ask decided elsewhere. **shown** records which asks a session displayed.

Store: an append-only JSON-lines ledger local to the board checkout and shared by every session on the machine
(`<board>/.local/asks.jsonl`, else `<git common dir>/board-asks/<board subdir>.jsonl`; `BOARD_ASKS_LEDGER` overrides).
Readers need no network: a board post fetches and pushes (seconds each), which a check on every prompt cannot afford.
Mirroring the ledger to other machines is not in this version. The label letter is `BOARD_ASKS_PREFIX`; the hook entry
passes it and the engine keeps it next to the ledger (`<ledger>.prefix`), so an `ask` run by hand uses the same letter;
without either, Q.

CLI:
    python3 board_asks.py ask      --root <board> --text '<question>' --recommend '<answer>' --ground <g> [--key K]...
                                   [--evidence <repo>@<rev>:<path>] [--applied] [--reask '<what changed>'] [--project P] [--json]
    python3 board_asks.py answer   --root <board> --label H12 [--label …] --quote '<owner words>' --binding label|order|confirmed|guess
                                   [--reading '<one line>'] [--recorded <path or repo@commit>]
    python3 board_asks.py withdraw --root <board> --label H12 --reason '<why>'
    python3 board_asks.py list     --root <board> [--open] [--session S] [--json]
    python3 board_asks.py show     --root <board> --label H12
    python3 board_asks.py digest   --root <board> --session S [--max-chars 8000]
    python3 board_asks.py hook-prompt|hook-pretool|hook-stop|hook-precompact|hook-sessionstart --root <board>
                                   (Claude Code hook JSON on stdin, hook JSON or text on stdout; the hook entry files call these)
    python3 board_asks.py --selftest
Grounds: protected | rule | outbound | choice | policy | fact (meanings in GROUNDS). Exit of `ask`: 0 = at least one
ask made or shown again, 3 = none (refused by the gate, or already answered: the earlier answer is printed instead).
The session is `--session`, else CLAUDE_CODE_SESSION_ID / CODEX_THREAD_ID. Effective actions are configurable
(BOARD_ASKS_EFFECT_TOOLS / _BASH / _PATHS, newline-separated regexes that replace the defaults).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: no advisory lock; appends stay small
    fcntl = None

HERE = Path(__file__).resolve().parent
GROUNDS = {
    'protected': '本人の文書の保護された箇所 (原稿の題・要旨・序論・結論・式など)',
    'rule': '規則の文書の変更で事前の裁定が要るもの・設定・hook',
    'outbound': '外への発信 (送信・投稿・公開) の承認',
    'choice': '本人が選ぶもの (共同研究者の提案を採るか・案の間の好み・お金・家庭・人に連絡する・常駐させる)',
    'policy': '実装の前の方針の確認 (1 つの依頼に 1 回、 依頼元が立てる)',
    'fact': '本人しか知らない事実',
}
JUDGED = ('rule', 'protected')
BINDINGS = ('label', 'order', 'confirmed', 'guess')
SETTLED = ('label', 'order', 'confirmed')
LABEL_RE = re.compile(r'(?<![A-Za-z0-9])([A-Z])(\d{1,5})(?![0-9])')
BLOCK_RE = re.compile(r'〔問\s*([A-Z]\d{1,5})〕')
MAX_TEXT = 600
MAX_QUOTE = 1500
VALIDATOR_TIMEOUT = 30


# ---------- store ----------

def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def ledger_path(root=None):
    env = os.environ.get('BOARD_ASKS_LEDGER')
    if env:
        return Path(os.path.expanduser(env))
    root = Path(root or '.').expanduser().resolve()
    sub = ''
    with contextlib.suppress(Exception):
        sys.path.insert(0, str(HERE))
        import board_config as bc
        sub = bc.subdir(root) or ''
    if not sub and (root / '.local').is_dir():
        return root / '.local' / 'asks.jsonl'
    common = subprocess.run(['git', '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                            capture_output=True, text=True)
    if common.returncode:
        raise ValueError(f'{root}: not a board checkout (no .local/ and not a git repository); set BOARD_ASKS_LEDGER')
    return Path(common.stdout.strip()) / 'board-asks' / ((sub.replace('/', '_') or 'root') + '.jsonl')


@contextlib.contextmanager
def _locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.lock', 'a') as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_UN)


def load(path):
    out = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                with contextlib.suppress(ValueError):
                    rec = json.loads(line)
                    if isinstance(rec, dict) and rec.get('type'):
                        out.append(rec)
    except FileNotFoundError:
        pass
    return out


def _append(path, recs):
    if not recs:
        return
    with open(path, 'a', encoding='utf-8') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def prefix(path=None):
    """The machine's label letter: BOARD_ASKS_PREFIX (kept next to the ledger when given), else the kept letter, else Q.
    Not the host name's letter: hosts named Mac… give M, and chip names (M4, M5) then read as labels (measured)."""
    p = (os.environ.get('BOARD_ASKS_PREFIX') or '').strip().upper()
    keep = Path(str(path) + '.prefix') if path else None
    if re.fullmatch(r'[A-Z]', p):
        if keep:
            with contextlib.suppress(OSError):
                if not keep.exists() or keep.read_text().strip() != p:
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    keep.write_text(p)
        return p
    if keep:
        with contextlib.suppress(OSError):
            kept = keep.read_text().strip().upper()
            if re.fullmatch(r'[A-Z]', kept):
                return kept
    return 'Q'


def _next_label(recs, pfx):
    n = 0
    for r in recs:
        m = LABEL_RE.fullmatch(r.get('label') or '')
        if r.get('type') == 'ask' and m and m.group(1) == pfx:
            n = max(n, int(m.group(2)))
    return f'{pfx}{n + 1}'


def state(recs):
    """label -> ask record + status (open | answered | withdrawn) + answers (in order)."""
    asks = {}
    for r in recs:
        t = r.get('type')
        if t == 'ask':
            asks[r['label']] = dict(r, status='open', answers=[])
        elif t == 'answer':
            for lb in (r.get('labels') or []) + (r.get('candidates') or []):
                a = asks.get(lb)
                if a is None or r in a['answers']:
                    continue
                a['answers'].append(r)
                if (r.get('binding') in SETTLED and not r.get('defer') and lb in (r.get('labels') or [])
                        and a['status'] == 'open'):
                    a['status'] = 'answered'
        elif t == 'withdraw':
            a = asks.get(r.get('label'))
            if a is not None and a['status'] == 'open':
                a['status'] = 'withdrawn'
    return asks


def shown_by(recs, session):
    """Labels this session made, showed again, printed or answered, in first-seen order."""
    out = []
    for r in recs:
        if r.get('session') != session:
            continue
        if r.get('type') == 'ask':
            labels = [r['label']]
        elif r.get('type') in ('shown', 'answer'):
            labels = (r.get('labels') or []) + (r.get('candidates') or [])
        else:
            continue
        for lb in labels:
            if lb not in out:
                out.append(lb)
    return out


def pending_guess(recs, session, st=None):
    """This session's latest answer when it is a guess with at least one candidate still open (None otherwise)."""
    last = None
    for r in recs:
        if r.get('type') == 'answer' and r.get('session') == session:
            last = r
    if not last or last.get('binding') != 'guess':
        return None
    st = st if st is not None else state(recs)
    if not any(st.get(lb, {}).get('status') == 'open' for lb in last.get('candidates') or []):
        return None   # every candidate was answered or withdrawn elsewhere: nothing is left to bind
    return last


def _last_settled(a):
    return next((x for x in reversed(a.get('answers') or [])
                 if x.get('binding') in SETTLED and not x.get('defer') and a['label'] in (x.get('labels') or [])), {})


# ---------- the gate ----------

def _validator():
    env = os.environ.get('BOARD_ASKS_VALIDATOR')
    if env:
        return Path(os.path.expanduser(env))
    return HERE.parent.parent / 'claude-config' / 'scripts' / 'owner-ask-validate.py'


def gate(ground, evidence=None, *, applied=False, validator=None):
    """(ok, message). ok=False = do not ask; the message says why and what to do instead. A change named by evidence is
    judged whatever the ground (a rule change asked under another ground passes the same validator)."""
    if ground not in GROUNDS:
        return False, f'裁定が要る理由が無い・一覧に無い ({ground!r})。 理由 = {", ".join(GROUNDS)}。 どれでもなければ問わずに決めて報告する'
    if not evidence:
        if ground in JUDGED:
            return False, (f'理由 {ground} には変更の在りか (--evidence <repo>@<commit>:<path> か <repo>@worktree:<path>) が要る'
                           ' (裁定の要否を機械で判定するため)')
        return True, ''
    kind = ground if ground in JUDGED else ('protected' if re.search(r'\.tex$', evidence) else 'rule')
    v = Path(validator) if validator else _validator()
    if not v.exists():
        return True, f'⚠️ 判定の道具が無い ({v}) = 裁定の要否を確かめずに立てた'
    args = [sys.executable, str(v), '--ground', kind, '--evidence', evidence] + (['--applied'] if applied else [])
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=VALIDATOR_TIMEOUT)
        res = json.loads((p.stdout or '').strip().splitlines()[-1] if (p.stdout or '').strip() else '{}')
    except (subprocess.TimeoutExpired, ValueError, OSError) as e:
        return True, f'⚠️ 判定の道具が答えない ({e.__class__.__name__}) = 裁定の要否を確かめずに立てた'
    if res.get('error'):
        return False, f'変更の在りかを判定できない: {res["error"]} (在りかを直して立て直す)'
    if 'ok' not in res:
        return True, f'⚠️ 判定の道具の出力が読めない = 裁定の要否を確かめずに立てた ({(p.stderr or "")[:200]})'
    return bool(res['ok']), str(res.get('message') or '')


def _request_authors(root, request_id):
    """Ids that stand for the session that posted this request: actor.session_id and any 8-hex id in actor.task
    (a request posted under a role id keeps the native id there). [] when it cannot be read here."""
    if not root or not request_id:
        return []
    root = Path(root).expanduser()
    roots = [root]
    with contextlib.suppress(Exception):
        sys.path.insert(0, str(HERE))
        import board_config as bc
        roots += [b['root'] for b in bc.discover(root.parent) if Path(b['root']).resolve() != root.resolve()]
    files = [f for r in roots for f in Path(r).glob(f'events/*/*/*--{request_id}.json')]
    for f in files:
        with contextlib.suppress(OSError, ValueError):
            ev = json.loads(f.read_text(encoding='utf-8'))
            if ev.get('kind') == 'request':
                actor = ev.get('actor') or {}
                ids = [actor.get('session_id') or '']
                ids += re.findall(r'(?<![0-9a-f])[0-9a-f]{8}(?![0-9a-f])', str(actor.get('task') or ''))
                return [i for i in ids if i]
    return []


def _same_session(a, b):
    a, b = a or '', b or ''
    return bool(a) and bool(b) and (a == b or a[:8] == b[:8])


def _norm(t):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', t or ''))


# ---------- operations ----------

def _me(session):
    return session or os.environ.get('CLAUDE_CODE_SESSION_ID') or os.environ.get('CODEX_THREAD_ID') or 'unknown'


def _decide(root, st, it, me):
    """What to do with one item before the gate: (status, payload). status = answered-before | reused | refused | ask."""
    text = (it.get('text') or '').strip()[:MAX_TEXT]
    keys = [k for k in (it.get('keys') or []) if k]
    prior = [a for a in st.values() if a['status'] == 'answered' and keys and set(keys) & set(a.get('keys') or [])]
    if prior and not it.get('reask'):
        a = max(prior, key=lambda a: _last_settled(a).get('created_at', ''))
        ans = _last_settled(a)
        if _norm(a['text']) == _norm(text):
            return 'answered-before', {'status': 'answered-before', 'label': a['label'], 'text': a['text'], 'quote': ans.get('quote', ''),
                                       'message': ('同じ問い (同じ key・同じ文) に本人の答えが既にある = 問わずにその答えで進める。'
                                                   ' 状況が変わって問い直すなら --reask \'<何が変わったか>\'')}
        return 'refused', {'status': 'refused', 'text': text, 'label': a['label'], 'quote': ans.get('quote', ''), 'message': (
            f'同じ key の前の問い 〔問 {a["label"]}〕 「{a["text"][:80]}」 に本人の答え「{ans.get("quote", "")[:120]}」 がある。'
            ' その答えで足りるなら問わずに進める。 別の問いなら key を問いごとに分ける (例: <key>#2)。'
            ' 前提が変わった問い直しなら --reask \'<何が変わったか>\'')}
    if it.get('ground') == 'policy':
        rids = [k.split(':', 1)[1] for k in keys if k.startswith('request:')]
        if not rids:
            return 'refused', {'status': 'refused', 'text': text, 'message': '方針の確認の問いには --key request:<依頼の id> が要る (1 つの依頼に 1 回だけ)'}
        authors = _request_authors(root, rids[0])
        if not authors:
            return 'refused', {'status': 'refused', 'text': text, 'message': (
                f'依頼 {rids[0]} の event を手元の掲示板 (--root と、 その隣の掲示板) で見つけられない ='
                ' 依頼元が立てているかを確かめられない。 依頼の掲示板を最新にしてから立て直す')}
        if not any(_same_session(x, me) for x in authors):
            return 'refused', {'status': 'refused', 'text': text, 'message': (
                f'方針の確認の問いは依頼元 ({authors[0][:24]}) が 1 つの依頼に 1 回だけ立てる。'
                ' worker の方針の中の個々の選択は依頼元の検収で決める (本人に立てない)')}
    same = next((a for a in st.values() if a['status'] == 'open' and keys and set(keys) & set(a.get('keys') or [])), None)
    if same:
        if _norm(same['text']) == _norm(text):
            return 'reused', {'status': 'reused', 'label': same['label'], 'text': same['text'], 'recommend': same.get('recommend', ''),
                              'message': '同じ問い (同じ key・同じ文) が開いている = 新しく立てずにその印で問う'}
        return 'refused', {'status': 'refused', 'text': text, 'label': same['label'], 'message': (
            f'同じ key の問い 〔問 {same["label"]}〕 「{same["text"][:80]}」 が開いている。'
            ' 同じ問いならその文のまま立て直す (同じ印で出る)。 別の問いなら key を問いごとに分ける (例: <key>#2)。'
            ' 問いを書き換えるなら先に withdraw')}
    if not text:
        return 'refused', {'status': 'refused', 'text': '', 'message': '問いの文が空'}
    note = it.get('_note') or ''
    if it.get('ground') != 'policy' and re.search(r'方針|\bpolicy\b', text, re.I) and '--ground policy' not in note:
        note = ' '.join(x for x in (note, '⚠️ 方針の確認なら --ground policy (依頼元だけが 1 つの依頼に 1 回)') if x)
    return 'ask', dict(it, text=text, keys=keys, _note=note)


def ask(root, items, *, session=None, agent='claude', project='', path=None, validator=None):
    """items = [{text, recommend, ground, keys, evidence, applied, reask}]
    -> [{status: made|reused|answered-before|refused, label?, message}].
    The validator runs outside the ledger lock (it may take seconds); the lock covers only the decision and the append."""
    p = Path(path) if path else ledger_path(root)
    me = _me(session)
    pre = []
    st0 = state(load(p))
    for it in items:
        kind, payload = _decide(root, st0, it, me)
        if kind == 'ask':
            ok, msg = gate(payload.get('ground'), payload.get('evidence'), applied=bool(payload.get('applied')), validator=validator)
            note = payload.get('_note')
            msg = ' '.join(x for x in (msg, note) if x)
            pre.append(('ask', payload, ok, msg))
        else:
            pre.append((kind, payload, None, None))
    out = []
    with _locked(p):
        recs = load(p)
        st = state(recs)
        pfx = prefix(p)
        new = []
        for kind, payload, ok, msg in pre:
            if kind == 'ask':
                again, re_payload = _decide(root, st, payload, me)   # another session may have asked it meanwhile
                if again != 'ask':
                    kind, payload = again, re_payload
            if kind == 'reused':
                new.append({'type': 'shown', 'labels': [payload['label']], 'session': me, 'created_at': now_iso()})
                out.append(payload)
                continue
            if kind in ('answered-before', 'refused'):
                out.append(payload)
                continue
            if not ok:
                out.append({'status': 'refused', 'text': payload['text'], 'message': msg})
                continue
            label = _next_label(recs + new, pfx)
            rec = {'type': 'ask', 'label': label, 'text': payload['text'], 'recommend': (payload.get('recommend') or '').strip()[:MAX_TEXT],
                   'ground': payload['ground'], 'keys': payload['keys'], 'evidence': payload.get('evidence') or '',
                   'applied': bool(payload.get('applied')), 'reask': payload.get('reask') or '', 'gate': msg,
                   'session': me, 'agent': agent, 'project': project, 'created_at': now_iso()}
            new.append(rec)
            out.append({'status': 'made', 'label': label, 'text': rec['text'], 'recommend': rec['recommend'], 'message': msg})
        _append(p, new)
    return out


def format_block(results):
    lines = []
    for r in results:
        if r['status'] in ('made', 'reused'):
            lines.append(f"〔問 {r['label']}〕 {r['text']}")
            if r.get('recommend'):
                lines.append(f"　おすすめ: {r['recommend']}")
            if '⚠️' in r.get('message', '') or '別の問い' in r.get('message', ''):
                lines.append(f"　({r['message']})")
        elif r['status'] == 'answered-before':
            lines.append(f"(問わない) 〔問 {r['label']}〕 {r['text'][:80]} は本人が答え済み: 「{r.get('quote', '')[:200]}」 — {r['message']}")
        else:
            lines.append(f"(立てない) {r.get('text', '')[:80]} — {r['message']}")
    return '\n'.join(lines)


def answer(root, labels, quote, binding, *, reading='', recorded='', session=None, candidates=None, path=None,
           from_hook=False, defer=False):
    """Record an answer. A settling answer while this session has a pending guess comes only from the binding hook
    (the owner's words); a hand-written one is refused."""
    if binding not in BINDINGS:
        raise ValueError(f'binding は {BINDINGS} のどれか')
    p = Path(path) if path else ledger_path(root)
    me = _me(session)
    with _locked(p):
        recs = load(p)
        st = state(recs)
        unknown = [lb for lb in list(labels) + list(candidates or []) if lb not in st]
        if unknown:
            raise ValueError(f'台帳に無い印: {unknown}')
        if binding != 'guess' and not labels:
            raise ValueError('結んだ印が無い (--label)')
        if binding in SETTLED and not from_hook and pending_guess(recs, me, st):
            raise ValueError('結び先の決まらない本人の答えがある間は、 確定の記録は本人の次の発言 (hook) だけが書く。'
                             ' 本人に「〜と読みました。よいですか」 と確かめる')
        rec = {'type': 'answer', 'labels': list(labels) if binding != 'guess' else [], 'quote': (quote or '')[:MAX_QUOTE],
               'binding': binding, 'reading': (reading or '')[:MAX_TEXT], 'recorded': recorded,
               'candidates': list(candidates or []), 'session': me, 'created_at': now_iso()}
        if defer:
            rec['defer'] = True
        _append(p, [rec])
    marker = guess_marker(me)
    if binding == 'guess':
        marker.write_text(rec['created_at'])
    else:
        with contextlib.suppress(FileNotFoundError):
            marker.unlink()
    return rec


def withdraw(root, label, reason, *, session=None, path=None):
    p = Path(path) if path else ledger_path(root)
    with _locked(p):
        if label not in state(load(p)):
            raise ValueError(f'台帳に無い印: {label}')
        rec = {'type': 'withdraw', 'label': label, 'reason': reason, 'session': _me(session), 'created_at': now_iso()}
        _append(p, [rec])
    return rec


def mark_shown(root, labels, *, session=None, path=None):
    p = Path(path) if path else ledger_path(root)
    with _locked(p):
        recs = load(p)
        known = state(recs)
        me = _me(session)
        already = set(shown_by(recs, me))
        labels = [lb for lb in labels if lb in known and lb not in already]
        if labels:
            _append(p, [{'type': 'shown', 'labels': labels, 'session': me, 'created_at': now_iso()}])
    return labels


# ---------- binding the owner's words ----------

ALL_WORDS = ('全部', 'ぜんぶ', 'すべて', '全て', '両方', 'どれも', 'いずれも')
AFFIRM_ONLY = re.compile(r'^\s*(はい|うん|ok|okay|おけ|いいよ|いいです|よし|了解|それで(いい|よい|ok)?|おすすめ(で|どおり)?|推しで|'
                         r'(全部|ぜんぶ|すべて|両方)(おすすめ|推し)?で?(いい|ok)?|送って|進めて|当てて|入れて)'
                         r'\s*(で|です|ね|よ|。|！|!|、|お願い(します)?|ください)*\s*$', re.I)
DEFER_RE = re.compile(r'後で|あとで|保留|待って|考える|考えさせて|まだ決め|検討する|今度')
ORDINAL_RE = re.compile(r'^\s*([0-9]{1,2}|[①-⑳])')
POSITION_RE = re.compile(r'^\s*(上の|下の|前者|後者|最初の|最後の|[一二三四五1-9]つ目|[1-9]番目)')
QTY_ALL_RE = re.compile(r'^\s*[0-9]{1,2}\s*(つ|通|か所|箇所|点|件|本|個)\s*(とも|全部|ぜんぶ|すべて)')
QTY_RE = re.compile(r'^\s*[0-9]{1,2}\s*(つ|通|か所|箇所|点|件|本|個|人|回|日|時|分|月|年|週|枚|頁|行|章|節|円|%)')
NOT_ORDINAL_AFTER = re.compile(r'^[0-9]{1,2}\s*([/:]|[.][0-9])')
CIRCLED = ''.join(chr(0x2460 + i) for i in range(20))   # circled digits one to twenty


def _ordinals(text, n):
    """Positions named at the start of lines (NFKC text): "1 はい / 3 いいえ" = 1 and 3. A two-digit token is a single
    position when it is within the shown count, split into its digits ("１２OK" = 1 and 2) only when both digits are
    distinct positions within the count and the rest of the line is a bare affirmation ("12は違う" may name item 12 of
    another list), and kept whole otherwise (then it is outside the block and the answer is a guess)."""
    nums = []
    for line in text.splitlines():
        m = ORDINAL_RE.match(line)
        if not m or NOT_ORDINAL_AFTER.match(line.strip()) or QTY_RE.match(line):
            continue
        tok = m.group(1)
        if tok in CIRCLED:
            nums.append(CIRCLED.index(tok) + 1)
            continue
        v = int(tok)
        if len(tok) == 2 and v > n:
            a, b = int(tok[0]), int(tok[1])
            rest = line.strip()[len(tok):].strip()
            if 1 <= a <= n and 1 <= b <= n and a != b and (not rest or AFFIRM_ONLY.match(rest)):
                nums.extend([a, b])
                continue
        nums.append(v)
    return [x for i, x in enumerate(nums) if x not in nums[:i]]


def bind(text, shown_now, shown_prev, open_labels, other_numbered_now=False, known=None):
    """Bind the owner's words to asks.
    shown_now / shown_prev = labels displayed in the latest reply / the one before (display order);
    known = labels this session showed at any time (a label the owner writes binds only when it is one of these).
    Returns {'binding': 'label'|'order'|'guess'|'none', 'labels': [...], 'candidates': [...], 'defer': bool}."""
    t = unicodedata.normalize('NFKC', text or '')
    open_set = set(open_labels)
    knownset = set(known or []) | set(shown_now) | set(shown_prev)
    named = []
    for m in LABEL_RE.finditer(t):   # upper case only: "v3" is a version, not a label (measured)
        lb = m.group(1) + str(int(m.group(2)))
        if lb in open_set and lb in knownset and lb not in named:
            named.append(lb)
    first = t.strip().splitlines()[0] if t.strip() else ''
    defer = bool(DEFER_RE.search(first))
    if named:
        return {'binding': 'label', 'labels': named, 'candidates': [], 'defer': defer}
    now = [lb for lb in shown_now if lb in open_set]
    prev = [lb for lb in shown_prev if lb in open_set and lb not in now]
    wants_all = bool(QTY_ALL_RE.match(first)) or (any(w in first for w in ALL_WORDS) and bool(AFFIRM_ONLY.match(first)))
    nums = _ordinals(t, len(now))
    positional = bool(POSITION_RE.match(first))
    affirm = bool(AFFIRM_ONLY.match(first))
    if not (nums or wants_all or positional or affirm):
        return {'binding': 'none', 'labels': [], 'candidates': [], 'defer': False}
    if not now and not prev:
        return {'binding': 'none', 'labels': [], 'candidates': [], 'defer': False}
    safe = bool(now) and not other_numbered_now and not prev and not positional
    if safe and nums and max(nums) <= len(now):
        return {'binding': 'order', 'labels': [now[k - 1] for k in nums], 'candidates': [], 'defer': defer}
    if safe and not nums and (wants_all or (affirm and len(now) == 1)):
        return {'binding': 'order', 'labels': list(now), 'candidates': [], 'defer': defer}
    return {'binding': 'guess', 'labels': [], 'candidates': now + prev, 'defer': False}


NUMBERED_LINE = re.compile(r'^\s*(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*)?(?:[0-9]{1,2}\s*[.)、]|[(][0-9]{1,2}[)]|[①-⑳])'
                           r'|^\s*\|\s*(?:\*\*)?[0-9]{1,2}(?:\*\*)?\s*\|')


def numbered_outside_blocks(text):
    """True when the text has a numbered list, numbered heading or numbered table row besides the ask block lines
    (code excluded; full-width digits and brackets are read as ASCII)."""
    in_code = False
    for line in (text or '').splitlines():
        if line.strip().startswith('```'):
            in_code = not in_code
            continue
        if in_code or BLOCK_RE.search(line):
            continue
        if NUMBERED_LINE.match(unicodedata.normalize('NFKC', line)):
            return True
    return False


# ---------- transcripts (hooks) ----------

NOT_HUMAN = ('<', 'Stop hook feedback', 'Another Claude session sent a message', '[Request interrupted', 'Caveat:',
             'This session is being continued', 'Base directory for this skill')


def _texts(rec):
    t = rec.get('type')
    if t == 'attachment':
        a = rec.get('attachment') or {}
        if a.get('type') == 'queued_command':
            p = a.get('prompt')
            if isinstance(p, str):
                return 'user', [p]
            if isinstance(p, list):
                return 'user', [b.get('text', '') for b in p if isinstance(b, dict) and b.get('type') == 'text']
        return None, []
    if t not in ('user', 'assistant'):
        return None, []
    c = (rec.get('message') or {}).get('content')
    if isinstance(c, str):
        return t, [c]
    if isinstance(c, list):
        if t == 'user' and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c):
            return None, []
        return t, [b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text']
    return None, []


def windows(transcript, tail_bytes=4 << 20):
    """(latest window, previous window) of assistant text, split at the owner's messages (read from the file's tail)."""
    rows = []
    try:
        with open(transcript, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail_bytes))
            data = f.read().decode('utf-8', 'replace').splitlines()
    except OSError:
        return '', ''
    for line in data:
        with contextlib.suppress(ValueError):
            rec = json.loads(line)
            if not isinstance(rec, dict) or rec.get('isSidechain'):
                continue
            role, texts = _texts(rec)
            for tx in texts:
                if role == 'user' and (not tx.strip() or tx.lstrip().startswith(NOT_HUMAN)):
                    continue
                if role:
                    rows.append((role, tx))
    hum = [i for i, (r, _) in enumerate(rows) if r == 'user']
    last = hum[-1] if hum else -1
    prev = hum[-2] if len(hum) > 1 else -1
    w0 = '\n'.join(tx for r, tx in rows[last + 1:] if r == 'assistant')
    w1 = '\n'.join(tx for r, tx in rows[prev + 1:last] if r == 'assistant') if last >= 0 else ''
    return w0, w1


def labels_in(text):
    out = []
    for m in BLOCK_RE.finditer(text or ''):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def bare_labels(text, labels):
    """Which of these labels the text names (block or bare form, e.g. "H1 と読みました")."""
    t = unicodedata.normalize('NFKC', text or '')
    return [lb for lb in labels if re.search(rf'(?<![A-Za-z0-9]){re.escape(lb)}(?![0-9])', t)]


EFFECT_TOOLS_DEFAULT = [r'^SendMessage$', r'send_email$', r'send_message$',
                        r'^mcp__ccd_session_mgmt__(archive|stop|delete|clear)_session$', r'^mcp__ccd_session__start_session$']
EFFECT_BASH_DEFAULT = [r'send_mail\.py\b[^\n]*--send\b', r'discord-post\.py\b[^\n]*--send\b',
                       r'record-reply\.py\b[^\n]*--apply\b', r'yaml-set-top-keys\.py\b',
                       r'(>{1,2}|\btee\b)[^\n|;&]*(/|^)todo/[^/\s]+\.ya?ml\b',
                       r'(\brm\b|\bmv\b|\bcp\b|>{1,2}|\btee\b|\btruncate\b|\bsed\s+-i)[^\n|;&]*(board-asks|asks\.jsonl)']
EFFECT_PATH_DEFAULT = [r'/todo/[^/]+\.ya?ml$', r'(^|/)DESIGN\.md$', r'rulings\.md$', r'decisions?\.md$',
                       r'/board-asks/', r'asks\.jsonl$']
BOARD_CMDS = ('accept', 'request', 'revise', 'handover', 'claim', 'submit', 'note', 'show', 'inbox', 'watch', 'touch',
              'touching', 'untouch', 'release', 'blocker', 'update', 'finding', 'abandoned', 'launch', 'pickup', 'init', 'boards')
BOARD_EFFECT_CMDS = ('accept', 'request', 'revise', 'handover')
ASKS_FREE_CMDS = ('ask', 'list', 'show', 'digest')


def _segments(cmd):
    return [s.strip() for s in re.split(r'\|\||&&|[;|\n]', cmd or '') if s.strip()]


def _tokens(seg):
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def _subcommand(tokens, script):
    i = next((k for k, t in enumerate(tokens) if t.endswith(script)), None)
    if i is None:
        return None
    for k in range(i + 1, len(tokens)):
        t = tokens[k]
        prev = tokens[k - 1]
        if t.startswith('-'):
            continue
        if prev.startswith('--') and '=' not in prev and k - 1 > i:
            continue   # the value of an option (e.g. `--request <id>`)
        return t
    return None


def effect(tool, inp):
    """A short name of the effective action this tool call is, or None."""
    def env_list(name, default):
        v = os.environ.get(name)
        return [x for x in v.split('\n') if x.strip()] if v else default
    if any(re.search(p, tool or '') for p in env_list('BOARD_ASKS_EFFECT_TOOLS', EFFECT_TOOLS_DEFAULT)):
        return tool
    if tool == 'Bash':
        cmd = (inp or {}).get('command') or ''
        pats = env_list('BOARD_ASKS_EFFECT_BASH', EFFECT_BASH_DEFAULT)
        for seg in _segments(cmd):
            toks = _tokens(seg)
            if any(t.endswith('board_asks.py') for t in toks):
                if _subcommand(toks, 'board_asks.py') in ASKS_FREE_CMDS:
                    continue   # asking, listing and reading the ledger are never stopped
                return 'Bash (board_asks.py)'   # answer / withdraw would settle or close a pending guess by hand
            if re.search(r'board_asks\b[^\n]*\b(answer|withdraw)\b', seg):
                return 'Bash (board_asks)'
            if any(t.endswith('board.py') for t in toks) and _subcommand(toks, 'board.py') in BOARD_EFFECT_CMDS:
                return 'Bash (board.py)'
            if any(re.search(p, seg) for p in pats):
                return 'Bash'
        return None
    if tool in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        fp = (inp or {}).get('file_path') or ''
        return f'{tool} {fp}' if any(re.search(p, fp) for p in env_list('BOARD_ASKS_EFFECT_PATHS', EFFECT_PATH_DEFAULT)) else None
    return None


ASK_RE = re.compile(r'決めてほしい|決めてください|答えてください|教えてください|してよいですか|でよいですか|よいですか|いいですか|どうしますか|はい\s*[/／]\s*直す|ご判断')


def _state_dir():
    d = Path(os.environ.get('BOARD_ASKS_STATE_DIR') or (Path.home() / '.claude' / 'state' / 'board-asks'))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(session):
    return re.sub(r'[^A-Za-z0-9_-]', '_', session or 'unknown')[:80]


def _state_file(session):
    return _state_dir() / f'{_safe(session)}.json'


def guess_marker(session):
    """A file that exists while this session's latest answer is a guess: a hook can test it before starting Python."""
    return _state_dir() / f'{_safe(session)}.guess'


def _bound_file(session):
    return _state_dir() / f'{_safe(session)}.bound'


QUOTED_RE = re.compile(r'「[^」\n]*」|『[^』\n]*』|`[^`\n]*`|"[^"\n]*"')


def unquoted(text):
    """The text without phrases in Japanese brackets, inline code and double quotes: prose that explains a rule quotes
    the asking phrase without asking anyone (measured)."""
    return QUOTED_RE.sub('', text or '')


def prose_only(text):
    """The reply without fenced code and quoted lines: drafts for third parties (mail, posts) sit there (measured)."""
    out, in_code = [], False
    for line in (text or '').splitlines():
        if line.strip().startswith('```'):
            in_code = not in_code
            continue
        if not in_code and not line.lstrip().startswith('>'):
            out.append(line)
    return '\n'.join(out)


def hook_prompt(root, data, path=None):
    """UserPromptSubmit: bind the owner's words, record the answer, return what to tell the agent (or None)."""
    session = data.get('session_id') or _me(None)
    prompt = data.get('prompt') or ''
    if not prompt.strip() or prompt.lstrip().startswith(NOT_HUMAN):
        return None
    p = Path(path) if path else ledger_path(root)
    prefix(p)   # keep the configured letter next to the ledger for hand-run asks
    recs = load(p)
    st = state(recs)
    open_labels = [lb for lb, a in st.items() if a['status'] == 'open']
    if not open_labels:
        return None
    w0, w1 = windows(data.get('transcript_path') or '')
    known = shown_by(recs, session)
    now, prev = labels_in(w0), labels_in(w1)
    g = pending_guess(recs, session, st)
    res = bind(prompt, now, prev, open_labels, numbered_outside_blocks(w0), known=known)
    if g:
        cands = [lb for lb in (g.get('candidates') or []) if lb in open_labels]
        named_by_agent = bare_labels(prose_only(w0), cands)
        if res['binding'] == 'label' and set(res['labels']) & set(cands):
            res['binding'] = 'confirmed'
        elif AFFIRM_ONLY.match(unicodedata.normalize('NFKC', prompt).strip().splitlines()[0]) and len(named_by_agent) == 1:
            res = {'binding': 'confirmed', 'labels': named_by_agent, 'candidates': [], 'defer': False}
        elif AFFIRM_ONLY.match(unicodedata.normalize('NFKC', prompt).strip().splitlines()[0]) and len(cands) == 1:
            res = {'binding': 'confirmed', 'labels': cands, 'candidates': [], 'defer': False}
    if res['binding'] == 'none' or (res['binding'] == 'guess' and not res['candidates']):
        return None
    answer(root, res['labels'], prompt, res['binding'], session=session, candidates=res['candidates'], path=p,
           from_hook=True, defer=res.get('defer', False))
    if res['binding'] == 'guess':
        heads = '; '.join(f"{lb} ({st[lb]['text'][:40]})" for lb in res['candidates'][:6])
        extra = ' 返事の中に問いの段のほかにも番号つきの見出し・一覧がある。' if numbered_outside_blocks(w0) else ''
        return (f'🔒 board-asks: 本人の答えの結び先が決まらない (候補: {heads}).{extra}'
                ' 送る・決定を記録する・別の session に頼む・session を起こす・畳む操作は止まる。'
                ' 返事の 1 行目で、 候補の印を 1 つだけ名指して「H12 (問いの頭) と読みました。よいですか」 と確かめる'
                ' (本人が「はい」 か印で答えると解ける)。 読む・調べる・下書きは止めない')
    heads = '; '.join(f"{lb} ({st[lb]['text'][:40]})" for lb in res['labels'])
    with contextlib.suppress(OSError):
        _bound_file(session).write_text(json.dumps(res['labels']))
    if res.get('defer'):
        return f'board-asks: 本人の答えは {heads} の先送り (問いは開いたまま)。 返事の 1 行目に印と問いの頭を書く'
    how = {'label': '印で', 'order': '直前の返事の問いの並びで', 'confirmed': '確かめた読みで'}[res['binding']]
    return (f'board-asks: 本人の答えを {heads} に結んだ ({how})。 返事の 1 行目に印と問いの頭を書く。'
            ' 本人の裁定なら、 その問いの key の記録 (TODO の decided など) に本人の語のまま書く')


def hook_pretool(root, data, path=None):
    """PreToolUse: while this session's latest answer is an open guess, stop effective actions. A deny reason or None."""
    session = data.get('session_id') or _me(None)
    recs = load(Path(path) if path else ledger_path(root))
    g = pending_guess(recs, session)
    if not g:
        with contextlib.suppress(FileNotFoundError):
            guess_marker(session).unlink()   # settled elsewhere: let the entry stop starting Python
        return None
    eff = effect(data.get('tool_name') or '', data.get('tool_input') or {})
    if not eff:
        return None
    c = ', '.join(g.get('candidates') or [])
    return (f'🔒 board-asks: 本人の答え「{(g.get("quote") or "")[:60]}」 の結び先が決まっていない (候補 {c}) ので、 {eff} は止めた。'
            ' 先に 1 行で、 候補の印を 1 つだけ名指して「〜と読みました。よいですか」 と本人に確かめる。 本人が「はい」 か印で答えると解ける')


def _first_line(text):
    return next((ln for ln in (text or '').splitlines() if ln.strip()), '')


def hook_stop(root, data, path=None):
    """Stop: record the ask labels the reply printed; send back once (a) a reply that asks the owner in a paragraph
    without an ask label, (b) a reply after a bound answer whose first line does not name the bound label."""
    session = data.get('session_id') or _me(None)
    p = Path(path) if path else ledger_path(root)
    w0, _ = windows(data.get('transcript_path') or '')
    labels = labels_in(w0)
    if labels:
        mark_shown(root, labels, session=session, path=p)
    bf = _bound_file(session)
    bound = []
    with contextlib.suppress(OSError, ValueError):
        bound = json.loads(bf.read_text())
    with contextlib.suppress(FileNotFoundError):
        bf.unlink()
    if data.get('stop_hook_active'):
        return None
    sf = _state_file(session)
    key = hashlib.sha256(w0[-4000:].encode('utf-8')).hexdigest()[:16]
    try:
        if json.loads(sf.read_text()).get('sent_back') == key:
            return None
    except (OSError, ValueError):
        pass
    msgs = []
    if bound and not bare_labels(_first_line(w0), bound):
        msgs.append(f'返事の 1 行目に、 本人の答えを結んだ印 ({", ".join(bound)}) と問いの頭を書いていない')
    recs = load(p)
    st = state(recs)
    known = [lb for lb in shown_by(recs, session) if lb in st] + [lb for lb in labels if lb in st]
    g = pending_guess(recs, session, st)
    allowed = set(known) | set((g or {}).get('candidates') or [])
    loose = []
    for para in re.split(r'\n\s*\n', prose_only(w0)):
        if ASK_RE.search(unquoted(para)) and not BLOCK_RE.search(para) and not bare_labels(para, sorted(allowed)):
            loose.append(para.strip().splitlines()[0][:60])
    if loose:
        here = Path(__file__).resolve()
        msgs.append('本人に答えを求める段に、 掲示板の問いの印 (〔問 H12〕 の形) が付いていない'
                    f' (「{loose[0]}」 ほか)。 問いを立ててから (python3 {here} ask --root <掲示板> --text … --recommend … --ground <理由>)、'
                    ' 道具が出した問いの段を短い追記に貼る。 本人の裁定が要らない問いなら、 問わずに決めて報告する追記にする')
    if not msgs:
        return None
    sf.write_text(json.dumps({'sent_back': key}))
    return 'board-asks: ' + ' / '.join(msgs)


def digest(root, session, max_chars=8000, path=None):
    recs = load(Path(path) if path else ledger_path(root))
    st = state(recs)
    mine = shown_by(recs, session)
    opened = [st[lb] for lb in mine if lb in st and st[lb]['status'] == 'open']
    answered = [st[lb] for lb in mine if lb in st and st[lb]['status'] == 'answered']
    if not opened and not answered:
        return ''
    lines = ['📌 この session の本人への問い (掲示板の問いの台帳 = board_asks.py。 依頼・調べを出す前に、 同じ問いがあれば前の答えを読む。'
             ' 本人の裁定は TODO の decided・DESIGN に記録したかを確かめる)']
    for a in sorted(answered, key=lambda a: _last_settled(a).get('created_at', ''), reverse=True):
        ans = _last_settled(a)
        lines.append(f"✅ {a['label']} {a['text'][:200]} → 本人「{(ans.get('quote') or '')[:300]}」"
                     + (f" 読み: {ans['reading'][:150]}" if ans.get('reading') else ''))
    for a in opened:
        lines.append(f"❓ {a['label']} {a['text'][:200]} / おすすめ: {a.get('recommend', '')[:150]}")
    out, n = [], 0
    for i, ln in enumerate(lines):
        if n + len(ln) > max_chars:
            out.append(f'… ほか {len(lines) - i} 件 (全部 = board_asks.py list --session {session})')
            break
        out.append(ln)
        n += len(ln) + 1
    return '\n'.join(out)


def precompact_text(root, data, path=None):
    session = data.get('session_id') or _me(None)
    recs = load(Path(path) if path else ledger_path(root))
    st = state(recs)
    labels = [lb for lb in shown_by(recs, session) if lb in st]
    if not labels:
        return ''
    heads = ' / '.join(f"{lb}: {st[lb]['text'][:60]} ({st[lb]['status']})" for lb in labels)
    return ('要約の中に、 この会話で本人に問うた問いと本人の答えを、 本人の語のまま「問い → 答え → した事」 の対で残す。'
            '「済み」 の 1 行に畳まない。 問いの印 = ' + heads)[:9000]


# ---------- CLI ----------

def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(description='questions to the board owner and the owner answers (CONTRACT.md#owner-asks)')
    ap.add_argument('cmd', nargs='?', choices=['ask', 'answer', 'withdraw', 'list', 'show', 'digest', 'hook-prompt',
                                               'hook-pretool', 'hook-stop', 'hook-precompact', 'hook-sessionstart'])
    ap.add_argument('--root', default='.')
    ap.add_argument('--session')
    ap.add_argument('--agent', default='claude')
    ap.add_argument('--project', default='')
    ap.add_argument('--text', action='append', default=[])
    ap.add_argument('--recommend', action='append', default=[])
    ap.add_argument('--ground', action='append', default=[])
    ap.add_argument('--key', action='append', default=[], help='one question only (with several --text, call once per question)')
    ap.add_argument('--evidence', action='append', default=[])
    ap.add_argument('--applied', action='store_true')
    ap.add_argument('--reask', default='', help='同じ問いに本人の答えが既にあっても問い直す理由 (何が変わったか)')
    ap.add_argument('--label', action='append', default=[])
    ap.add_argument('--quote', default='')
    ap.add_argument('--binding', default='label')
    ap.add_argument('--reading', default='')
    ap.add_argument('--recorded', default='')
    ap.add_argument('--reason', default='')
    ap.add_argument('--open', action='store_true')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--max-chars', type=int, default=8000)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        if a.cmd == 'ask':
            n = len(a.text)
            if not n or len(a.ground) not in (1, n) or len(a.recommend) not in (0, n) or len(a.evidence) not in (0, 1, n):
                raise ValueError('--text を 1 つ以上。 --ground は 1 つ (全部に同じ) か --text と同じ数、 --recommend は --text と同じ数')
            if n > 1 and a.key:
                raise ValueError('key は問い 1 つずつに付ける (--text を 1 つにして呼び分ける)')
            items = [{'text': t, 'recommend': a.recommend[i] if a.recommend else '',
                      'ground': a.ground[i] if len(a.ground) == n else a.ground[0], 'keys': a.key,
                      'evidence': (a.evidence[i] if len(a.evidence) == n else (a.evidence[0] if a.evidence else '')),
                      'applied': a.applied, 'reask': a.reask} for i, t in enumerate(a.text)]
            res = ask(a.root, items, session=a.session, agent=a.agent, project=a.project)
            _print(res) if a.json else print(format_block(res))
            return 0 if any(r['status'] in ('made', 'reused') for r in res) else 3
        if a.cmd == 'answer':
            _print(answer(a.root, a.label, a.quote, a.binding, reading=a.reading, recorded=a.recorded, session=a.session))
            return 0
        if a.cmd == 'withdraw':
            if not a.label:
                raise ValueError('--label が要る')
            _print(withdraw(a.root, a.label[0], a.reason, session=a.session))
            return 0
        if a.cmd in ('list', 'show'):
            recs = load(ledger_path(a.root))
            st = state(recs)
            rows = [st[lb] for lb in a.label if lb in st] if a.cmd == 'show' else list(st.values())
            if a.open:
                rows = [r for r in rows if r['status'] == 'open']
            if a.session:
                mine = set(shown_by(recs, a.session))
                rows = [r for r in rows if r['label'] in mine]
            if a.json or a.cmd == 'show':
                _print(rows)
            else:
                for r in rows:
                    print(f"{r['label']:6} {r['status']:9} {r.get('ground', ''):9} {r['text'][:80]}")
            return 0
        if a.cmd == 'digest':
            print(digest(a.root, _me(a.session), a.max_chars))
            return 0
        data = json.loads(sys.stdin.read() or '{}')
        if a.cmd == 'hook-prompt':
            msg = hook_prompt(a.root, data)
            if msg:
                print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': msg}}, ensure_ascii=False))
        elif a.cmd == 'hook-pretool':
            msg = hook_pretool(a.root, data)
            if msg:
                print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                         'permissionDecisionReason': msg}}, ensure_ascii=False))
        elif a.cmd == 'hook-stop':
            msg = hook_stop(a.root, data)
            if msg:
                print(json.dumps({'decision': 'block', 'reason': msg}, ensure_ascii=False))
        elif a.cmd == 'hook-precompact':
            out = precompact_text(a.root, data)
            if out:
                print(out)
        elif a.cmd == 'hook-sessionstart':
            prefix(ledger_path(a.root))
            out = digest(a.root, data.get('session_id') or _me(None), a.max_chars)
            if out:
                print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': out}}, ensure_ascii=False))
        return 0
    except ValueError as e:
        print(f'board_asks: {e}', file=sys.stderr)
        return 1


# ---------- selftest ----------

def selftest():
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print('FAIL', msg)
    saved = {k: os.environ.get(k) for k in ('BOARD_ASKS_PREFIX', 'BOARD_ASKS_STATE_DIR')}
    try:
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / 'asks.jsonl'
            os.environ['BOARD_ASKS_PREFIX'] = 'H'
            os.environ['BOARD_ASKS_STATE_DIR'] = str(Path(td) / 'state')
            r = ask(None, [{'text': '問い一', 'recommend': 'はい', 'ground': 'choice', 'keys': ['todo:x:1']},
                           {'text': '問い二', 'recommend': 'いいえ', 'ground': 'fact'}], session='s1', path=led)
            check([x['label'] for x in r] == ['H1', 'H2'], f'印 = 機械ごとの字 + 通し番号 {r}')
            os.environ.pop('BOARD_ASKS_PREFIX')
            check(prefix(led) == 'H', '一度渡された字は台帳の隣に残り、 手で打つ ask も同じ字を使う')
            check(prefix(Path(td) / 'other.jsonl') == 'Q', '字の設定が無ければ Q (機械の名の頭字は M4・M5 と重なる)')
            os.environ['BOARD_ASKS_PREFIX'] = 'H'
            r2 = ask(None, [{'text': '問い一', 'ground': 'choice', 'keys': ['todo:x:1']}], session='s2', path=led)
            check(r2[0]['status'] == 'reused' and r2[0]['label'] == 'H1' and '別の問い' not in r2[0]['message'],
                  '同じ key の開いた問いはその印で出し直す')
            r2b = ask(None, [{'text': '全然ちがう問い', 'ground': 'choice', 'keys': ['todo:x:1']}], session='s2', path=led)
            check(r2b[0]['status'] == 'refused' and '別の問い' in r2b[0]['message'] and 'H1' in r2b[0]['message'],
                  '同じ key で文が違う問いは、 前の問いの印で出し直さずに断り、 key を分けるよう言う')
            check(ask(None, [{'text': '理由なし', 'ground': 'nothing'}], session='s1', path=led)[0]['status'] == 'refused',
                  '理由の無い問いは立てない')
            r4 = ask(None, [{'text': '規則', 'ground': 'rule'}], session='s1', path=led)
            check(r4[0]['status'] == 'refused' and 'evidence' in r4[0]['message'], '規則の理由には変更の在りかが要る')
            stub = Path(td) / 'validator.py'
            stub.write_text('import json,sys\nev=sys.argv[sys.argv.index("--evidence")+1]\n'
                            'print(json.dumps({"error": "読めない"} if "bad" in ev else {"ok": "needs" in ev, "message": "stub"}))\n',
                            encoding='utf-8')
            r5 = ask(None, [{'text': '要らない規則', 'ground': 'rule', 'evidence': 'r@HEAD:free'}], session='s1', path=led, validator=stub)
            r6 = ask(None, [{'text': '要る規則', 'ground': 'rule', 'evidence': 'r@HEAD:needs'}], session='s1', path=led, validator=stub)
            check(r5[0]['status'] == 'refused' and r6[0]['status'] == 'made' and r6[0]['label'] == 'H3', f'判定の道具が要らないと言えば立てない {r5} {r6}')
            r5b = ask(None, [{'text': '理由を選び直した規則', 'ground': 'choice', 'evidence': 'r@HEAD:free'}], session='s1', path=led, validator=stub)
            check(r5b[0]['status'] == 'refused', '変更の在りかがあれば理由に依らず判定の道具を通す')
            r5c = ask(None, [{'text': '在りかの誤り', 'ground': 'rule', 'evidence': 'r@HEAD:bad'}], session='s1', path=led, validator=stub)
            check(r5c[0]['status'] == 'refused' and '読めない' in r5c[0]['message'], '判定の道具の誤りを理由として返す')
            r7 = ask(None, [{'text': '道具なし', 'ground': 'rule', 'evidence': 'r@HEAD:x'}], session='s1', path=led,
                     validator=Path(td) / 'missing.py')
            check(r7[0]['status'] == 'made' and r7[0]['message'].startswith('⚠️'), '判定の道具が無ければ立てて、 確かめていないと言う')
            blk = format_block(r)
            check('〔問 H1〕 問い一' in blk and 'おすすめ: はい' in blk, '問いの段の形')
            check(shown_by(load(led), 's2') == ['H1'], '出し直した問いも見せた問いに数える')
            # binding
            o2 = ['H1', 'H2']
            check(bind('H2 OK', o2, [], o2) == {'binding': 'label', 'labels': ['H2'], 'candidates': [], 'defer': False}, '印で答えた')
            check(bind('Ｈ２　ＯＫ', o2, [], o2)['labels'] == ['H2'], '全角の印も読む')
            check(bind('H9 OK', ['H1'], [], ['H1', 'H9'])['binding'] == 'none', 'この session が見せていない印には結ばない')
            check(bind('H9 OK', ['H1'], [], ['H1', 'H9'], known=['H9'])['labels'] == ['H9'], '前に見せた印なら前の返事の問いでも結ぶ')
            check(bind('M5 の Mac でやって', ['M4'], [], ['M4', 'M5'])['binding'] == 'none', '見せていない機種名の類は印にしない')
            b = bind('H2 は後で考える', o2, [], o2)
            check(b['binding'] == 'label' and b['defer'], '先送りの答えは印に結ぶが閉じない')
            check(bind('１２OK', o2, [], o2)['labels'] == ['H1', 'H2'], '並びの番号 (連記) = 直前の返事の問いの段だけなら確定')
            check(bind('12は違う', o2, [], o2)['binding'] == 'guess', '連記の後が肯定の語だけでなければ推定 (別の一覧の 12 番かもしれない)')
            check(bind('arxiv v3 で', ['V3'], [], ['V3'])['binding'] == 'none', '小文字の v3 は印でない')
            check(bind('１　はい\n２　来週でいい', o2, [], o2)['labels'] == ['H1', 'H2'], '行ごとの番号')
            check(bind('10はいらない', o2, [], o2)['binding'] == 'guess', '問いの数を越える 2 桁は分けない (推定)')
            check(bind('11は後で', o2, [], o2)['binding'] == 'guess', '同じ字の 2 桁は分けない')
            check(bind('１はメールで伝えよう', o2, [], o2, other_numbered_now=True)['binding'] == 'guess', '番号つきの見出しもあれば推定')
            b = bind('1 OK', ['H3'], ['H1'], ['H1', 'H3'])
            check(b['binding'] == 'guess' and b['candidates'] == ['H3', 'H1'], f'前の返事にも開いた問いがあれば推定 {b}')
            check(bind('3 OK', o2, [], o2)['binding'] == 'guess', '並びの外の番号は推定')
            check(bind('全部おすすめで', o2, [], o2)['labels'] == o2, '全部 = 直前の問い全部')
            check(bind('3 つとも案どおり', ['H1', 'H2', 'H4'], [], ['H1', 'H2', 'H4'])['labels'] == ['H1', 'H2', 'H4'],
                  '「3 つとも」 は数の答え = 全部')
            check(bind('2件メールが来てるので見て', o2, [], o2)['binding'] == 'none', '「2件…」 は答えでない')
            check(bind('1つだけ聞きたいんだけど', o2, [], o2)['binding'] == 'none', '「1つだけ…」 は答えでない')
            check(bind('それで、どうなった？', ['H1'], [], ['H1'])['binding'] == 'none', '肯定の語で始まる問い返しは答えでない')
            check(bind('送ってほしい資料がある', ['H1'], [], ['H1'])['binding'] == 'none', '肯定の語で始まる依頼は答えでない')
            check(bind('12/24でいいよ', ['H1'], [], ['H1'])['binding'] == 'none', '日付は番号でない')
            check(bind('それより先にメールを見て', ['H1'], [], ['H1'])['binding'] == 'none', '答えでない発言は結ばない')
            check(bind('はい', ['H1'], [], ['H1'])['labels'] == ['H1'], '問い 1 つへの「はい」')
            check(bind('はい', o2, [], o2)['binding'] == 'guess', '問い 2 つへの「はい」 は推定')
            for txt in ('### 1. 報告', '| 1 | 案 |', '(1) 案', '１．案', '1、案', '（１）案'):
                check(numbered_outside_blocks(txt + '\n〔問 H1〕 x\n'), f'番号の形を拾う: {txt}')
            check(not numbered_outside_blocks('〔問 H1〕 x\n```\n1. code\n```'), '問いの段と code の中は数えない')
            # answers and the stop on effective actions
            answer(None, [], '1 OK', 'guess', session='s1', candidates=['H1', 'H3'], path=led, from_hook=True)
            check(guess_marker('s1').exists(), '推定のあいだは印の file がある')
            deny = lambda tool, inp=None, s='s1': hook_pretool(None, {'session_id': s, 'tool_name': tool, 'tool_input': inp or {}}, path=led)
            check(deny('SendMessage'), '推定のあいだは別の session への message を止める')
            check(deny('mcp__ccd_session_mgmt__send_message'), 'app の別 session への message も止める')
            check(deny('mcp__ccd_session__start_session'), 'session を起こすのも止める')
            check(deny('Read') is None, '読むのは止めない')
            check(deny('Edit', {'file_path': '/r/todo/a.yaml'}), 'TODO の記録も止める')
            check(deny('Edit', {'file_path': '/r/review/author-decisions.md'}), '決定の台帳も止める')
            check(deny('Bash', {'command': 'python3 send_mail.py --to x --send'}), '送信の道具も止める')
            check(deny('Bash', {'command': 'python3 board_asks.py list --root b; python3 send_mail.py --send'}),
                  '台帳の道具と ; でつないだ送信も止める')
            check(deny('Bash', {'command': "cat <<'EOF' > ~/r/todo/a.yaml\nx\nEOF"}), 'heredoc で TODO に書くのも止める')
            check(deny('Bash', {'command': 'rm ~/.claude/state/board-asks/s1.guess'}), '推定の印の file を消すのも止める')
            check(deny('Bash', {'command': 'cat ~/b/.local/asks.jsonl'}) is None, '台帳を読むのは止めない')
            check(deny('Bash', {'command': 'python3 board_asks.py answer --label H1 --binding confirmed'}), '台帳の答えを手で書くのは止める')
            check(deny('Bash', {'command': 'python3 board_asks.py ask --root b --text x --ground fact'}) is None, '問いを立てるのは止めない')
            check(deny('Bash', {'command': 'python3 board.py show --root b --request R1'}) is None, '掲示板を読むのは止めない (--request の値)')
            check(deny('Bash', {'command': 'python3 board.py claim --root b --request R1'}) is None, 'claim は止めない')
            check(deny('Bash', {'command': 'python3 board.py accept --root b --request R1'}), '受け取りは止める')
            check(deny('SendMessage', s='s2') is None, '別の session は止めない')
            try:
                answer(None, ['H1'], '自分で', 'confirmed', session='s1', path=led)
                check(False, '推定のあいだ手で確定は書けない')
            except ValueError:
                pass
            answer(None, ['H1'], 'H1 です', 'confirmed', session='s1', path=led, from_hook=True)
            check(deny('SendMessage') is None and not guess_marker('s1').exists(), '確かめた後は解け、 印の file も消える')
            st = state(load(led))
            check(st['H1']['status'] == 'answered' and st['H2']['status'] == 'open', '答えの状態')
            answer(None, ['H2'], 'H2 は後で', 'label', session='s1', path=led, from_hook=True, defer=True)
            check(state(load(led))['H2']['status'] == 'open', '先送りでは閉じない')
            withdraw(None, 'H2', '他で決まった', session='s1', path=led)
            check(state(load(led))['H2']['status'] == 'withdrawn', '取り下げ')
            # a guess whose candidates were all closed elsewhere does not stop forever
            answer(None, [], '2 OK', 'guess', session='s4', candidates=['H2'], path=led, from_hook=True)
            check(deny('SendMessage', s='s4') is None and not guess_marker('s4').exists(), '候補が全部閉じた推定では止めない')
            # an earlier decision: the same question already answered is not asked again
            rb = ask(None, [{'text': '問い一', 'ground': 'choice', 'keys': ['todo:x:1']}], session='s5', path=led)
            check(rb[0]['status'] == 'answered-before' and rb[0]['label'] == 'H1' and rb[0]['quote'] == 'H1 です',
                  f'同じ key に本人の答えがあれば問わずにその答えを返す {rb}')
            check('(問わない) 〔問 H1〕' in format_block(rb), '答え済みの印と本人の語を出す')
            rb2 = ask(None, [{'text': '別の問い', 'ground': 'choice', 'keys': ['todo:x:1']}], session='s5', path=led)
            check(rb2[0]['status'] == 'refused' and '別の問いなら key' in rb2[0]['message'] and 'H1 です' in rb2[0]['message'],
                  '同じ key の別の文の問いには前の答えを答えとして返さず、 前の答えを見せて断る')
            rr = ask(None, [{'text': '問い一 (前提が変わった)', 'ground': 'choice', 'keys': ['todo:x:1'], 'reask': '期日が変わった'}],
                     session='s5', path=led)
            check(rr[0]['status'] == 'made', '理由つきなら問い直せる')
            # one policy check per request, put by the requester (native id in actor.task too)
            board = Path(td) / 'board'
            (board / 'events' / 'proj' / 'th').mkdir(parents=True)
            (board / 'events' / 'proj' / 'th' / 'R1--20260101T000000Z-claude-abc123.json').write_text(json.dumps(
                {'kind': 'request', 'event_id': '20260101T000000Z-claude-abc123',
                 'actor': {'agent': 'claude', 'session_id': 'role-x-y', 'task': 'deadbeef (opus)'}}), encoding='utf-8')
            pk = ['request:20260101T000000Z-claude-abc123']
            check(ask(board, [{'text': '方針でよいか', 'ground': 'policy'}], session='deadbeef-1', path=led)[0]['status'] == 'refused',
                  '方針の確認には依頼の key が要る')
            check(ask(None, [{'text': '方針でよいか', 'ground': 'policy', 'keys': ['request:nowhere']}], session='deadbeef-1',
                      path=led)[0]['status'] == 'refused', '依頼の作者を確かめられなければ方針の確認は立てない')
            rw = ask(None, [{'text': '方針の中の選択をどうするか', 'ground': 'choice'}], session='worker-9', path=led)
            check(rw[0]['status'] == 'made' and '--ground policy' in rw[0]['message'], '方針の語を別の理由で問うと注意を添える')
            check(ask(board, [{'text': '方針の中の選択', 'ground': 'policy', 'keys': pk}], session='worker-9', path=led)[0]['status'] == 'refused',
                  '依頼元でない session は方針の確認を立てない')
            rp = ask(board, [{'text': '方針でよいか', 'ground': 'policy', 'keys': pk}], session='deadbeef-1111', path=led)
            check(rp[0]['status'] == 'made', f'role id で出した依頼でも、 task の中の native id の session は立てられる {rp}')
            check(ask(board, [{'text': '方針でよいか', 'ground': 'policy', 'keys': pk}], session='deadbeef-1111', path=led)[0]['status'] == 'reused',
                  '同じ依頼の方針の確認は 1 回だけ (2 回目は同じ印)')
            check('H1' in precompact_text(None, {'session_id': 's1'}, path=led), '圧縮の前の指示に印を出す')
            d = digest(None, 's1', path=led)
            check('✅ H1' in d and 'H1 です' in d, f'開始・圧縮の後の出力 {d[:160]}')
            check(digest(None, 'nobody', path=led) == '', '問いの無い session には何も出さない')
            # hooks on a transcript
            tr = Path(td) / 't.jsonl'

            def write_tr(*turns):
                lines = []
                for u, a_ in turns:
                    lines.append({'type': 'user', 'message': {'role': 'user', 'content': u}})
                    lines.append({'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': a_}]}})
                tr.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in lines) + '\n', encoding='utf-8')
            r8 = ask(None, [{'text': '問い八', 'ground': 'choice'}, {'text': '問い九', 'ground': 'choice'}], session='s9', path=led)
            l8, l9 = r8[0]['label'], r8[1]['label']
            write_tr(('RCA を見せて', f'### 1. 報告\n\n〔問 {l8}〕 問い八\n\n〔問 {l9}〕 問い九'))
            w0, w1 = windows(str(tr))
            check(labels_in(w0) == [l8, l9] and w1 == '', '直前の窓の問いの印')
            check(hook_stop(None, {'session_id': 's9', 'transcript_path': str(tr)}, path=led) is None, '印つきの問いは差し戻さない')
            msg = hook_prompt(None, {'session_id': 's9', 'transcript_path': str(tr), 'prompt': '１はメールで伝えよう'}, path=led)
            check(msg and '🔒' in msg, f'見出しの番号と問いの段が並ぶ返事への「１は…」 は推定 {msg}')
            check(hook_pretool(None, {'session_id': 's9', 'tool_name': 'SendMessage', 'tool_input': {}}, path=led), '推定で止まる')
            write_tr(('RCA を見せて', f'### 1. 報告\n\n〔問 {l8}〕 問い八\n\n〔問 {l9}〕 問い九'),
                     ('１はメールで伝えよう', f'{l8} (問い八) と読みました。よいですか'))
            check(hook_stop(None, {'session_id': 's9', 'transcript_path': str(tr)}, path=led) is None,
                  '候補の印を名指した確かめの文は差し戻さない')
            msg = hook_prompt(None, {'session_id': 's9', 'transcript_path': str(tr), 'prompt': 'はい'}, path=led)
            check(msg and '確かめた読み' in msg and l8 in msg, f'確かめの文が名指した印に「はい」 が結ぶ {msg}')
            check(hook_pretool(None, {'session_id': 's9', 'tool_name': 'SendMessage', 'tool_input': {}}, path=led) is None, '解ける')
            write_tr(('x', f'{l9} は残っています。\n\nこれで進めてよいですか'))
            stop = hook_stop(None, {'session_id': 's9', 'transcript_path': str(tr)}, path=led)
            check(stop and '印' in stop and '1 行目' in stop, f'結んだ印を 1 行目に書かない返事と、 印の無い問いの段を差し戻す {stop}')
            write_tr(('x', f'〔問 {l9}〕 問い九\n\nもう一つ、 こちらも決めてください'))
            stop = hook_stop(None, {'session_id': 's8', 'transcript_path': str(tr)}, path=led)
            check(stop and '印' in stop, '印のある問いと並んでも、 印の無い問いの段は差し戻す')
            check(hook_stop(None, {'session_id': 's8', 'transcript_path': str(tr)}, path=led) is None, '同じ返事は繰り返し差し戻さない')
            write_tr(('x', '下書きです。\n```\n担当者様\nこの形で進めてよいですか。\n```\n> 引用: よいですか\n'))
            check(hook_stop(None, {'session_id': 's6', 'transcript_path': str(tr)}, path=led) is None,
                  '下書き (code block) と引用の中の問いは本人への問いに数えない')
            check(hook_prompt(None, {'session_id': 's7', 'transcript_path': str(tr), 'prompt': '<system-reminder>x'}, path=led) is None,
                  '注入の文は答えに数えない')
            write_tr(('x', '規則は「送る前に よいですか と聞く」 です。 説明だけです。'))
            check(hook_stop(None, {'session_id': 's10', 'transcript_path': str(tr)}, path=led) is None,
                  '規則を説明する地の文の中の、 鉤括弧で引いた問いの語は数えない')
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print('selftest:', 'OK' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
