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
  `request:<id>`, `session:<id>`). **A key names one question**: an open ask with the same key is shown again under its
  label (`--reword` with what changed keeps the label for the same question in other words), and a question already
  answered under that key is not asked again (the earlier answer is printed; `--reask` with a reason asks anew).
  The ask block puts the question first and the label after it; the owner is never asked to type a label.
- Before an ask is made it passes a **gate**: the ground must be one the owner alone can decide (GROUNDS); a policy
  check before implementation is asked once per piece of work (`request:<id>`, or `session:<own id>` for a window
  without a board request) and is refused from a worker of that request (its assignee or claimant); and a change named
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
                                   [--evidence <repo>@<rev>:<path>] [--applied] [--denied '<guard's reason>']
                                   [--reask '<what changed>'] [--reword '<what changed>'] [--project P] [--json]
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
    'policy': '実装の前の方針の確認 (1 つの作業に 1 回。 その依頼の worker からは立てない)',
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
        elif t == 'reword':
            a = asks.get(r.get('label'))
            if a is not None and a['status'] == 'open':
                a.setdefault('rewords', []).append({'from': a['text'], 'reason': r.get('reason', ''), 'created_at': r.get('created_at', '')})
                a['text'] = r.get('text') or a['text']
                if r.get('recommend'):
                    a['recommend'] = r['recommend']
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


def _resolve_evidence(evidence, root=None):
    """(evidence, error). A relative repo dir in `<repo>@<rev>:<path>` is resolved against the board root and its parents
    (the work root holding the repos), then the current dir, and handed to the validator as an absolute path. A repo
    found nowhere is an error (the ask is refused: fix the evidence). Measured: the validator ran `git -C <repo>` from the
    asking shell's directory, so the same evidence judged "no ruling needed" from the work root and "unreadable, asked
    anyway" from a repo directory, and the unreadable branch let asks through that needed no ruling."""
    repo, sep, rest = (evidence or '').partition('@')
    if not sep or not repo:
        return evidence, ''          # malformed: the validator reports it
    p = Path(os.path.expanduser(repo))
    if p.is_absolute():
        return (evidence, '') if p.is_dir() else (evidence, f'在りかの repo {repo} が無い (在りかを直して立て直す。 repo の dir の絶対 path が確か)')
    bases = []
    if root:
        r = Path(root).expanduser().resolve()
        bases += [r, *r.parents]
    bases.append(Path.cwd())
    for b in bases:
        if (b / p).is_dir():
            return f'{(b / p).resolve()}@{rest}', ''
    return evidence, (f'在りかの repo {repo} が掲示板の root の上の dir にも作業 dir にも無い = 判定の道具が読めず、 裁定の要否を'
                      ' 確かめないまま立ててしまう (在りかを直して立て直す。 repo の dir の絶対 path が確か)')


def _session_transcript(session):
    """The asking session's Claude Code transcript (BOARD_ASKS_TRANSCRIPT overrides, for the selftest), or None."""
    env = os.environ.get('BOARD_ASKS_TRANSCRIPT')
    if env:
        return Path(os.path.expanduser(env))
    if not session or session == 'unknown' or not re.fullmatch(r'[0-9a-f-]{8,64}', session):
        return None
    import glob
    hits = glob.glob(os.path.expanduser(f'~/.claude*/projects/*/{session}.jsonl'))
    return Path(max(hits, key=os.path.getmtime)) if hits else None


def _denied_seen(session, denied):
    """True = the start of `denied` is in a tool result of the asking session's transcript (the guard's own refusal was
    copied), False = the transcript was read and the text is absent (a paraphrase, or something that happened in another
    window), None = no transcript to read. Measured: a conductor wrote its own account ("the reviewer did not approve")
    into --denied, and the validator's "no ruling needed" was overridden by it."""
    t = _session_transcript(session)
    if t is None or not t.is_file():
        return None
    want = _norm(denied)[:40]
    if not want:
        return False
    try:
        with open(t, encoding='utf-8', errors='replace') as f:
            for line in f:
                if '"tool_result"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                content = (rec.get('message') or {}).get('content')
                for c in content if isinstance(content, list) else []:
                    if not (isinstance(c, dict) and c.get('type') == 'tool_result'):
                        continue
                    body = c.get('content')
                    text = body if isinstance(body, str) else ' '.join(
                        x.get('text', '') for x in body or [] if isinstance(x, dict))
                    if want in _norm(text):
                        return True
    except OSError:
        return None
    return False


REVIEW_GATED = ('choice', 'protected', 'rule', 'outbound')   # grounds a reviewer's accept classifies (policy and fact are not)
ORIGIN_KEYS = ('request:', 'todo:', 'plan:', 'session:')     # keys that name where a question came from
REVIEW_WINDOW_H = 24


def _request_file(root, request_id):
    if not root or not request_id:
        return None
    hits = list(Path(root).expanduser().glob(f'events/*/*/*--{request_id}.json'))
    return hits[0] if hits else None


def _review_classes(root, request_id):
    """The owner-ruling classes of the latest accept of a request on this board (`review-owner: <class>: …` lines of the
    reviewer's form), an empty set when the accept names none, or None when the request has no accept here."""
    f = _request_file(root, request_id)
    if f is None:
        return None
    accepts = []
    for g in f.parent.glob('*.json'):
        with contextlib.suppress(OSError, ValueError):
            e = json.loads(g.read_text(encoding='utf-8'))
            if e.get('kind') == 'accept' and e.get('request_id') == request_id:
                accepts.append(e)
    if not accepts:
        return None
    last = max(accepts, key=lambda e: str(e.get('created_at', '')))
    return set(re.findall(r'^review-owner: ([a-z]+):', str(last.get('details') or ''), re.M))


def _recent_reviewed(root, me, hours=REVIEW_WINDOW_H):
    """Request ids posted by this session whose accept (by a reviewer's form) is newer than `hours` on this board."""
    if not root or not me or me == 'unknown':
        return []
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).strftime('%Y%m%dT%H%M%SZ')
    out = []
    for g in Path(root).expanduser().glob('events/*/*/*.json'):
        if g.name[:16] < cutoff:
            continue
        with contextlib.suppress(OSError, ValueError):
            e = json.loads(g.read_text(encoding='utf-8'))
            if e.get('kind') != 'accept' or 'review-' not in str(e.get('details') or ''):
                continue
            rid = e.get('request_id') or ''
            req = next(iter(g.parent.glob(f'*--{rid}.json')), None) if rid else None   # same thread dir (a board-wide glob per accept took seconds)
            if req is None:
                continue
            actor = json.loads(req.read_text(encoding='utf-8')).get('actor') or {}
            if any(_same_session(x, me) for x in _ids_of(actor, actor.get('task'))):
                out.append(rid)
    return out


def gate(ground, evidence=None, *, applied=False, validator=None, session=None, denied='', root=None):
    """(ok, message). ok=False = do not ask; the message says why and what to do instead. A change named by evidence is
    judged whatever the ground (a rule change asked under another ground passes the same validator). The asking session
    goes to the validator (the write-time guard's refusal net reads that session). `denied` = the reason the write-time
    guard gave when it stopped this very change: the validator's "no ruling needed" then does not refuse the ask (the two
    disagree only where the validator cannot see what the guard saw), and the reason is kept on the ask."""
    if ground not in GROUNDS:
        return False, f'裁定が要る理由が無い・一覧に無い ({ground!r})。 理由 = {", ".join(GROUNDS)}。 どれでもなければ問わずに決めて報告する'
    if not evidence:
        if ground in JUDGED:
            return False, (f'理由 {ground} には変更の在りか (--evidence <repo>@<commit>:<path> か <repo>@worktree:<path>、 当てる前の候補なら <repo>@candidate=<候補の全文の絶対 path>:<path>) が要る'
                           ' (裁定の要否を機械で判定するため)')
        return True, ''
    evidence, err = _resolve_evidence(evidence, root)
    if err:
        return False, err
    kind = ground if ground in JUDGED else ('protected' if re.search(r'\.tex$', evidence) else 'rule')
    v = Path(validator) if validator else _validator()
    if not v.exists():
        return True, f'⚠️ 判定の道具が無い ({v}) = 裁定の要否を確かめずに立てた'
    args = ([sys.executable, str(v), '--ground', kind, '--evidence', evidence] + (['--applied'] if applied else [])
            + (['--session', session] if session and session != 'unknown' else []))
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=VALIDATOR_TIMEOUT)
        res = json.loads((p.stdout or '').strip().splitlines()[-1] if (p.stdout or '').strip() else '{}')
    except (subprocess.TimeoutExpired, ValueError, OSError) as e:
        return True, f'⚠️ 判定の道具が答えない ({e.__class__.__name__}) = 裁定の要否を確かめずに立てた'
    if res.get('error'):
        return False, f'変更の在りかを判定できない: {res["error"]} (在りかを直して立て直す)'
    if 'ok' not in res:
        return True, f'⚠️ 判定の道具の出力が読めない = 裁定の要否を確かめずに立てた ({(p.stderr or "")[:200]})'
    ok, msg = bool(res['ok']), str(res.get('message') or '')
    if not ok and denied:
        seen = _denied_seen(session, denied)
        if seen is False:
            return False, ('--denied は、 この窓で書く時の守りが止めたときの理由をそのまま写す欄 (この窓の会話記録の tool の結果に'
                           ' 無い文 = 言い換えか、 別の窓で起きたこと)。 当てる前の候補の承認なら、 候補を在りかにして立て直す'
                           ' (--evidence <repo>@candidate=<候補の全文の絶対 path>:<path> = 判定の道具が候補の中身で判定する)')
        warn = '' if seen else ' ⚠️ --denied を会話記録と照らせなかった (この窓の会話記録が見つからない)'
        return True, f'書く時の守りが止めた: {denied[:300]} (判定の道具は「要らない」: {msg[:160]}){warn}'
    if not ok:
        msg += ' (当てた時に書く時の守りが止めたら、 止めた理由を --denied \'<理由>\' に写して立て直す)'
    return ok, msg


def _ids_of(addr, task=''):
    """A board address's session id and the 8-hex native ids kept in its task field (a post made under a role id)."""
    ids = [(addr or {}).get('session_id') or '']
    ids += re.findall(r'(?<![0-9a-f])[0-9a-f]{8}(?![0-9a-f])', str(task or ''))
    return [i for i in ids if i]


def _request_parties(root, request_id):
    """(authors, workers) of a request on this board or a board beside it, or None when its event cannot be found.
    authors = the session that posted it; workers = its assignee, sessions it was handed over to as assignee, and the
    sessions that claimed it (each with the native ids in the task field)."""
    if not root or not request_id:
        return None
    root = Path(root).expanduser()
    roots = [root]
    with contextlib.suppress(Exception):
        sys.path.insert(0, str(HERE))
        import board_config as bc
        roots += [b['root'] for b in bc.discover(root.parent) if Path(b['root']).resolve() != root.resolve()]
    for f in [f for r in roots for f in Path(r).glob(f'events/*/*/*--{request_id}.json')]:
        with contextlib.suppress(OSError, ValueError):
            ev = json.loads(f.read_text(encoding='utf-8'))
            if ev.get('kind') != 'request':
                continue
            actor = ev.get('actor') or {}
            authors = _ids_of(actor, actor.get('task'))
            workers = _ids_of(ev.get('assignee'))
            for g in f.parent.glob('*.json'):
                with contextlib.suppress(OSError, ValueError):
                    e = json.loads(g.read_text(encoding='utf-8'))
                    if e.get('request_id') != request_id:
                        continue
                    if e.get('kind') == 'claim':
                        workers += _ids_of(e.get('actor'), (e.get('actor') or {}).get('task'))
                    elif e.get('kind') == 'handover' and e.get('handover_role') == 'assignee':
                        workers += _ids_of(e.get('target'))
            return authors, workers
    return None


def _request_authors(root, request_id):
    """Ids that stand for the session that posted this request ([] when it cannot be read here)."""
    parties = _request_parties(root, request_id)
    return parties[0] if parties else []


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
        # One policy check per piece of work. It is refused only from a worker of that request: a worker's choices are
        # settled at the requester's review. The requester, a conductor that took over the requester's work, and the
        # reviewer may put it (measured: requiring the posting session refused a conductor's successor). A window
        # without a board request names its own work with session:<its id>.
        rids = [k.split(':', 1)[1] for k in keys if k.startswith('request:')]
        sids = [k.split(':', 1)[1] for k in keys if k.startswith('session:')]
        if not rids and not sids:
            return 'refused', {'status': 'refused', 'text': text, 'message': (
                '方針の確認の問いには、 掲示板の依頼の作業なら --key request:<依頼の id>、 掲示板の依頼の無い窓の作業なら'
                ' --key session:<この窓の session id> が要る (1 つの作業に 1 回だけ)')}
        if sids and not _same_session(sids[0], me):
            return 'refused', {'status': 'refused', 'text': text, 'message': (
                f'session:{sids[0][:24]} はこの窓の id でない。 方針の確認は、 その作業をしている窓が自分の id で立てる')}
        if rids:
            parties = _request_parties(root, rids[0])
            if not parties:
                return 'refused', {'status': 'refused', 'text': text, 'message': (
                    f'依頼 {rids[0]} の event を手元の掲示板 (--root と、 その隣の掲示板) で見つけられない ='
                    ' その依頼の worker かを確かめられない。 依頼の掲示板を最新にしてから立て直す')}
            authors, workers = parties
            if any(_same_session(x, me) for x in workers) and not any(_same_session(x, me) for x in authors):
                return 'refused', {'status': 'refused', 'text': text, 'message': (
                    '方針の確認の問いは、 その依頼の worker (宛先・claim した session) からは立てない。'
                    ' 方針の中の選択は依頼元に submit して検収で決める (本人に立てない)')}
    same = next((a for a in st.values() if a['status'] == 'open' and keys and set(keys) & set(a.get('keys') or [])), None)
    if same:
        if _norm(same['text']) == _norm(text):
            return 'reused', {'status': 'reused', 'label': same['label'], 'text': same['text'], 'recommend': same.get('recommend', ''),
                              'message': '同じ問い (同じ key・同じ文) が開いている = 新しく立てずにその印で問う'}
        if it.get('reword'):
            # the same question in other words keeps its label (measured: re-asking under a new label changed the
            # owner's handle for the same matter twice in one morning)
            return 'reworded', {'status': 'reworded', 'label': same['label'], 'text': text,
                                'recommend': (it.get('recommend') or same.get('recommend') or '').strip()[:MAX_TEXT],
                                'reason': it['reword'], 'message': f'言い直した (同じ印のまま。 変えたこと: {it["reword"][:120]})'}
        return 'refused', {'status': 'refused', 'text': text, 'label': same['label'], 'message': (
            f'同じ key の問い 「{same["text"][:80]}」 〔問 {same["label"]}〕 が開いている。'
            ' 同じ問いの言い直しなら --reword \'<何を変えたか>\' (同じ印のまま文を変える)。'
            ' 別の問いなら key を問いごとに分ける (例: <key>#2)')}
    if not text:
        return 'refused', {'status': 'refused', 'text': '', 'message': '問いの文が空'}
    if it.get('ground') in REVIEW_GATED and root:
        # A question that comes out of a reviewer's accept goes to the owner only when the reviewer classified it as the
        # owner's (`review-owner: <class>:`); what the reviewer decided (`review-decided:`) is not asked again. Measured:
        # a conductor re-asked as the owner's choice a question its reviewer had decided, and asked the owner to approve
        # files the reviewer had not classified as the owner's. Policy checks before implementation are not gated here.
        # `request:<id>#2` names a second question out of the same request (the documented way to split keys)
        rids = [k.split(':', 1)[1].split('#', 1)[0] for k in keys if k.startswith('request:')]
        if rids:
            classes = _review_classes(root, rids[0])
            if classes is not None and it['ground'] not in classes:
                return 'refused', {'status': 'refused', 'text': text, 'message': (
                    f'依頼 {rids[0]} の検収係の受け取りは、 本人に回す問いとして {it["ground"]} を挙げていない'
                    f' (挙げたのは: {", ".join(sorted(classes)) or "なし"})。 検収係が決めた答え (受け取りの review-decided) で進める。'
                    ' 検収係が本人のものと分類し直すなら、 その受け取りの後に検収係が note か受け取り直しで書く')}
        elif not any(k.startswith(ORIGIN_KEYS) for k in keys) and not (it.get('not_from_review') or '').strip():
            recent = _recent_reviewed(root, me)
            if recent:
                return 'refused', {'status': 'refused', 'text': text, 'message': (
                    f'この窓が出した依頼に、 最近 {REVIEW_WINDOW_H} 時間の検収係の受け取りがある (例: {recent[0]})。'
                    ' 検収係の受け取りから出す問いには --key request:<依頼 id> を付ける (受け取りが本人のものと分類した問いだけが立つ)。'
                    ' 受け取りから出したのでない問いなら、 どこから出たかの key (todo:<repo>:<id> / plan:<path>#<item> / session:<id>)'
                    ' か --not-from-review \'<1 行>\' を付ける')}
    note = it.get('_note') or ''
    if it.get('ground') != 'policy' and re.search(r'方針|\bpolicy\b', text, re.I) and '--ground policy' not in note:
        note = ' '.join(x for x in (note, '⚠️ 方針の確認なら --ground policy (1 つの作業に 1 回、 依頼の worker からは立てない)') if x)
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
            ok, msg = gate(payload.get('ground'), payload.get('evidence'), applied=bool(payload.get('applied')),
                           validator=validator, session=me, denied=payload.get('denied') or '', root=root)
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
            if kind == 'reworded':
                new.append({'type': 'reword', 'label': payload['label'], 'text': payload['text'], 'recommend': payload['recommend'],
                            'reason': payload['reason'][:MAX_TEXT], 'session': me, 'created_at': now_iso()})
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
                   'denied': (payload.get('denied') or '')[:MAX_TEXT],
                   'session': me, 'agent': agent, 'project': project, 'created_at': now_iso()}
            new.append(rec)
            out.append({'status': 'made', 'label': label, 'text': rec['text'], 'recommend': rec['recommend'], 'message': msg})
        _append(p, new)
    return out


def format_block(results):
    lines = []
    for r in results:
        if r['status'] in ('made', 'reused', 'reworded'):
            # the content first and the label after it: the owner reads the question, the label is only a handle
            # (measured: a label at the head of the line was then used like a number, "H3・H12・H13 は…")
            lines.append(f"{r['text']} 〔問 {r['label']}〕")
            if r.get('recommend'):
                lines.append(f"　おすすめ: {r['recommend']}")
            if '⚠️' in r.get('message', '') or '別の問い' in r.get('message', '') or r['status'] == 'reworded':
                lines.append(f"　({r['message']})")
        elif r['status'] == 'answered-before':
            lines.append(f"(問わない) {r['text'][:80]} 〔問 {r['label']}〕 は本人が答え済み: 「{r.get('quote', '')[:200]}」 — {r['message']}")
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
    # separate reply blocks are separate paragraphs (a single line break would merge an earlier turn's last paragraph
    # with the next turn's first one, and the Stop check would read the pair as a new paragraph)
    w0 = '\n\n'.join(tx for r, tx in rows[last + 1:] if r == 'assistant')
    w1 = '\n\n'.join(tx for r, tx in rows[prev + 1:last] if r == 'assistant') if last >= 0 else ''
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
# An asking phrase that does not ask the owner here (each measured in a send-back of the Stop check):
# reported words ("worker が決めてほしいと言った細かい 4 つは、 検収で決まり…"),
REPORTED_AFTER = re.compile(r'^\s*(?:と(?:言|い[っうわ]|書|頼|求|伝|聞|尋|問|申|返|あ|の)|という|との|って)')
# the owner sent to another window ("その worker の窓から確認が出るので、 そこで答えてください"; "この窓で" still asks),
ROUTED_RE = re.compile(r'(?<!こ)の\s*(?:窓|ウィンドウ|セッション|session|画面)\s*(?:で|から|を開いて|に出)', re.I)
# an instruction on how to answer, with no question in the sentence ("本人は普段の言葉で答えてください"),
MANNER_ASKS = ('答えてください', '教えてください')
QUESTION_CONTENT = re.compile(r'か[、。\s」]|かを|かどうか|？|\?|どちら|どっち|どれ|どう|いつ|何|誰|おすすめ|推す|よいか|いいか')
# and a heading line ("**本人に決めてほしいもの**"), which is read together with the paragraph after it.
HEADING_PARA = re.compile(r'^\s*(?:#{1,6}\s\S.*|(?:[-*]\s*)?\*\*[^*\n]+\*\*\s*[:：]?|[^\n]{1,60}[:：])\s*$')
# Labels used as numbers for the owner (rule: a label is only appended to the content = claude-config
# conventions/concise-output.md#decision-questions, "作業側の符号だけで聞かない"; measured: the owner was told to
# answer "「H14 送って」" and "番号で", labels were listed without content ("H3・H12・H13 は…"), and put at line heads).
TYPE_VERB = r'(?:返して|返事して|答えて|お答え|言って|教えて|送って|打って|書いて|伝えて|選んで|どうぞ)'
QUOTE_TYPE_RE = re.compile(rf'「([^「」\n]*)」\s*(?:と|で|か)\s*(?:「([^「」\n]*)」\s*(?:と|で)\s*)?{TYPE_VERB}')
# only a request form ("番号で教えてください"), not the name of a matter ("番号で答えが返ってくる件") or a line number (行番号)
BY_NUMBER_RE = re.compile(r'(?<!行)(?:番号|印|記号|符号|ラベル)\s*で\s*(?:答えて|教えて|返して|お答え|お返事|どうぞ|選んで|指定して|伝えて|書いて|打って)')
NEGATED_AFTER = re.compile(r'^.{0,12}?(?:やめ|ない|不要|要ら|しな|なくて|ません|ず[、。])')
ORDINAL_TOKEN = re.compile(r'\d{1,2}\s*(?:つ目|番目|番)')
OWN_MARK = 'board-asks:'   # the start of this hook's Stop reasons (the app records them as "Stop hook feedback: board-asks: …")
SEEN_MAX = 400


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


QUOTED_RE = re.compile(r'「[^「」\n]*」|『[^『』\n]*』|`[^`\n]*`|"[^"\n]*"')


def unquoted(text):
    """The text without phrases in Japanese brackets, inline code and double quotes: prose that explains a rule quotes
    the asking phrase without asking anyone (measured). Nested brackets are removed from the inside out (measured: an
    RCA citing 「「H14 送って」 と返して」 left the outer remainder in the prose)."""
    t, prev = text or '', None
    while prev != t:
        prev, t = t, QUOTED_RE.sub('', t)
    return t


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


def _sentence_at(text, i):
    """The sentence (between 。！？ or line breaks) that holds position i."""
    start = max(text.rfind(c, 0, i) for c in '。！？!?\n') + 1
    ends = [j for j in (text.find(c, i) for c in '。！？!?\n') if j >= 0]
    return text[start:(min(ends) + 1 if ends else len(text))]


def owner_ask_in(para):
    """The asking phrase by which this paragraph asks the owner here, or None. Not counted: phrases in quotes, reported
    words, an owner sent to answer in another window, and an instruction on how to answer with no question in it."""
    u = unquoted(para)
    for m in ASK_RE.finditer(u):
        if REPORTED_AFTER.match(u[m.end():]):
            continue
        sent = _sentence_at(u, m.start())
        if ROUTED_RE.search(sent):
            continue
        if m.group(0) in MANNER_ASKS and not QUESTION_CONTENT.search(sent):
            continue
        return m.group(0)
    return None


def paragraphs(text):
    """Paragraphs split at blank lines; a one-line heading is joined to the paragraph after it (the heading may carry the
    asking phrase and the list under it the questions, or the list may carry the labels)."""
    raw = [p for p in re.split(r'\n\s*\n', text or '') if p.strip()]
    out, i = [], 0
    while i < len(raw):
        p = raw[i]
        if '\n' not in p.strip() and HEADING_PARA.match(p.strip()) and i + 1 < len(raw):
            out.append(p + '\n' + raw[i + 1])
            i += 2
            continue
        out.append(p)
        i += 1
    return out


def _key(kind, text):
    return kind + ':' + hashlib.sha256(_norm(text).encode('utf-8')).hexdigest()[:16]


def turn_window(transcript, tail_bytes=4 << 20):
    """(assistant text written since the previous Stop, whether the previous Stop was this hook's send-back).
    The desktop app writes a `system` / `stop_hook_summary` record after every Stop's hooks have finished, so at Stop
    time the last such record belongs to the previous Stop. (None, None) when the tail holds none (first Stop of a
    session, or a harness that does not write it): the caller then reads the text since the owner's last words."""
    rows = []
    try:
        with open(transcript, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail_bytes))
            data = f.read().decode('utf-8', 'replace').splitlines()
    except OSError:
        return None, None
    for line in data:
        with contextlib.suppress(ValueError):
            rec = json.loads(line)
            if not isinstance(rec, dict) or rec.get('isSidechain'):
                continue
            if rec.get('type') == 'system' and rec.get('subtype') == 'stop_hook_summary':
                rows.append(('stop', ''))
                continue
            role, texts = _texts(rec)
            for tx in texts:
                if role == 'assistant':
                    rows.append(('reply', tx))
                elif role == 'user' and tx.lstrip().startswith('Stop hook feedback'):
                    rows.append(('feedback', tx))
    stops = [i for i, (k, _) in enumerate(rows) if k == 'stop']
    if not stops:
        return None, None
    last = stops[-1]
    prev = stops[-2] if len(stops) > 1 else -1
    text = '\n\n'.join(tx for k, tx in rows[last + 1:] if k == 'reply')
    own = any(k == 'feedback' and OWN_MARK in tx for k, tx in rows[prev + 1:last])
    return text, own


def _content_words(text):
    """Words that name an ask's content (runs of kanji / katakana of 2+, latin words of 3+, dates) from its first 60 chars."""
    t = unicodedata.normalize('NFKC', text or '')[:60]
    return {w for w in re.findall(r'[一-龥々ァ-ヶー]{2,}|[A-Za-z]{3,}|\d{1,2}/\d{1,2}', t)}


def label_usage(text, labels, heads):
    """Places where the reply uses ask labels as numbers for the owner: [(kind, snippet)]. kind = type (the owner is told
    to answer by a label, a number or an ordinal), bare (two or more labels in a sentence without their content), head
    (a label at the head of a line). labels = labels this session may name; heads = label -> the ask's text."""
    t = unicodedata.normalize('NFKC', prose_only(text))
    u = unquoted(t)   # labels and phrases inside quotes are cited, not used (measured: an RCA quoting "H3・H12・H13 は")
    known = sorted({lb for lb in labels if lb in heads}, key=len, reverse=True)
    kl = '(?<![A-Za-z0-9])(?:' + '|'.join(map(re.escape, known)) + ')(?![0-9])' if known else None
    out = []
    for m in QUOTE_TYPE_RE.finditer(t):
        inner = ' '.join(x for x in m.groups() if x)
        before = t[t.rfind('\n', 0, m.start()) + 1:m.start()]
        if before.count('「') > before.count('」'):
            continue   # inside an outer quote = a cited example (measured: an RCA quoting 「「H14 送って」 と返してください」)
        if ORDINAL_TOKEN.search(inner) or (kl and re.search(kl, inner)):
            out.append(('type', m.group(0)))
    for m in BY_NUMBER_RE.finditer(u):
        if not NEGATED_AFTER.match(u[m.end():]):
            out.append(('type', _sentence_at(u, m.start()).strip()))
    if kl:
        flat = re.sub(r'〔問\s*([A-Z]\d{1,5})〕', r' \1 ', u)
        run = re.compile(rf'{kl}(?:\s*(?:[・、,，〜~]|と|\s)\s*{kl})+')
        for m in run.finditer(flat):
            sent = _sentence_at(flat, m.start())
            named = re.findall(kl, m.group(0))
            # a label whose ask has no content word to look for is not judged (nothing to compare)
            if any(_content_words(heads[lb]) and not any(w in sent for w in _content_words(heads[lb])) for lb in named):
                out.append(('bare', sent.strip()))
        head_re = re.compile(rf'^[ \t]*(?:[-*・][ \t]*)?(?:\*\*)?[ \t]*(?:〔問[ \t]*)?{kl}[ \t]*(?:〕)?[ \t]*(?:\*\*)?(?=[\s:：、.)）]|$)', re.M)
        src, prev = t, None
        while prev != src:   # blank quotes from the inside out, keeping positions (line starts stay where they are)
            prev, src = src, QUOTED_RE.sub(lambda x: ' ' * len(x.group(0)), src)
        for m in head_re.finditer(src):
            end = src.find('\n', m.start())
            out.append(('head', t[m.start():end if end >= 0 else len(t)].strip()))
    seen, uniq = set(), []
    for kind, snip in out:
        if (kind, snip) not in seen:
            seen.add((kind, snip))
            uniq.append((kind, snip))
    return uniq


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
        heads = '; '.join(f"{st[lb]['text'][:40]} ({lb})" for lb in res['candidates'][:6])
        extra = ' 返事の中に問いの段のほかにも番号つきの見出し・一覧がある。' if numbered_outside_blocks(w0) else ''
        return (f'🔒 board-asks: 本人の答えの結び先が決まらない (候補: {heads}).{extra}'
                ' 送る・決定を記録する・別の session に頼む・session を起こす・畳む操作は止まる。'
                ' 返事の 1 行目で、 候補を 1 つだけ問いの中身で名指し、 印は後ろに添えて「〈問いの中身〉 (H12) と読みました。よいですか」'
                ' と確かめる (本人が「はい」 か中身か印で答えると解ける。 本人に印を打つよう頼まない)。 読む・調べる・下書きは止めない')
    heads = '; '.join(f"{st[lb]['text'][:40]} ({lb})" for lb in res['labels'])
    with contextlib.suppress(OSError):
        _bound_file(session).write_text(json.dumps(res['labels']))
    if res.get('defer'):
        return (f'board-asks: 本人の答えは {heads} の先送り (問いは開いたまま)。'
                ' 返事の 1 行目に問いの中身を書き、 印は後ろに添える')
    how = {'label': '印で', 'order': '直前の返事の問いの並びで', 'confirmed': '確かめた読みで'}[res['binding']]
    return (f'board-asks: 本人の答えを {heads} に結んだ ({how})。 返事の 1 行目に結んだ問いの中身を書き、 印は後ろに添える'
            ' (例: 「〈問いの中身〉 (H12) への答えと読みました」)。'
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
            ' 先に 1 行で、 候補を 1 つだけ問いの中身で名指し (印は後ろに添える)、 「〜と読みました。よいですか」 と本人に確かめる。'
            ' 本人が「はい」 か中身か印で答えると解ける')


def _first_line(text):
    return next((ln for ln in (text or '').splitlines() if ln.strip()), '')


def _seen(sf):
    try:
        return list(json.loads(sf.read_text()).get('seen') or [])
    except (OSError, ValueError, AttributeError):
        return []


def hook_stop(root, data, path=None):
    """Stop: record the ask labels the reply printed; send back once (a) a reply that asks the owner in a paragraph
    without an ask label, (b) a reply after a bound answer whose first line does not name the bound label, (c) a reply
    that uses labels as numbers for the owner (tells the owner to answer by a label or a number, lists labels without
    their content, or puts a label at the head of a line).
    It reads only the text written since the previous Stop (turn_window), and never sends back the same paragraph or
    sentence twice (its key is kept in the session's state file): the first version read everything since the
    owner's last words and keyed the send-back on the tail of that text, so each later turn started by a task
    notice or another session's message sent the same earlier paragraph back again (measured, many times in one window).
    A continuation after another hook's send-back is judged (its addendum is new text); one after this hook's own
    send-back, or of an unknown shape, is not (hook-authoring.md#stop-hook-active-other-hooks)."""
    session = data.get('session_id') or _me(None)
    p = Path(path) if path else ledger_path(root)
    tp = data.get('transcript_path') or ''
    w0, _ = windows(tp)
    labels = labels_in(w0)
    if labels:
        mark_shown(root, labels, session=session, path=p)
    bf = _bound_file(session)
    bound = []
    with contextlib.suppress(OSError, ValueError):
        bound = json.loads(bf.read_text())
    with contextlib.suppress(FileNotFoundError):
        bf.unlink()
    turn, own = turn_window(tp)
    if data.get('stop_hook_active') and (own is None or own):
        return None
    text = w0 if turn is None else turn
    sf = _state_file(session)
    seen = _seen(sf)
    new = []
    msgs = []
    if bound and not data.get('stop_hook_active') and not bare_labels(_first_line(w0), bound):
        k = _key('bound', ','.join(bound) + _first_line(w0))
        if k not in seen:
            new.append(k)
            msgs.append(f'返事の 1 行目に、 本人の答えを結んだ問いの中身と、 その後ろに印 ({", ".join(bound)}) を書いていない'
                        ' (例: 「〈問いの中身〉 (H12) への答えと読みました」)')
    recs = load(p)
    st = state(recs)
    known = [lb for lb in shown_by(recs, session) if lb in st] + [lb for lb in labels if lb in st]
    g = pending_guess(recs, session, st)
    allowed = set(known) | set((g or {}).get('candidates') or [])
    loose = []
    for para in paragraphs(prose_only(text)):
        if owner_ask_in(para) and not BLOCK_RE.search(para) and not bare_labels(para, sorted(allowed)):
            k = _key('loose', para)
            if k not in seen and k not in new:
                new.append(k)
                loose.append(para.strip().splitlines()[0][:60])
    if loose:
        here = Path(__file__).resolve()
        msgs.append('本人に答えを求める段に、 掲示板の問いの印 (〔問 H12〕 の形) が付いていない'
                    f' (「{loose[0]}」 ほか)。 問いを立ててから (python3 {here} ask --root <掲示板> --text … --recommend … --ground <理由>)、'
                    ' 短い追記に「上の問いを台帳に立てた」 の 1 行と、'
                    ' 道具が出した問いの段 (中身が先、 印は後ろ) を貼る。 本人に印や番号で答えるよう求める文は書かない'
                    ' (「上の番号は使わない」 は本人に印を使えと言う文に読まれた = 実測)。'
                    ' 本人の裁定が要らない問いなら、 問わずに決めて報告する追記にする')
    heads = {lb: a.get('text', '') for lb, a in st.items()}
    uses = []
    for kind, snip in label_usage(text, sorted(allowed), heads):
        k = _key('use', kind + snip)
        if k not in seen and k not in new:
            new.append(k)
            uses.append((kind, snip))
    if uses:
        what = {'type': '本人に印・番号で答えさせる文', 'bare': '中身の無い印の並び', 'head': '行の頭に置いた印'}
        kinds = []
        for kind, _ in uses:
            if what[kind] not in kinds:
                kinds.append(what[kind])
        msgs.append(f'問いの印を番号のように使っている ({"・".join(kinds)}: 「{uses[0][1][:60]}」 ほか)。 印は問いの中身の後ろに添えるだけにし、'
                    ' 本人に印や番号を打たせない (答え方を示すなら「送って」「推しで」 のような中身を知らなくても言える語で)。'
                    ' 該当の文だけを、 問いの中身で言い直す短い追記にする (前の返事は出し直さない。 正本 ='
                    ' claude-config/conventions/concise-output.md#decision-questions の「作業側の符号だけで聞かない」)')
    if not msgs:
        return None
    with contextlib.suppress(OSError):
        sf.write_text(json.dumps({'seen': (seen + new)[-SEEN_MAX:]}))
    return OWN_MARK + ' ' + ' / '.join(msgs)


def digest(root, session, max_chars=8000, path=None):
    recs = load(Path(path) if path else ledger_path(root))
    st = state(recs)
    mine = shown_by(recs, session)
    opened = [st[lb] for lb in mine if lb in st and st[lb]['status'] == 'open']
    answered = [st[lb] for lb in mine if lb in st and st[lb]['status'] == 'answered']
    if not opened and not answered:
        return ''
    lines = ['📌 この session の本人への問い (掲示板の問いの台帳 = board_asks.py。 依頼・調べを出す前に、 同じ問いがあれば前の答えを読む。'
             ' 本人の裁定は TODO の decided・DESIGN に記録したかを確かめる)',
             '　本人に問うときは、 番号を振らずに先に台帳に立てる (ask)。 問いの段は中身が先・印は後ろ、 本人に印や番号を打たせない。'
             ' 問いを言い直すときは同じ印のまま (--reword)']
    for a in sorted(answered, key=lambda a: _last_settled(a).get('created_at', ''), reverse=True):
        ans = _last_settled(a)
        lines.append(f"✅ {a['text'][:200]} ({a['label']}) → 本人「{(ans.get('quote') or '')[:300]}」"
                     + (f" 読み: {ans['reading'][:150]}" if ans.get('reading') else ''))
    for a in opened:
        lines.append(f"❓ {a['text'][:200]} ({a['label']}) / おすすめ: {a.get('recommend', '')[:150]}")
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
    ap.add_argument('--reword', default='', help='開いた問いを同じ印のまま言い直す (同じ key、 何を変えたか)')
    ap.add_argument('--denied', default='', help='その変更を書く時の守りが止めた理由 (判定の道具が「要らない」 と言っても立てる)')
    ap.add_argument('--not-from-review', default='',
                    help='検収係の受け取りから出したのでない問いの印 (この窓の依頼に最近の受け取りがあるとき、 request: などの key が無ければ要る)')
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
                      'applied': a.applied, 'reask': a.reask, 'denied': a.denied, 'reword': a.reword,
                      'not_from_review': a.not_from_review} for i, t in enumerate(a.text)]
            res = ask(a.root, items, session=a.session, agent=a.agent, project=a.project)
            _print(res) if a.json else print(format_block(res))
            return 0 if any(r['status'] in ('made', 'reused', 'reworded') for r in res) else 3
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
    verbose = bool(os.environ.get('BOARD_ASKS_SELFTEST_VERBOSE'))   # PASS lines too (board_asks.mutants.json reads them)

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print('FAIL', msg)
        elif verbose:
            print('PASS', msg)
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
            rr = Path(td) / 'r'   # the evidence's repo dir must exist (the gate resolves and refuses a missing one)
            rr.mkdir()
            stub = Path(td) / 'validator.py'
            stub.write_text('import json,sys\nev=sys.argv[sys.argv.index("--evidence")+1].split("@",1)[1]\n'
                            'print(json.dumps({"error": "読めない"} if "bad" in ev else {"ok": "needs" in ev, "message": "stub"}))\n',
                            encoding='utf-8')
            r5 = ask(None, [{'text': '要らない規則', 'ground': 'rule', 'evidence': f'{rr}@HEAD:free'}], session='s1', path=led, validator=stub)
            r6 = ask(None, [{'text': '要る規則', 'ground': 'rule', 'evidence': f'{rr}@HEAD:needs'}], session='s1', path=led, validator=stub)
            check(r5[0]['status'] == 'refused' and r6[0]['status'] == 'made' and r6[0]['label'] == 'H3', f'判定の道具が要らないと言えば立てない {r5} {r6}')
            r5b = ask(None, [{'text': '理由を選び直した規則', 'ground': 'choice', 'evidence': f'{rr}@HEAD:free'}], session='s1', path=led, validator=stub)
            check(r5b[0]['status'] == 'refused', '変更の在りかがあれば理由に依らず判定の道具を通す')
            r5c = ask(None, [{'text': '在りかの誤り', 'ground': 'rule', 'evidence': f'{rr}@HEAD:bad'}], session='s1', path=led, validator=stub)
            check(r5c[0]['status'] == 'refused' and '読めない' in r5c[0]['message'], '判定の道具の誤りを理由として返す')
            r5d = ask(None, [{'text': '守りが止めた規則', 'ground': 'rule', 'evidence': f'{rr}@HEAD:free', 'denied': '断った件の網'}],
                      session='s1', path=led, validator=stub)
            check(r5d[0]['status'] == 'made' and '書く時の守りが止めた' in r5d[0]['message'],
                  '書く時の守りが止めた変更は、 判定の道具が要らないと言っても立てる')
            check('--denied' in r5[0]['message'], '要らないと断る時は、 守りが止めた時の立て直し方を添える')
            r7 = ask(None, [{'text': '道具なし', 'ground': 'rule', 'evidence': f'{rr}@HEAD:x'}], session='s1', path=led,
                     validator=Path(td) / 'missing.py')
            check(r7[0]['status'] == 'made' and r7[0]['message'].startswith('⚠️'), '判定の道具が無ければ立てて、 確かめていないと言う')
            # the evidence's relative repo dir is resolved from the board root's parents, not from the asking shell's dir
            # (measured: the same relative evidence judged "no ruling needed" from the work root and "unreadable, asked
            # anyway" from a repo dir)
            work = Path(td) / 'work'
            (work / 'repoA').mkdir(parents=True)
            (work / 'board').mkdir()
            echo = Path(td) / 'echo.py'
            echo.write_text('import json,sys\nev=sys.argv[sys.argv.index("--evidence")+1]\n'
                            'print(json.dumps({"ok": True, "message": "saw " + ev}))\n', encoding='utf-8')
            cwd0 = os.getcwd()
            try:
                os.chdir(rr)
                rv = ask(work / 'board', [{'text': '相対の在りか', 'ground': 'rule', 'evidence': 'repoA@HEAD:x.md'}],
                         session='s1', path=led, validator=echo)
            finally:
                os.chdir(cwd0)
            check(rv[0]['status'] == 'made' and f'saw {(work / "repoA").resolve()}@HEAD:x.md' in rv[0]['message'],
                  f'在りかの相対の repo の名は、 掲示板の root の上の dir から解いて絶対 path で判定の道具に渡す {rv}')
            rm = ask(work / 'board', [{'text': '無い repo の在りか', 'ground': 'rule', 'evidence': 'nowhere@HEAD:x.md'}],
                     session='s1', path=led, validator=echo)
            check(rm[0]['status'] == 'refused' and '無い' in rm[0]['message'],
                  f'在りかの repo がどこにも無ければ立てない (判定できないまま立てない) {rm}')
            # --denied is the guard's own refusal copied from this window's tool results, not an account of it
            trp = Path(td) / 'denied-transcript.jsonl'
            trp.write_text(json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content':
                           '🛑 guard: 本人の具体的な裁定が無い保護領域の変更です。適用しない。'}]}}, ensure_ascii=False) + '\n',
                           encoding='utf-8')
            os.environ['BOARD_ASKS_TRANSCRIPT'] = str(trp)
            try:
                rd1 = ask(None, [{'text': '守りが止めた (写し)', 'ground': 'rule', 'evidence': f'{rr}@HEAD:free',
                                  'denied': '本人の具体的な裁定が無い保護領域の変更です。'}], session='s1', path=led, validator=stub)
                rd2 = ask(None, [{'text': '守りが止めた (言い換え)', 'ground': 'rule', 'evidence': f'{rr}@HEAD:free',
                                  'denied': '検収係が委任の承認を出さなかった'}], session='s1', path=led, validator=stub)
            finally:
                os.environ.pop('BOARD_ASKS_TRANSCRIPT', None)
            check(rd1[0]['status'] == 'made' and '⚠️ --denied' not in rd1[0]['message'],
                  f'--denied が会話記録の守りの理由の写しなら立てる {rd1}')
            check(rd2[0]['status'] == 'refused' and 'candidate=' in rd2[0]['message'],
                  f'--denied が会話記録に無い言い換えなら立てず、 候補を在りかにするよう言う {rd2}')
            check('⚠️ --denied' in r5d[0]['message'], '会話記録が見つからなければ立てて、 照らせなかったと添える')
            # a question out of a reviewer's accept: only the classes the accept gave to the owner; decided ones are not asked
            bd = Path(td) / 'rboard'
            thr = bd / 'events' / 'proj' / '2026-01-01-x'
            thr.mkdir(parents=True)
            tsn = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            rq = '20260101T000000Z-claude-req001'
            (thr / f'20260101T000000Z--{rq}.json').write_text(json.dumps({'kind': 'request', 'event_id': rq, 'request_id': rq,
                'actor': {'agent': 'claude', 'session_id': 'cond-1111-aaaa'}}), encoding='utf-8')
            (thr / f'{tsn}--20260101T000100Z-claude-acc001.json').write_text(json.dumps({'kind': 'accept', 'request_id': rq,
                'event_id': '20260101T000100Z-claude-acc001', 'created_at': now_iso(),
                'details': 'review-verdict: ok\nreview-decided: 形を全部止めるか => 止める (理由)\nreview-owner: outbound: 送るか'}),
                encoding='utf-8')
            ra = ask(bd, [{'text': '検収係が決めた問い', 'ground': 'choice', 'keys': [f'request:{rq}']}], session='cond-1111-aaaa', path=led)
            check(ra[0]['status'] == 'refused' and 'review-decided' in ra[0]['message'],
                  f'受け取りが本人のものと分類しなかった理由の問いは立てない (検収係が決めた答えで進める) {ra}')
            rb = ask(bd, [{'text': '送るか', 'ground': 'outbound', 'keys': [f'request:{rq}#2']}], session='cond-1111-aaaa', path=led)
            check(rb[0]['status'] == 'made', f'受け取りが本人のものと分類した理由の問いは立てる {rb}')
            rb2 = ask(bd, [{'text': '同じ依頼の 3 つ目', 'ground': 'choice', 'keys': [f'request:{rq}#3']}], session='cond-1111-aaaa', path=led)
            check(rb2[0]['status'] == 'refused' and 'review-decided' in rb2[0]['message'],
                  f'key を分けた同じ依頼の問い (request:<id>#3) も、 その依頼の受け取りで判定する {rb2}')
            rc = ask(bd, [{'text': '鍵なしの問い', 'ground': 'choice', 'keys': ['free-form-key']}], session='cond-1111-aaaa', path=led)
            check(rc[0]['status'] == 'refused' and 'request:' in rc[0]['message'],
                  f'最近の受け取りのある依頼元の、 どこから出たかの key の無い問いは立てない {rc}')
            rc2 = ask(bd, [{'text': '受け取りと別の問い', 'ground': 'choice', 'keys': ['free-form-key2'],
                            'not_from_review': '本人の予定の問い'}], session='cond-1111-aaaa', path=led)
            rc3 = ask(bd, [{'text': 'TODO の問い', 'ground': 'choice', 'keys': ['todo:x:9']}], session='cond-1111-aaaa', path=led)
            check(rc2[0]['status'] == 'made' and rc3[0]['status'] == 'made',
                  '受け取りから出したのでない問いは --not-from-review か、 どこから出たかの key で立つ')
            rp = ask(bd, [{'text': '方針でよいか', 'ground': 'policy', 'keys': [f'session:cond-1111-aaaa']}], session='cond-1111-aaaa', path=led)
            check(rp[0]['status'] == 'made', f'実装の前の方針の確認は、 この門では止めない (規則 18 は本人の裁定のまま) {rp}')
            rn = ask(bd, [{'text': '別の窓の問い', 'ground': 'choice', 'keys': ['free-form-key3']}], session='other-2222-bbbb', path=led)
            check(rn[0]['status'] == 'made', f'受け取りの無い窓の問いは、 今までどおり立つ {rn}')
            blk = format_block(r)
            check('問い一 〔問 H1〕' in blk and 'おすすめ: はい' in blk and not blk.startswith('〔'), '問いの段の形 (中身が先、 印は後ろ)')
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
            check('(問わない) 問い一 〔問 H1〕' in format_block(rb), '答え済みの印と本人の語を出す')
            rb2 = ask(None, [{'text': '別の問い', 'ground': 'choice', 'keys': ['todo:x:1']}], session='s5', path=led)
            check(rb2[0]['status'] == 'refused' and '別の問いなら key' in rb2[0]['message'] and 'H1 です' in rb2[0]['message'],
                  '同じ key の別の文の問いには前の答えを答えとして返さず、 前の答えを見せて断る')
            rr = ask(None, [{'text': '問い一 (前提が変わった)', 'ground': 'choice', 'keys': ['todo:x:1'], 'reask': '期日が変わった'}],
                     session='s5', path=led)
            check(rr[0]['status'] == 'made', '理由つきなら問い直せる')
            # one policy check per piece of work; refused from a worker of the request (native id in actor.task too)
            board = Path(td) / 'board'
            (board / 'events' / 'proj' / 'th').mkdir(parents=True)
            rid = '20260101T000000Z-claude-abc123'
            (board / 'events' / 'proj' / 'th' / f'R1--{rid}.json').write_text(json.dumps(
                {'kind': 'request', 'event_id': rid, 'request_id': rid, 'assignee': {'agent': 'claude', 'session_id': 'role-x-worker'},
                 'actor': {'agent': 'claude', 'session_id': 'role-x-y', 'task': 'deadbeef (opus)'}}), encoding='utf-8')
            (board / 'events' / 'proj' / 'th' / 'C1--20260101T000100Z-claude-def456.json').write_text(json.dumps(
                {'kind': 'claim', 'event_id': '20260101T000100Z-claude-def456', 'request_id': rid,
                 'actor': {'agent': 'claude', 'session_id': 'role-x-worker', 'task': 'feedf00d (opus)'}}), encoding='utf-8')
            pk = [f'request:{rid}']
            check(ask(board, [{'text': '方針でよいか', 'ground': 'policy'}], session='deadbeef-1', path=led)[0]['status'] == 'refused',
                  '方針の確認には依頼か窓の key が要る')
            check(ask(None, [{'text': '方針でよいか', 'ground': 'policy', 'keys': ['request:nowhere']}], session='deadbeef-1',
                      path=led)[0]['status'] == 'refused', '依頼の event を確かめられなければ方針の確認は立てない')
            rw = ask(None, [{'text': '方針の中の選択をどうするか', 'ground': 'choice'}], session='worker-9', path=led)
            check(rw[0]['status'] == 'made' and '--ground policy' in rw[0]['message'], '方針の語を別の理由で問うと注意を添える')
            rwk = ask(board, [{'text': '方針の中の選択', 'ground': 'policy', 'keys': pk}], session='feedf00d-2222', path=led)
            check(rwk[0]['status'] == 'refused' and 'worker' in rwk[0]['message'], f'その依頼の worker (claim した session) は方針の確認を立てない {rwk}')
            rp = ask(board, [{'text': '方針でよいか', 'ground': 'policy', 'keys': pk}], session='deadbeef-1111', path=led)
            check(rp[0]['status'] == 'made', f'role id で出した依頼でも、 task の中の native id の session は立てられる {rp}')
            check(ask(board, [{'text': '方針でよいか', 'ground': 'policy', 'keys': pk}], session='deadbeef-1111', path=led)[0]['status'] == 'reused',
                  '同じ依頼の方針の確認は 1 回だけ (2 回目は同じ印)')
            check(ask(board, [{'text': '方針でよいか', 'ground': 'policy', 'keys': pk}], session='cafe1234-3333', path=led)[0]['status'] == 'reused',
                  '依頼元を引き継いだ session (作者でも worker でもない) も門を通る (同じ問いなので同じ印)')
            rs = ask(None, [{'text': '窓の作業の方針でよいか', 'ground': 'policy', 'keys': ['session:abcd0123-4444']}],
                     session='abcd0123-4444', path=led)
            check(rs[0]['status'] == 'made', f'掲示板の依頼の無い窓は自分の id の key で方針の確認を立てられる {rs}')
            check(ask(None, [{'text': '別の窓の方針', 'ground': 'policy', 'keys': ['session:0000ffff-5555']}], session='abcd0123-4444',
                      path=led)[0]['status'] == 'refused', '別の窓の id の key では立てない')
            # rewording keeps the label
            rr0 = ask(None, [{'text': '研究会に行くか', 'ground': 'choice', 'keys': ['ev:1']}], session='s11', path=led)
            rr1 = ask(None, [{'text': '研究会 (11/16、 配信あり) に行くか', 'ground': 'choice', 'keys': ['ev:1'], 'reword': '日付と配信を足した'}],
                      session='s11', path=led)
            check(rr1[0]['status'] == 'reworded' and rr1[0]['label'] == rr0[0]['label']
                  and state(load(led))[rr0[0]['label']]['text'].startswith('研究会 (11/16'), f'言い直しは同じ印のまま文を変える {rr1}')
            check('--reword' in ask(None, [{'text': '研究会に行くかどうか', 'ground': 'choice', 'keys': ['ev:1']}], session='s11',
                                    path=led)[0]['message'], '同じ key の別の文は、 言い直しの道を添えて断る')
            check('H1' in precompact_text(None, {'session_id': 's1'}, path=led), '圧縮の前の指示に印を出す')
            d = digest(None, 's1', path=led)
            check('✅ 問い一 (H1)' in d and 'H1 です' in d and '番号を振らずに' in d, f'開始・圧縮の後の出力 {d[:160]}')
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
            write_tr(('RCA を見せて', f'### 1. 報告\n\n問い八 〔問 {l8}〕\n\n問い九 〔問 {l9}〕'))
            w0, w1 = windows(str(tr))
            check(labels_in(w0) == [l8, l9] and w1 == '', '直前の窓の問いの印')
            check(hook_stop(None, {'session_id': 's9', 'transcript_path': str(tr)}, path=led) is None, '印つきの問いは差し戻さない')
            msg = hook_prompt(None, {'session_id': 's9', 'transcript_path': str(tr), 'prompt': '１はメールで伝えよう'}, path=led)
            check(msg and '🔒' in msg and '中身' in msg, f'見出しの番号と問いの段が並ぶ返事への「１は…」 は推定 {msg}')
            check(hook_pretool(None, {'session_id': 's9', 'tool_name': 'SendMessage', 'tool_input': {}}, path=led), '推定で止まる')
            write_tr(('RCA を見せて', f'### 1. 報告\n\n問い八 〔問 {l8}〕\n\n問い九 〔問 {l9}〕'),
                     ('１はメールで伝えよう', f'問い八 ({l8}) と読みました。よいですか'))
            check(hook_stop(None, {'session_id': 's9', 'transcript_path': str(tr)}, path=led) is None,
                  '候補を中身で名指し、 印を後ろに添えた確かめの文は差し戻さない')
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
            # paragraphs that do not ask the owner here (forms measured in send-backs; the sentences are synthetic)
            for i, txt in enumerate((
                    '- **済んだこと**: 試験が通りました。 worker が決めてほしいと言った細かい 4 つは、 検収で決まりました。',
                    '承認がまだです。 本人にはその worker の窓から確認が出るので、 そこで答えてください。',
                    '今から印で答えを頼むのをやめます。 本人は普段の言葉で答えてください。',
                    '決めてほしいことは、 それぞれの窓を開いて答えてください。',
                    '**本人に決めてほしいもの**\n\n- 面接と重なる予定をどうするか 〔問 %s〕' % l8)):
                write_tr(('x', txt))
                check(hook_stop(None, {'session_id': f'fp{i}', 'transcript_path': str(tr)}, path=led) is None,
                      f'本人にこの窓で問うていない段は差し戻さない: {txt[:30]}')
            # real questions are still sent back
            for i, txt in enumerate(('どちらの案で進めるか、 決めてください。',
                                     'A と B のどちらで送るか、 この窓で答えてください。',
                                     '**本人に決めてほしいこと**\n\n- 研究会に行くか\n- 予定をずらすか',
                                     'これで進めてよいですか')):
                write_tr(('x', txt))
                check(bool(hook_stop(None, {'session_id': f'tp{i}', 'transcript_path': str(tr)}, path=led)),
                      f'本当の問いは今までどおり差し戻す: {txt[:30]}')

            # the window = the text since the previous Stop; the same paragraph is never sent back twice
            def write_raw(*rows):
                lines = []
                for kind, text_ in rows:
                    if kind == 'stop':
                        lines.append({'type': 'system', 'subtype': 'stop_hook_summary'})
                    elif kind == 'user':
                        lines.append({'type': 'user', 'message': {'role': 'user', 'content': text_}})
                    elif kind == 'meta':
                        lines.append({'type': 'user', 'isMeta': True, 'message': {'role': 'user', 'content': text_}})
                    else:
                        lines.append({'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text_}]}})
                tr.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in lines) + '\n', encoding='utf-8')
            old_ask = 'このあと、 A と B のどちらにするか決めてください。'
            write_raw(('user', '状況は？'), ('reply', old_ask), ('stop', ''),
                      ('user', '<task-notification>done</task-notification>'), ('reply', '背景の作業が終わりました。 問いはありません。'))
            check(turn_window(str(tr))[0] == '背景の作業が終わりました。 問いはありません。', '今の窓 = 前の Stop の後の返事')
            check(hook_stop(None, {'session_id': 'tw1', 'transcript_path': str(tr)}, path=led) is None,
                  '前の Stop で判定を通った段を、 後の turn (背景の知らせで始まる) で読み直さない')
            write_raw(('user', '状況は？'), ('reply', old_ask))
            first = hook_stop(None, {'session_id': 'tw2', 'transcript_path': str(tr)}, path=led)
            write_raw(('user', '状況は？'), ('reply', old_ask), ('user', 'Another Claude session sent a message: x'),
                      ('reply', '別の窓の知らせを読みました。'))
            again = hook_stop(None, {'session_id': 'tw2', 'transcript_path': str(tr)}, path=led)
            check(bool(first) and again is None, f'窓の印の無い会話記録でも、 一度差し戻した段は次の turn で差し戻さない {again}')
            write_raw(('user', 'x'), ('reply', '返事'), ('meta', 'Stop hook feedback: 🧭 別の hook の差し戻し'), ('stop', ''),
                      ('reply', '追記です。 これで送ってよいですか'))
            check(bool(hook_stop(None, {'session_id': 'tw3', 'transcript_path': str(tr), 'stop_hook_active': True}, path=led)),
                  '別の hook の差し戻しの後の追記は判定する')
            write_raw(('user', 'x'), ('reply', '返事'), ('meta', 'Stop hook feedback: board-asks: 本人に答えを求める段に…'), ('stop', ''),
                      ('reply', '追記です。 これで送ってよいですか'))
            check(hook_stop(None, {'session_id': 'tw4', 'transcript_path': str(tr), 'stop_hook_active': True}, path=led) is None,
                  '自分が差し戻した続きは判定しない')
            write_raw(('user', 'x'), ('reply', '返事です。 これで送ってよいですか'))
            check(hook_stop(None, {'session_id': 'tw5', 'transcript_path': str(tr), 'stop_hook_active': True}, path=led) is None,
                  '続きの形が分からない (Stop の記録が無い) ときは判定しない')
            # labels used as numbers for the owner (a session that showed two asks with content words)
            r12 = ask(None, [{'text': '研究会の出欠を出すか', 'ground': 'choice'}, {'text': '面接と重なる家庭の予定をどうするか', 'ground': 'choice'}],
                      session='s12', path=led)
            la, lb_ = r12[0]['label'], r12[1]['label']
            stop12 = lambda: hook_stop(None, {'session_id': 's12', 'transcript_path': str(tr)}, path=led) or ''
            write_tr(('x', f'研究会の出欠を出すか 〔問 {la}〕\n\nどれか 1 つなら「{la} 送って」 と返してください。'))
            u = stop12()
            check('印・番号で答えさせる' in u, f'本人に印を打たせる文を差し戻す {u}')
            # the line the unlabeled-ask nudge tells the session to add must not be refused by the label-usage check below
            # (measured: the nudge's suggested line carried 「番号で答えてもらっても…」 and the next check refused it)
            write_tr(('x', '研究会の出欠を出すか、 決めてください。 おすすめ: 出す'))
            nudge = hook_stop(None, {'session_id': 's13', 'transcript_path': str(tr)}, path=led) or ''
            sug = re.search(r'短い追記に「([^」]*)」 の 1 行', nudge)
            check(bool(sug), f'印の無い問いの段に、 足す 1 行を勧める {nudge[:80]}')
            write_tr(('x', (sug.group(1) if sug else '') + f'\n\n研究会の出欠を出すか 〔問 {la}〕 おすすめ: 出す'))
            check('番号で答えさせる' not in stop12(), '勧めどおりの追記は、 印を番号のように使う検査に当たらない')
            write_tr(('x', '違う所があれば、 番号で教えてください。'))
            check('番号で答えさせる' in stop12(), '「番号で教えて」 を差し戻す')
            write_tr(('x', f'答えは「{la} 1 つ目」 か「{la} 2 つ目」 でどうぞ。'))
            check('番号で答えさせる' in stop12(), '序数の答え方を差し戻す')
            write_tr(('x', f'{la}・{lb_} は、 検収係が決めます。'))
            check('中身の無い印の並び' in stop12(), '中身の無い印の並びを差し戻す')
            write_tr(('x', f'- **{la}** 研究会の出欠を出すか\n'))
            check('行の頭に置いた印' in stop12(), '行の頭の印を差し戻す')
            for i, txt in enumerate((f'研究会の出欠 ({la}) と面接の予定 ({lb_}) は、 検収係が決めます。',
                                     f'{la}・{lb_} (研究会の出欠と面接の予定) は、 検収係が決めます。',
                                     '今から印で答えを頼むのをやめます。 印で答えてもらうのは、 もうしません。',
                                     '本人は「送って」 と返せば足ります。',
                                     f'本人は「{la} 1 つ目」 と返した。',
                                     '番号で答えが返ってくる件を調べる worker を起こしました。',
                                     '本人の「いまだに行番号で答えを返してくる」 の件です。',
                                     f'返事が中身を書かずに印だけで呼んだ (「{la}・{lb_} は…」)。',
                                     # lb_ (not la): a key already sent back above would hide a send-back here
                                     f'本人に印で答えるよう頼んでいた (「「{lb_} 送って」 と返して」、 「答えるときは番号でどうぞ」)。')):
                write_tr(('x', txt))
                check(stop12() == '', f'中身つきの印・やめる宣言・印の無い答え方・過去の報告は差し戻さない: {txt[:30]}')
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
