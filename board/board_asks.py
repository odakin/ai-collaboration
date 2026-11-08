#!/usr/bin/env python3
"""board_asks.py — questions an agent puts to the board's owner, and the owner's answers. See CONTRACT.md#owner-asks.

Why: an agent that asks its owner several things in one reply labels them itself (1 2 3, A B C), and labels it
invents restart in every reply. The owner answers by label or by position ("1 and 2 OK"), often to an earlier reply
than the latest, and the same question re-asked in another window gets a different label each time. The agent then
binds the answer to the wrong item and acts on it in the same turn (measured: a short answer meant for a report
section was bound to the item just above it, then recorded as a decision and forwarded to another session). Answers also fade: a context compaction folds answered questions into a one-line "done".

What it is:
- An **ask** is one item the owner must answer. The board, not the agent, gives it a label: a letter fixed per machine
  plus that machine's running number (`H12`), never reused, so the same question keeps one label in every window and on
  every day. The ask carries the question, the recommended answer, why it needs the owner (the **ground**), and keys
  naming the work it belongs to (`todo:<repo>:<id>`, `plan:<path>#<section>`, `request:<id>`). An open ask with the
  same key is reused instead of asking twice.
- Before an ask is made it passes a **gate**: the ground must be one the owner alone can decide (GROUNDS). Grounds a
  machine can decide are decided by a validator: a change to a rule document or to a protected part of a manuscript
  is judged by the owner's rule-protection engines, and an ask about a change that needs no ruling is refused ("apply
  it and report"; measured: asks to ratify changes that never needed a ruling reached the owner). The validator is a
  separate program (`BOARD_ASKS_VALIDATOR`, default = `owner-ask-validate.py` in a sibling `claude-config/scripts/`)
  so this engine does not depend on any one user's protection engines: without one, rule and protected asks are made
  and the output says the gate could not judge.
- An **answer** records the owner's words verbatim, the labels it was bound to and how: `label` (the owner wrote the
  label), `order` (a position in the only ask block of the latest reply), `confirmed` (the owner confirmed a reading),
  or `guess` (no safe binding: candidates listed). While a session's latest answer is a `guess`, the tool check stops
  effective actions (sending, recording a decision, messaging another session, closing a session) until the owner's
  next words settle it; the agent cannot settle it alone.
- A **withdraw** closes an ask decided elsewhere. **shown** records which asks a session displayed.

Store: an append-only JSON-lines ledger local to the board checkout and shared by every session on the machine
(`<board>/.local/asks.jsonl`, else `<git common dir>/board-asks/<board subdir>.jsonl`; `BOARD_ASKS_LEDGER` overrides).
Readers need no network: a board post fetches and pushes (seconds each), which a check on every prompt cannot afford.
Mirroring the ledger to other machines is not in this version.

CLI:
    python3 board_asks.py ask      --root <board> --text '<question>' --recommend '<answer>' --ground <g> [--key K]...
                                   [--evidence <repo>@<rev>:<path>] [--applied] [--project P] [--json]
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
ask made or reused, 3 = every item refused by the gate. The session is `--session`, else CLAUDE_CODE_SESSION_ID /
CODEX_THREAD_ID. The label letter is `BOARD_ASKS_PREFIX` (one capital letter per machine), else the host name's first
letter. Effective actions are configurable (BOARD_ASKS_EFFECT_TOOLS / _BASH / _PATHS, newline-separated regexes).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import socket
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
    'policy': '実装の前の方針の確認',
    'fact': '本人しか知らない事実',
}
JUDGED = ('rule', 'protected')
BINDINGS = ('label', 'order', 'confirmed', 'guess')
SETTLED = ('label', 'order', 'confirmed')
LABEL_RE = re.compile(r'(?<![A-Za-z0-9])([A-Z])(\d{1,5})(?![0-9])')
BLOCK_RE = re.compile(r'〔問\s*([A-Z]\d{1,5})〕')
MAX_TEXT = 600
MAX_QUOTE = 1500


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


def prefix():
    p = (os.environ.get('BOARD_ASKS_PREFIX') or '').strip().upper()
    if re.fullmatch(r'[A-Z]', p):
        return p
    host = re.sub(r'[^A-Za-z]', '', socket.gethostname())
    return (host[:1] or 'Q').upper()


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
                if r.get('binding') in SETTLED and lb in (r.get('labels') or []) and a['status'] == 'open':
                    a['status'] = 'answered'
        elif t == 'withdraw':
            a = asks.get(r.get('label'))
            if a is not None and a['status'] == 'open':
                a['status'] = 'withdrawn'
    return asks


def shown_by(recs, session):
    """Labels this session made, reused, printed or answered, in first-seen order."""
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


def pending_guess(recs, session):
    """This session's latest answer when it is an unsettled guess (a later settled answer ends it)."""
    last = None
    for r in recs:
        if r.get('type') == 'answer' and r.get('session') == session:
            last = r
    return last if last and last.get('binding') == 'guess' else None


# ---------- the gate ----------

def _validator():
    env = os.environ.get('BOARD_ASKS_VALIDATOR')
    if env:
        return Path(os.path.expanduser(env))
    return HERE.parent.parent / 'claude-config' / 'scripts' / 'owner-ask-validate.py'


def gate(ground, evidence=None, *, applied=False, validator=None):
    """(ok, message). ok=False = do not ask; the message says why and what to do instead."""
    if ground not in GROUNDS:
        return False, f'裁定が要る理由が無い・一覧に無い ({ground!r})。 理由 = {", ".join(GROUNDS)}。 どれでもなければ問わずに決めて報告する'
    if ground not in JUDGED:
        return True, ''
    if not evidence:
        return False, f'理由 {ground} には変更の在りか (--evidence <repo>@<commit>:<path> か <repo>@worktree:<path>) が要る (裁定の要否を機械で判定するため)'
    v = Path(validator) if validator else _validator()
    if not v.exists():
        return True, f'⚠️ 判定の道具が無い ({v}) = 裁定の要否を確かめずに立てた'
    args = [sys.executable, str(v), '--ground', ground, '--evidence', evidence] + (['--applied'] if applied else [])
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=60)
        res = json.loads(p.stdout or '{}')
    except (subprocess.TimeoutExpired, ValueError, OSError) as e:
        return True, f'⚠️ 判定の道具が答えない ({e.__class__.__name__}) = 裁定の要否を確かめずに立てた'
    if 'ok' not in res:
        return True, f'⚠️ 判定の道具の出力が読めない = 裁定の要否を確かめずに立てた ({(p.stderr or "")[:200]})'
    return bool(res['ok']), str(res.get('message') or '')


# ---------- operations ----------

def _me(session):
    return session or os.environ.get('CLAUDE_CODE_SESSION_ID') or os.environ.get('CODEX_THREAD_ID') or 'unknown'


def ask(root, items, *, session=None, agent='claude', project='', path=None, validator=None):
    """items = [{text, recommend, ground, keys, evidence, applied}] -> [{status: made|reused|refused, label?, message}]."""
    p = Path(path) if path else ledger_path(root)
    me = _me(session)
    out = []
    with _locked(p):
        recs = load(p)
        st = state(recs)
        new = []
        for it in items:
            text = (it.get('text') or '').strip()[:MAX_TEXT]
            keys = [k for k in (it.get('keys') or []) if k]
            same = next((a for a in st.values() if a['status'] == 'open' and keys and set(keys) & set(a.get('keys') or [])), None)
            if same:
                new.append({'type': 'shown', 'labels': [same['label']], 'session': me, 'created_at': now_iso()})
                out.append({'status': 'reused', 'label': same['label'], 'text': same['text'], 'recommend': same.get('recommend', ''),
                            'message': '同じ仕事の開いた問いがある = 新しく立てずにその印で問う'})
                continue
            if not text:
                out.append({'status': 'refused', 'text': '', 'message': '問いの文が空'})
                continue
            ok, msg = gate(it.get('ground'), it.get('evidence'), applied=bool(it.get('applied')), validator=validator)
            if not ok:
                out.append({'status': 'refused', 'text': text, 'message': msg})
                continue
            label = _next_label(recs + new, prefix())
            rec = {'type': 'ask', 'label': label, 'text': text, 'recommend': (it.get('recommend') or '').strip()[:MAX_TEXT],
                   'ground': it['ground'], 'keys': keys, 'evidence': it.get('evidence') or '', 'applied': bool(it.get('applied')),
                   'gate': msg, 'session': me, 'agent': agent, 'project': project, 'created_at': now_iso()}
            new.append(rec)
            out.append({'status': 'made', 'label': label, 'text': text, 'recommend': rec['recommend'], 'message': msg})
        _append(p, new)
    return out


def format_block(results):
    lines = []
    for r in results:
        if r['status'] in ('made', 'reused'):
            lines.append(f"〔問 {r['label']}〕 {r['text']}")
            if r.get('recommend'):
                lines.append(f"　おすすめ: {r['recommend']}")
            if r.get('message', '').startswith('⚠️'):
                lines.append(f"　({r['message']})")
        else:
            lines.append(f"(立てない) {r.get('text', '')[:80]} — {r['message']}")
    return '\n'.join(lines)


def answer(root, labels, quote, binding, *, reading='', recorded='', session=None, candidates=None, path=None):
    if binding not in BINDINGS:
        raise ValueError(f'binding は {BINDINGS} のどれか')
    p = Path(path) if path else ledger_path(root)
    with _locked(p):
        st = state(load(p))
        unknown = [lb for lb in list(labels) + list(candidates or []) if lb not in st]
        if unknown:
            raise ValueError(f'台帳に無い印: {unknown}')
        if binding != 'guess' and not labels:
            raise ValueError('結んだ印が無い (--label)')
        rec = {'type': 'answer', 'labels': list(labels) if binding != 'guess' else [], 'quote': (quote or '')[:MAX_QUOTE],
               'binding': binding, 'reading': (reading or '')[:MAX_TEXT], 'recorded': recorded,
               'candidates': list(candidates or []), 'session': _me(session), 'created_at': now_iso()}
        _append(p, [rec])
    marker = guess_marker(rec['session'])
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
AFFIRM_RE = re.compile(r'^\s*(はい|ok|おけ|それで|いいよ|よし|おすすめ|推し|送って|進めて|当てて)', re.I)
ORDINAL_RE = re.compile(r'^[\s　]*([0-9]{1,2}|[①-⑳])')
POSITION_RE = re.compile(r'^[\s　]*(上の|下の|前者|後者|最初の|最後の|[一二三四五1-9]つ目|[1-9]番目)')
QTY_RE = re.compile(r'^[\s　]*[0-9]{1,2}[\s　]*(つ|通|か所|箇所|点|件|本|個)')
NOT_ORDINAL_AFTER = re.compile(r'^[0-9]{1,2}[\s　]*([/:年月日時分秒%件個回人本円つ週枚頁行章節]|[.][0-9])')
CIRCLED = ''.join(chr(0x2460 + i) for i in range(20))   # circled digits one to twenty


def _ordinals(text):
    """Positions named at the start of lines: "１２OK" = 1 and 2, "1 はい / 3 いいえ" = 1 and 3 (NFKC text)."""
    nums = []
    for line in text.splitlines():
        m = ORDINAL_RE.match(line)
        if not m or NOT_ORDINAL_AFTER.match(line.strip()):
            continue
        tok = m.group(1)
        if tok in CIRCLED:
            nums.append(CIRCLED.index(tok) + 1)
        elif len(tok) == 2 and tok[0] != '0' and (int(tok) > 20 or re.match(r'^[\s　]*[0-9]{2}\s*(ok|とも|は|も)', line, re.I)):
            nums.extend(int(c) for c in tok)
        else:
            nums.append(int(tok))
    return [n for i, n in enumerate(nums) if n > 0 and n not in nums[:i]]


def bind(text, shown_now, shown_prev, open_labels, other_numbered_now=False):
    """Bind the owner's words to asks. shown_now / shown_prev = labels displayed in the latest reply / the one before
    (display order). Returns {'binding': 'label'|'order'|'guess'|'none', 'labels': [...], 'candidates': [...]}."""
    t = unicodedata.normalize('NFKC', text or '')
    open_set = set(open_labels)
    named = []
    for m in LABEL_RE.finditer(t.upper()):
        lb = m.group(1) + str(int(m.group(2)))
        if lb in open_set and lb not in named:
            named.append(lb)
    if named:
        return {'binding': 'label', 'labels': named, 'candidates': []}
    now = [lb for lb in shown_now if lb in open_set]
    prev = [lb for lb in shown_prev if lb in open_set and lb not in now]
    first = t.strip().splitlines()[0] if t.strip() else ''
    wants_all = bool(QTY_RE.match(first)) or any(w in first for w in ALL_WORDS)
    nums = [] if QTY_RE.match(first) else _ordinals(t)
    positional = bool(POSITION_RE.match(first))
    affirm = bool(AFFIRM_RE.match(first))
    if not (nums or wants_all or positional or affirm):
        return {'binding': 'none', 'labels': [], 'candidates': []}
    if not now and not prev:
        return {'binding': 'none' if not other_numbered_now else 'guess', 'labels': [], 'candidates': []}
    safe = bool(now) and not other_numbered_now and not prev and not positional
    if safe and nums and max(nums) <= len(now):
        return {'binding': 'order', 'labels': [now[n - 1] for n in nums], 'candidates': []}
    if safe and not nums and (wants_all or len(now) == 1):
        return {'binding': 'order', 'labels': list(now), 'candidates': []}
    return {'binding': 'guess', 'labels': [], 'candidates': now + prev}


NUMBERED_LINE = re.compile(r'^\s*(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*)?(?:[0-9]{1,2}[.)．]|[①-⑳])')


def numbered_outside_blocks(text):
    """True when the text has a numbered list or numbered heading besides the ask block lines (code excluded)."""
    in_code = False
    for line in (text or '').splitlines():
        if line.strip().startswith('```'):
            in_code = not in_code
            continue
        if in_code or BLOCK_RE.search(line):
            continue
        if NUMBERED_LINE.match(line):
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


EFFECT_TOOLS_DEFAULT = [r'^SendMessage$', r'send_email$', r'^mcp__ccd_session_mgmt__(archive|stop|delete)_session$']
EFFECT_BASH_DEFAULT = [r'send_mail\.py\b[^\n]*--send\b', r'discord-post\.py\b[^\n]*--send\b',
                       r'\bboard\.py\b[^\n]*\b(accept|request|revise|handover)\b', r'record-reply\.py\b[^\n]*--apply\b',
                       r'yaml-set-top-keys\.py\b[^\n]*\bdecided\b']
EFFECT_PATH_DEFAULT = [r'/todo/[^/]+\.ya?ml$', r'(^|/)DESIGN\.md$', r'rulings\.md$']


def effect(tool, inp):
    """A short name of the effective action this tool call is, or None."""
    def env_list(name, default):
        v = os.environ.get(name)
        return [x for x in v.split('\n') if x.strip()] if v else default
    if any(re.search(p, tool or '') for p in env_list('BOARD_ASKS_EFFECT_TOOLS', EFFECT_TOOLS_DEFAULT)):
        return tool
    if tool == 'Bash':
        cmd = (inp or {}).get('command') or ''
        if 'board_asks.py' in cmd:
            return None   # recording the reading itself is never stopped
        return 'Bash' if any(re.search(p, cmd) for p in env_list('BOARD_ASKS_EFFECT_BASH', EFFECT_BASH_DEFAULT)) else None
    if tool in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        fp = (inp or {}).get('file_path') or ''
        return f'{tool} {fp}' if any(re.search(p, fp) for p in env_list('BOARD_ASKS_EFFECT_PATHS', EFFECT_PATH_DEFAULT)) else None
    return None


ASK_RE = re.compile(r'決めてほしい|決めてください|答えてください|教えてください|してよいですか|でよいですか|よいですか|いいですか|どうしますか|はい\s*[/／]\s*直す|ご判断')


def _state_dir():
    d = Path(os.environ.get('BOARD_ASKS_STATE_DIR') or (Path.home() / '.claude' / 'state' / 'board-asks'))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_file(session):
    return _state_dir() / f'{re.sub(r"[^A-Za-z0-9_-]", "_", session)[:80]}.json'


def guess_marker(session):
    """A file that exists while this session's latest answer is a guess: a hook can test it before starting Python."""
    return _state_dir() / f'{re.sub(r"[^A-Za-z0-9_-]", "_", session)[:80]}.guess'


def hook_prompt(root, data, path=None):
    """UserPromptSubmit: bind the owner's words, record the answer, return what to tell the agent (or None)."""
    session = data.get('session_id') or _me(None)
    prompt = data.get('prompt') or ''
    if not prompt.strip() or prompt.lstrip().startswith(NOT_HUMAN):
        return None
    p = Path(path) if path else ledger_path(root)
    recs = load(p)
    st = state(recs)
    open_labels = [lb for lb, a in st.items() if a['status'] == 'open']
    if not open_labels:
        return None
    w0, w1 = windows(data.get('transcript_path') or '')
    now, prev = labels_in(w0), labels_in(w1)
    g = pending_guess(recs, session)
    res = bind(prompt, now, prev, open_labels, numbered_outside_blocks(w0))
    if g:
        cands = [lb for lb in (g.get('candidates') or []) if lb in open_labels]
        if res['binding'] == 'label':
            res['binding'] = 'confirmed'
        elif AFFIRM_RE.match(unicodedata.normalize('NFKC', prompt)) and len(cands) == 1 and res['binding'] != 'order':
            res = {'binding': 'confirmed', 'labels': cands, 'candidates': []}
    if res['binding'] == 'none' or (res['binding'] == 'guess' and not res['candidates']):
        return None
    answer(root, res['labels'], prompt, res['binding'], session=session, candidates=res['candidates'], path=p)
    if res['binding'] == 'guess':
        heads = '; '.join(f"{lb} ({st[lb]['text'][:40]})" for lb in res['candidates'][:6])
        extra = ' 返事の中に問いの段のほかにも番号つきの見出し・一覧がある。' if numbered_outside_blocks(w0) else ''
        return (f'🔒 board-asks: 本人の答えの結び先が決まらない (候補: {heads}).{extra}'
                ' 送る・決定を記録する・別の session に頼む・session を畳む操作は止まる。'
                ' 返事の 1 行目で「〜と読みました。よいですか」 と確かめる (本人が印か「はい」 で答えると解ける)。 読む・調べる・下書きは止めない')
    heads = '; '.join(f"{lb} ({st[lb]['text'][:40]})" for lb in res['labels'])
    how = {'label': '印で', 'order': '直前の返事の問いの並びで', 'confirmed': '確かめた読みで'}[res['binding']]
    return (f'board-asks: 本人の答えを {heads} に結んだ ({how})。 返事の 1 行目に印と問いの頭を書く。'
            ' 本人の裁定なら、 その問いの key の記録 (TODO の decided など) に本人の語のまま書く')


def hook_pretool(root, data, path=None):
    """PreToolUse: while this session's latest answer is a guess, stop effective actions. A deny reason or None."""
    eff = effect(data.get('tool_name') or '', data.get('tool_input') or {})
    if not eff:
        return None
    session = data.get('session_id') or _me(None)
    g = pending_guess(load(Path(path) if path else ledger_path(root)), session)
    if not g:
        return None
    c = ', '.join(g.get('candidates') or [])
    return (f'🔒 board-asks: 本人の答え「{(g.get("quote") or "")[:60]}」 の結び先が決まっていない (候補 {c}) ので、 {eff} は止めた。'
            ' 先に 1 行で「〜と読みました。よいですか」 と本人に確かめる。 本人が印か「はい」 で答えると解ける')


def hook_stop(root, data, path=None):
    """Stop: record the ask labels the reply printed; send back once a reply that asks the owner without labels."""
    session = data.get('session_id') or _me(None)
    w0, _ = windows(data.get('transcript_path') or '')
    labels = labels_in(w0)
    if labels:
        mark_shown(root, labels, session=session, path=path)
    if data.get('stop_hook_active') or labels or not ASK_RE.search(w0):
        return None
    sf = _state_file(session)
    key = hashlib.sha256(w0[-4000:].encode('utf-8')).hexdigest()[:16]
    try:
        if json.loads(sf.read_text()).get('sent_back') == key:
            return None
    except (OSError, ValueError):
        pass
    sf.write_text(json.dumps({'sent_back': key}))
    return ('board-asks: 本人に答えを求める文があるのに、 掲示板の問いの印 (〔問 H12〕 の形) が付いていない。'
            f' 問いを立ててから (python3 {Path(__file__).resolve()} ask --root <掲示板> --text … --recommend … --ground <理由>)、'
            ' 道具が出した問いの段を短い追記に貼る。 本人の裁定が要らない問いなら、 問わずに決めて報告する追記にする')


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
    for a in sorted(answered, key=lambda a: a['answers'][-1]['created_at'] if a['answers'] else '', reverse=True):
        ans = next((x for x in reversed(a['answers']) if x.get('binding') in SETTLED and a['label'] in (x.get('labels') or [])), {})
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
    ap.add_argument('--key', action='append', default=[], help='with several --text, a key applies to all of them')
    ap.add_argument('--evidence', action='append', default=[])
    ap.add_argument('--applied', action='store_true')
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
            items = [{'text': t, 'recommend': a.recommend[i] if a.recommend else '',
                      'ground': a.ground[i] if len(a.ground) == n else a.ground[0], 'keys': a.key,
                      'evidence': (a.evidence[i] if len(a.evidence) == n else (a.evidence[0] if a.evidence else '')),
                      'applied': a.applied} for i, t in enumerate(a.text)]
            if n > 1 and a.key:
                raise ValueError('key は問い 1 つずつに付ける (--text を 1 つにして呼び分ける)')
            res = ask(a.root, items, session=a.session, agent=a.agent, project=a.project)
            _print(res) if a.json else print(format_block(res))
            return 0 if any(r['status'] != 'refused' for r in res) else 3
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
            r2 = ask(None, [{'text': '問い一 (別の窓)', 'ground': 'choice', 'keys': ['todo:x:1']}], session='s2', path=led)
            check(r2[0]['status'] == 'reused' and r2[0]['label'] == 'H1', '同じ key の開いた問いは使い回す')
            check(ask(None, [{'text': '理由なし', 'ground': 'nothing'}], session='s1', path=led)[0]['status'] == 'refused',
                  '理由の無い問いは立てない')
            r4 = ask(None, [{'text': '規則', 'ground': 'rule'}], session='s1', path=led)
            check(r4[0]['status'] == 'refused' and 'evidence' in r4[0]['message'], '規則の理由には変更の在りかが要る')
            stub = Path(td) / 'validator.py'
            stub.write_text('import json,sys\nev=sys.argv[sys.argv.index("--evidence")+1]\n'
                            'print(json.dumps({"ok": "needs" in ev, "message": "stub"}))\n', encoding='utf-8')
            r5 = ask(None, [{'text': '要らない規則', 'ground': 'rule', 'evidence': 'r@HEAD:free'}], session='s1', path=led, validator=stub)
            r6 = ask(None, [{'text': '要る規則', 'ground': 'rule', 'evidence': 'r@HEAD:needs'}], session='s1', path=led, validator=stub)
            check(r5[0]['status'] == 'refused' and r6[0]['status'] == 'made' and r6[0]['label'] == 'H3', f'判定の道具が要らないと言えば立てない {r5} {r6}')
            r7 = ask(None, [{'text': '道具なし', 'ground': 'rule', 'evidence': 'r@HEAD:x'}], session='s1', path=led,
                     validator=Path(td) / 'missing.py')
            check(r7[0]['status'] == 'made' and r7[0]['message'].startswith('⚠️'), '判定の道具が無ければ立てて、 確かめていないと言う')
            blk = format_block(r)
            check('〔問 H1〕 問い一' in blk and 'おすすめ: はい' in blk, '問いの段の形')
            check(shown_by(load(led), 's2') == ['H1'], '使い回した問いも見せた問いに数える')
            # binding
            open4 = ['H1', 'H2']
            check(bind('H2 OK', open4, [], open4) == {'binding': 'label', 'labels': ['H2'], 'candidates': []}, '印で答えた')
            check(bind('Ｈ２　ＯＫ', open4, [], open4)['labels'] == ['H2'], '全角の印も読む')
            check(bind('１２OK', open4, [], open4) == {'binding': 'order', 'labels': ['H1', 'H2'], 'candidates': []},
                  '並びの番号 = 直前の返事の問いの段だけなら確定')
            check(bind('１　はい\n２　来週でいい', open4, [], open4)['labels'] == ['H1', 'H2'], '行ごとの番号')
            check(bind('１はメールで伝えよう', open4, [], open4, other_numbered_now=True)['binding'] == 'guess',
                  '番号つきの見出しもあれば推定')
            b = bind('1 OK', ['H3'], ['H1'], ['H1', 'H3'])
            check(b['binding'] == 'guess' and b['candidates'] == ['H3', 'H1'], f'前の返事にも開いた問いがあれば推定 {b}')
            check(bind('3 OK', open4, [], open4)['binding'] == 'guess', '並びの外の番号は推定')
            check(bind('全部おすすめで', open4, [], open4)['labels'] == open4, '全部 = 直前の問い全部')
            check(bind('3 つとも案どおり', ['H1', 'H2', 'H4'], [], ['H1', 'H2', 'H4'])['labels'] == ['H1', 'H2', 'H4'],
                  '「3 つとも」 は数の答え = 全部')
            check(bind('12/24でいいよ', ['H1'], [], ['H1'])['binding'] == 'none', '日付は番号でない')
            check(bind('それより先にメールを見て', ['H1'], [], ['H1'])['binding'] == 'none', '答えでない発言は結ばない')
            check(bind('はい', ['H1'], [], ['H1'])['labels'] == ['H1'], '問い 1 つへの「はい」')
            check(bind('はい', open4, [], open4)['binding'] == 'guess', '問い 2 つへの「はい」 は推定')
            check(numbered_outside_blocks('### 1. 報告\n〔問 H1〕 x\n') and not numbered_outside_blocks('〔問 H1〕 x\n```\n1. code\n```'),
                  '問いの段と code の外の番号だけを数える')
            # answers and the stop on effective actions
            answer(None, [], '1 OK', 'guess', session='s1', candidates=['H1', 'H3'], path=led)
            check(hook_pretool(None, {'session_id': 's1', 'tool_name': 'SendMessage', 'tool_input': {}}, path=led),
                  '推定のあいだは別の session への message を止める')
            check(hook_pretool(None, {'session_id': 's1', 'tool_name': 'Read', 'tool_input': {}}, path=led) is None, '読むのは止めない')
            check(hook_pretool(None, {'session_id': 's1', 'tool_name': 'Edit', 'tool_input': {'file_path': '/r/todo/a.yaml'}}, path=led),
                  'TODO の記録も止める')
            check(hook_pretool(None, {'session_id': 's1', 'tool_name': 'Bash',
                                      'tool_input': {'command': 'python3 send_mail.py --to x --send'}}, path=led), '送信の道具も止める')
            check(hook_pretool(None, {'session_id': 's1', 'tool_name': 'Bash',
                                      'tool_input': {'command': 'python3 board_asks.py answer --label H1 --binding confirmed'}}, path=led) is None,
                  '読みを記録する道具は止めない')
            check(hook_pretool(None, {'session_id': 's2', 'tool_name': 'SendMessage', 'tool_input': {}}, path=led) is None,
                  '別の session は止めない')
            check(guess_marker('s1').exists(), '推定のあいだは印の file がある (hook が python を起こす前に見る)')
            answer(None, ['H1'], 'H1 です', 'confirmed', session='s1', path=led)
            check(hook_pretool(None, {'session_id': 's1', 'tool_name': 'SendMessage', 'tool_input': {}}, path=led) is None,
                  '確かめた後は解ける')
            check(not guess_marker('s1').exists(), '解けたら印の file を消す')
            st = state(load(led))
            check(st['H1']['status'] == 'answered' and st['H2']['status'] == 'open', '答えの状態')
            withdraw(None, 'H2', '他で決まった', session='s1', path=led)
            check(state(load(led))['H2']['status'] == 'withdrawn', '取り下げ')
            d = digest(None, 's1', path=led)
            check('✅ H1' in d and 'H1 です' in d and '❓ H3' in d, f'開始・圧縮の後の出力 {d[:160]}')
            check(digest(None, 'nobody', path=led) == '', '問いの無い session には何も出さない')
            check('H1' in precompact_text(None, {'session_id': 's1'}, path=led), '圧縮の前の指示に印を出す')
            # hooks on a transcript
            tr = Path(td) / 't.jsonl'

            def write_tr(reply):
                lines = [{'type': 'user', 'message': {'role': 'user', 'content': 'RCA を見せて'}},
                         {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': reply}]}}]
                tr.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in lines) + '\n', encoding='utf-8')
            write_tr('### 1. 報告\n〔問 H3〕 進めてよいですか')
            w0, w1 = windows(str(tr))
            check(labels_in(w0) == ['H3'] and w1 == '', '直前の窓の問いの印')
            check(hook_stop(None, {'session_id': 's9', 'transcript_path': str(tr)}, path=led) is None, '印つきの問いは差し戻さない')
            check('H3' in shown_by(load(led), 's9'), '返事に出した印を見せた問いに記録する')
            msg = hook_prompt(None, {'session_id': 's9', 'transcript_path': str(tr), 'prompt': '１はメールで伝えよう'}, path=led)
            check(msg and '🔒' in msg, f'見出しの番号と問いの段が並ぶ返事への「１は…」 は推定 {msg}')
            check(hook_pretool(None, {'session_id': 's9', 'tool_name': 'SendMessage', 'tool_input': {}}, path=led), '推定で止まる')
            msg = hook_prompt(None, {'session_id': 's9', 'transcript_path': str(tr), 'prompt': 'H3 のこと'}, path=led)
            check(msg and '確かめた読み' in msg, f'印で答え直すと確定 {msg}')
            check(hook_pretool(None, {'session_id': 's9', 'tool_name': 'SendMessage', 'tool_input': {}}, path=led) is None, '解ける')
            write_tr('これで進めてよいですか')
            stop = hook_stop(None, {'session_id': 's8', 'transcript_path': str(tr)}, path=led)
            check(stop and '印' in stop, '印の無い問いは差し戻す')
            check(hook_stop(None, {'session_id': 's8', 'transcript_path': str(tr)}, path=led) is None, '同じ返事は繰り返し差し戻さない')
            check(hook_prompt(None, {'session_id': 's7', 'transcript_path': str(tr), 'prompt': '<system-reminder>x'}, path=led) is None,
                  '注入の文は答えに数えない')
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
