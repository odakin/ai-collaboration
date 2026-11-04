#!/usr/bin/env python3
"""board-post-reach-check.py — Stop hook: when a board post in this turn printed the next actor's direct address, was it
messaged? (CONTRACT.md#post-then-push: a post is a record, not a push; the rule said "send one line", the session forgot.)

What it reads: the session transcript named in the hook payload (`transcript_path`), only the current turn (after the
last real user message). A reach line is what `board.py` prints after a post whose next actor is alive on this machine:
`SendMessage の to = uds:…` (a Claude session, any config dir) or a `codex queue --thread …` command (a Codex thread).
Satisfied when, later in the same turn, a `SendMessage` / `send_message` tool call was made (for a Claude address) or a
Bash call containing `codex queue` (for a Codex thread). The sender's `to` is not matched against the printed address:
a peer in the same config dir may be messaged by name, and one message after the post is the whole obligation.

The other direction (kind `ack`): a cross-session message in this turn's user text that names a board request id hands
this session a turn (a revise, an answer, a request). Satisfied when the turn sends any message or posts on the board
(`board.py <posting command>` in a Bash call). Measured: a worker fixed a revise within two minutes and said so only in
its chat, which the requester cannot see; the requester saw an idle session for seven minutes and sent twice more.

The watch (kind `watch`, CONTRACT.md#codex-reach): a posting command or a watch that woke printed the line to watch the
request in the background (`background で見張る` / `続きを見張る (background)`), and the other side cannot message
this session: the same output named no live Claude counterpart (`SendMessage の to = uds:…`), and the board (this
machine's last fetch, no network) does not name the other participant as a live Claude session here = a Codex thread or
another machine. Satisfied when, later in the turn, a background Bash call (or a Monitor) runs a watch for that request,
when a watch for it is running on this machine (`ps`), or when the request is closed. Measured: a requester answered a
Codex worker's first question with `update`, ended the turn without watching again, and the worker's second question
waited about 85 minutes until the owner asked (a Codex thread has no SendMessage; the board was the only path).

The session's own turn (kind `turn`): the board (each board in the workspace as this machine last fetched it,
board.turns_for) says the next move on an open request is this session's — a submission or a question waiting for it
as the requester or as the reviewer role it acts under, a revision or a request addressed to it. Told once per post
(state `<config dir>/state/board-post-reach/turn-notified.json`); a turn that already named the request id in a tool
call (show, a post) counts as told. Catches what reached the board while the session was not watching, whenever it next
ends a turn.

Modes (environment BOARD_POST_REACH_STOP; the owner's wiring sets it): `observe` (default) records each miss as one JSON
line under `<config dir>/state/board-post-reach/observe.jsonl` and never blocks; `block` returns
`{"decision": "block", "reason": …}` once per turn (loop guard: `stop_hook_active`); `off` does nothing. Raise to
`block` only after the observe log shows no false positives (same two-step as the first-reply stamp check).
BOARD_WATCH_REARM_STOP and BOARD_OWN_TURN_STOP set the mode of the kinds `watch` and `turn` alone (default: the mode
above). The boards the `turn` kind reads: BOARD_POST_REACH_BOARDS (`:`-separated board directories), else
AGENT_BOARD_ROOT, else every board in the workspace (board_config.discover); a locked or unfetched board is skipped.
The rows are cached per fetched commit under the board's cache directory (a read costs about half a second, a cached
one a few git calls).

Fail-open: an unreadable payload or transcript, or any exception, prints nothing and exits 0. The wiring (a Stop entry
in the owner's settings calling this script) belongs to the owner's layer; this file is the shared kernel.

    board-post-reach-check.py            # hook payload on stdin
    board-post-reach-check.py --selftest
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REACH_CLAUDE = re.compile(r'SendMessage の to = (uds:\S+)')
# The line board.py prints after a post and after a watch wakes: watch this request in the background.
WATCH_LINE = re.compile(r'(?:background で見張る|続きを見張る \(background\))[^\n]*?\swatch\s+--root\s+(\S+)\s+--agent\s+(\S+)'
                        r'\s+--session\s+(\S+)\s+--request\s+(\S+)')
TURN_TTL_S = 600   # a cached row list is recomputed after this long (a lease can expire without a post)
REACH_CODEX = re.compile(r'\bcodex queue\b')
SEND_TOOLS = {'SendMessage', 'mcp__ccd_session_mgmt__send_message'}
# The other direction: a cross-session message that names a board request hands this session a turn (a revise, an
# answer, a request). Answered when the turn sends a message or posts on the board; the sender sees neither chat text.
INBOUND = re.compile(r'<cross-session-message\b')
INBOUND_FROM = re.compile(r'<cross-session-message[^>]*\bfrom="([^"]+)"')
REQUEST_ID = re.compile(r'\b\d{8}T\d{6}Z-(?:claude|codex|human|other)-[0-9a-f]{6}\b')
BOARD_POST = re.compile(r'\bboard\.py\s+(?:request|claim|submit|accept|revise|release|blocker|update|handover|abandoned|note|touch|untouch|retry)\b')


def load_entries(path):
    out = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try: e = json.loads(line)
            except Exception: continue
            if isinstance(e, dict): out.append(e)
    return out


def blocks(e):
    c = (e.get('message') or {}).get('content')
    return c if isinstance(c, list) else []


def is_real_user(e):
    if e.get('type') != 'user': return False
    c = (e.get('message') or {}).get('content')
    if isinstance(c, str): return True
    return not any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c or [])


def current_turn(entries):
    start = 0
    for i, e in enumerate(entries):
        if is_real_user(e): start = i
    return entries[start:]


def text_of(block):
    c = block.get('content')
    if isinstance(c, str): return c
    if isinstance(c, list): return '\n'.join(str(x.get('text', '')) for x in c if isinstance(x, dict))
    return ''


def steps(turn):
    """The turn as a flat list of ('result', text) and ('call', tool name, input) in order."""
    out = []
    for e in turn:
        for b in blocks(e):
            if not isinstance(b, dict): continue
            if e.get('type') == 'user' and b.get('type') == 'tool_result': out.append(('result', text_of(b), None))
            elif e.get('type') == 'assistant' and b.get('type') == 'tool_use': out.append(('call', b.get('name') or '', b.get('input') or {}))
    return out


def handovers(turn):
    """Senders of cross-session messages in this turn's user text that name a board request: ['uds:…', …]."""
    out = []
    for e in turn:
        if not is_real_user(e): continue
        c = (e.get('message') or {}).get('content')
        text = c if isinstance(c, str) else '\n'.join(str(b.get('text', '')) for b in c if isinstance(b, dict)) if isinstance(c, list) else ''
        if INBOUND.search(text) and REQUEST_ID.search(text):
            m = INBOUND_FROM.search(text); out.append(m.group(1) if m else '(sender unknown)')
    return list(dict.fromkeys(out))


def misses(turn):
    """Reach lines of this turn that no later direct message or codex queue answered, and board hand-over messages
    this turn neither answered nor acted on with a post: [(kind, address)] with kind claude / codex / ack."""
    flat = steps(turn); out = []
    senders = handovers(turn)
    if senders:
        replied = any(s[0] == 'call' and s[1] in SEND_TOOLS for s in flat)
        posted = any(s[0] == 'call' and s[1] == 'Bash' and BOARD_POST.search(str((s[2] or {}).get('command', ''))) for s in flat)
        if not replied and not posted: out.extend(('ack', a) for a in senders)
    for i, step in enumerate(flat):
        if step[0] != 'result': continue
        later = flat[i + 1:]
        for addr in REACH_CLAUDE.findall(step[1]):
            if not any(s[0] == 'call' and s[1] in SEND_TOOLS for s in later): out.append(('claude', addr))
        if REACH_CODEX.search(step[1]) and 'inbox --agent codex' in step[1]:
            if not any(s[0] == 'call' and s[1] == 'Bash' and REACH_CODEX.search(str((s[2] or {}).get('command', ''))) for s in later):
                out.append(('codex', 'codex queue'))
    seen, uniq = set(), []
    for m in out:
        if m not in seen: seen.add(m); uniq.append(m)
    return uniq


# ---------------------------------------------------------------- the board (watch / turn kinds)
# Providers are module globals so the selftest can stand in for the board, `ps` and the live registry.

def _engine():
    sys.path.insert(0, str(HERE))
    import board, board_config as bc, board_transport as bt
    return board, bc, bt


def board_events(root):
    """Events of one board as this machine last fetched it (no network); [] when unfetched or locked."""
    board, bc, bt = _engine()
    if bc.is_locked(root): return []
    repo = bt.Repo(root); sha = repo.remote_sha()
    return board.read(repo.materialized(sha)) if sha else []


def board_roots():
    env = os.environ.get('BOARD_POST_REACH_BOARDS') or os.environ.get('AGENT_BOARD_ROOT')
    if env: return [Path(os.path.expanduser(p)) for p in env.split(':') if p]
    _, bc, _ = _engine()
    return [b['root'] for b in bc.discover() if b.get('config') and not b.get('locked')]


def board_turns(root):
    """board.turn_rows of one board, cached per fetched commit (TURN_TTL_S) in the board's cache directory."""
    board, bc, bt = _engine()
    if bc.is_locked(root): return []
    repo = bt.Repo(root); sha = repo.remote_sha()
    if not sha: return []
    cache = repo.cache_dir() / f'turns-{sha}.json'
    try:
        got = json.loads(cache.read_text())
        if time.time() - got['at'] < TURN_TTL_S: return got['rows']
    except (OSError, ValueError, KeyError, TypeError): pass
    rows = board.turn_rows(board.read(repo.materialized(sha)))
    try:
        tmp = cache.with_name(cache.name + f'.{os.getpid()}.tmp'); tmp.write_text(json.dumps({'at': time.time(), 'rows': rows}))
        os.replace(tmp, cache)
        for old in sorted(repo.cache_dir().glob('turns-*.json'), key=lambda p: p.stat().st_mtime)[:-4]:
            if old != cache: old.unlink(missing_ok=True)
    except OSError: pass
    return rows


WATCH_PROC = re.compile(r'^\S*[Pp]ython[0-9.]*\s+(?:-\S+\s+)*\S*board\.py\s+watch\s')


def running_watches():
    """The command lines of the board watches running on this machine: a python process whose script is board.py and
    whose first argument is `watch` (measured: a shell whose command text quoted a watch line was counted as one; the
    macOS framework python shows as `…/Python.app/Contents/MacOS/Python`)."""
    p = subprocess.run(['ps', '-axww', '-o', 'command='], capture_output=True, text=True, timeout=10)
    return [l for l in p.stdout.splitlines() if WATCH_PROC.search(l)]


def watching(rid, running):
    return any(re.search(r'--request\s+' + re.escape(rid) + r'(?:\s|$)', l) for l in running)


def counterpart_live(root, agent, session, rid, events):
    """Whether the other participant of request `rid` (seen from agent/session) is a live Claude session on this machine
    (it can message this session) — None when the request is closed or unknown."""
    board, _, _ = _engine()
    same = [e for e in events if e.get('request_id') == rid or e.get('event_id') == rid]
    if not same: return None
    key = (same[0]['project']['key'], same[0]['thread_id'])
    thread = [e for e in events if (e['project']['key'], e['thread_id']) == key]
    w = board.reduce_workflow(thread, board.view.now_utc())
    if not w.get('request') or w.get('status') in ('accepted', 'abandoned'): return None
    other = board.other_party(w, (agent, session)) or {}
    other = dict(other, agent=board.role_agent(other, thread))
    return bool(board.live_address(other.get('agent'), other.get('session_id'), thread))


EVENTS = board_events
WATCHES = running_watches
LIVE = counterpart_live


def watch_misses(turn):
    """Requests whose watch line this turn printed while the other side cannot message this session, and no watch for
    them started later in the turn or runs on this machine: [('watch', request id)]."""
    flat = steps(turn); want = {}
    for i, step in enumerate(flat):
        if step[0] != 'result': continue
        for root, agent, session, rid in WATCH_LINE.findall(step[1]):
            if REACH_CLAUDE.search(step[1]): continue          # a live Claude counterpart: it messages this session
            later = flat[i + 1:]
            started = any(s[0] == 'call' and ((s[1] == 'Bash' and (s[2] or {}).get('run_in_background') and
                                               ' watch ' in f" {(s[2] or {}).get('command', '')} " and rid in str((s[2] or {}).get('command', '')))
                                              or (s[1] == 'Monitor' and rid in json.dumps(s[2] or {})))
                          for s in later)
            if not started: want[rid] = (root, agent, session)
            else: want.pop(rid, None)
    if not want: return []
    try: running = WATCHES()
    except Exception: running = []
    out, events_of = [], {}
    for rid, (root, agent, session) in want.items():
        if watching(rid, running): continue
        try:
            if root not in events_of: events_of[root] = EVENTS(Path(root))
            live = LIVE(Path(root), agent, session, rid, events_of[root])
        except Exception:
            live = False
        if live is None or live: continue                       # closed / the other side can message this session
        out.append(('watch', rid))
    return out


def _notified_path():
    return state_dir() / 'turn-notified.json'


def turn_misses(turn, session):
    """Open requests whose next move is this session's, not told before and not named in this turn's tool calls:
    [('turn', one line)]. Marks them told (once per post)."""
    if not session: return []
    board, _, _ = _engine()
    rows = []
    for root in board_roots():
        try: rows += [dict(r, board=str(root)) for r in TURNS(root) if board._native_match(r.get('native'), session)]
        except Exception: continue
    if not rows: return []
    calls = ' '.join(json.dumps(s[2] or {}, ensure_ascii=False) for s in steps(turn) if s[0] == 'call')
    try: told = json.loads(_notified_path().read_text())
    except (OSError, ValueError): told = {}
    mine = set(told.get(session, []))
    out, now_told = [], []
    for r in rows:
        key = f"{r['board']}:{r['event_id']}"
        if key in mine: continue
        now_told.append(key)
        if r['request_id'] in calls: continue                   # the turn already read or answered it
        out.append(('turn', f"{r['project']}/{r['thread_id']} [{r['label']}] {r['kind']} by {r['by']} "
                            f"{str(r.get('created_at') or '')[:16]}Z request {r['request_id']} (--root {r['board']})"))
    if now_told:
        told[session] = (list(mine) + now_told)[-200:]
        if len(told) > 300: told = dict(list(told.items())[-300:])
        try:
            tmp = _notified_path().with_suffix('.tmp'); tmp.write_text(json.dumps(told)); os.replace(tmp, _notified_path())
        except OSError: pass
    return out


TURNS = board_turns


def state_dir():
    base = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
    d = base / 'state' / 'board-post-reach'; d.mkdir(parents=True, exist_ok=True); return d


def modes_from_env():
    base = os.environ.get('BOARD_POST_REACH_STOP', 'observe').strip().lower() or 'observe'
    return {'claude': base, 'codex': base, 'ack': base,
            'watch': os.environ.get('BOARD_WATCH_REARM_STOP', '').strip().lower() or base,
            'turn': os.environ.get('BOARD_OWN_TURN_STOP', '').strip().lower() or base}


def block_reason(found):
    acks = [a for k, a in found if k == 'ack']; posts = [f'{k}: {a}' for k, a in found if k in ('claude', 'codex')]
    watches = [a for k, a in found if k == 'watch']; turns = [a for k, a in found if k == 'turn']
    parts = []
    if posts:
        parts.append('📮 掲示板に投稿し、 次に動く session がこの機械で生きている (' + '; '.join(posts) + ') のに、 この turn に SendMessage '
                     '(Codex なら codex queue) が無い。 投稿は push でない (CONTRACT#post-then-push): 今 1 行送る (thread id + 書いた中身)')
    if acks:
        parts.append('📨 掲示板の番を渡す message を受けた (' + '; '.join(acks) + ') のに、 この turn に返事 (SendMessage) も掲示板への投稿も無い。 '
                     '相手に見えるのは投稿と message だけ (chat は見えない): 「受け取った・何をする・いつ submit する」 の 1 行を SendMessage で返す')
    if watches:
        parts.append('👁 投稿か見張りの出力が「background で見張る」 を求めた依頼 (' + '; '.join(watches) + ') に、 見張りが動いていない '
                     '(この turn の run_in_background の watch も、 この機械で動いている watch も無い)。 相手は Codex か別の機械 = '
                     '相手の次の書き込みはこの session に届かない (CONTRACT#codex-reach): 出力のその 1 行を Bash の run_in_background で今打つ')
    if turns:
        parts.append('📮 掲示板でこの session の番の依頼がある: ' + ' / '.join(turns) + '。 show --request <id> --sync で読み、 '
                     '答える・検収する・引き受ける (中身に本人の判断が要るなら本人に 1 行)。 この知らせは 1 件 1 回')
    return {'decision': 'block', 'reason': ' / '.join(parts) + '。 送らない理由 (相手が自分 / 既に別の経路で伝えた / 知らせだけで番が動かない) なら短い追記に 1 行。 返事の本文は出し直さない'}


def decide(payload, mode, modes=None):
    modes = modes or {k: mode for k in ('claude', 'codex', 'ack', 'watch', 'turn')}
    if all(m == 'off' for m in modes.values()) or payload.get('stop_hook_active'): return None
    path = payload.get('transcript_path')
    if not path or not os.path.isfile(path): return None
    turn = current_turn(load_entries(path))
    found = [m for m in misses(turn) if modes.get(m[0]) != 'off']
    if modes.get('watch') != 'off':
        try: found += watch_misses(turn)
        except Exception: pass
    if modes.get('turn') != 'off':
        try: found += turn_misses(turn, str(payload.get('session_id') or ''))
        except Exception: pass
    if not found: return None
    seen = [m for m in found if modes.get(m[0]) == 'observe']
    if seen:
        try:
            with (state_dir() / 'observe.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'session': (payload.get('session_id') or '')[:8],
                                    'misses': [f'{k}: {a}' for k, a in seen], 'transcript': str(path)}, ensure_ascii=False) + '\n')
        except OSError: pass
    blocking = [m for m in found if modes.get(m[0]) == 'block']
    return block_reason(blocking) if blocking else None


def main():
    if '--selftest' in sys.argv: return _selftest()
    try:
        payload = json.loads(sys.stdin.read() or '{}')
        if not isinstance(payload, dict): return 0
        modes = modes_from_env()
        out = decide(payload, modes['claude'], modes)
        if out: print(json.dumps(out, ensure_ascii=False))
    except Exception:
        return 0
    return 0


def _selftest():
    import tempfile
    reach = 'event_id=x\nposted x\n→ 次に動く claude/56706b91 はこの機械で生きている: SendMessage の to = uds:/tmp/cc-socks/1.sock で thread id と書いた中身を 1 行\n'
    codex = 'posted y\n→ 次に動く codex/01a00000 に知らせる (生きている): codex queue --thread 01a0 --message \'掲示板 p/t: 書き込みあり。 inbox --agent codex --session 01a0 --sync で読む\'\n'
    inbound = ('Another Claude session sent a message:\n<cross-session-message from="uds:/tmp/cc-socks/7.sock" from-session="local_x" from-name="n" from-mode="prompting">\n'
               '依頼 20260101T000000Z-claude-abcdef に revise を出しました。 直したら submit してください。\n</cross-session-message>')
    def u(text): return {'type': 'user', 'message': {'content': text}}
    def res(text): return {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': text}]}}
    def call(name, inp=None): return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': name, 'input': inp or {}}]}}
    def text(t): return {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': t}]}}
    cases = {
        'post then no message → miss': ([u('go'), call('Bash'), res(reach), text('done')], [('claude', 'uds:/tmp/cc-socks/1.sock')]),
        'post then SendMessage → ok': ([u('go'), call('Bash'), res(reach), call('SendMessage', {'to': 'x', 'message': 'm'}), text('done')], []),
        'post then desktop send_message → ok': ([u('go'), call('Bash'), res(reach), call('mcp__ccd_session_mgmt__send_message', {'session_id': 'x', 'message': 'm'})], []),
        'message before the post does not count': ([u('go'), call('SendMessage', {'to': 'x', 'message': 'm'}), call('Bash'), res(reach)], [('claude', 'uds:/tmp/cc-socks/1.sock')]),
        'reach in an earlier turn only → ok': ([u('go'), call('Bash'), res(reach), u('next'), call('Bash'), res('posted z\n')], []),
        'codex thread then codex queue via Bash → ok': ([u('go'), call('Bash'), res(codex), call('Bash', {'command': "codex queue --thread 01a0 --message 'x'"})], []),
        'codex thread, no queue → miss': ([u('go'), call('Bash'), res(codex)], [('codex', 'codex queue')]),
        'no post → ok': ([u('go'), call('Bash'), res('ok\n'), text('done')], []),
        'two posts, one message → ok': ([u('go'), call('Bash'), res(reach), call('Bash'), res(reach), call('SendMessage', {'to': 'x'})], []),
        # the other direction: a hand-over message answered by a reply, by a board post, or not at all
        'hand-over message, no reply, no post → ack miss': ([u(inbound), call('Bash', {'command': 'git status'}), text('直します')], [('ack', 'uds:/tmp/cc-socks/7.sock')]),
        'hand-over message + SendMessage → ok': ([u(inbound), call('SendMessage', {'to': 'x', 'message': '受け取った'}), text('ok')], []),
        'hand-over message + board post → ok': ([u(inbound), call('Bash', {'command': 'python3 scripts/board.py submit --root b --request x'}), text('ok')], []),
        'cross-session chat without a request id → ok': ([u('<cross-session-message from="uds:/tmp/cc-socks/7.sock">お疲れさま</cross-session-message>'), text('ok')], []),
        'request id outside a cross-session message → ok': ([u('request 20260101T000000Z-claude-abcdef を見て'), text('ok')], []),
        'hand-over message in an earlier turn only → ok': ([u(inbound), call('SendMessage', {'to': 'x'}), u('next'), call('Bash'), text('ok')], []),
    }
    # the board, ps and the live registry stand-ins (the watch and turn kinds below set their own)
    os.environ['BOARD_POST_REACH_BOARDS'] = '/fixture-board'
    globals().update(TURNS=lambda root: [], WATCHES=lambda: [], LIVE=lambda *a: False, EVENTS=lambda root: [])
    with tempfile.TemporaryDirectory() as td:
        os.environ['CLAUDE_CONFIG_DIR'] = td
        for name, (entries, want) in cases.items():
            p = Path(td) / 'tr.jsonl'
            p.write_text('\n'.join(json.dumps(e) for e in entries) + '\n')
            got = misses(current_turn(load_entries(p)))
            assert got == want, (name, got, want)
            out = decide({'transcript_path': str(p), 'session_id': 'abcdef12'}, 'block')
            assert bool(out) == bool(want), (name, out)
            assert decide({'transcript_path': str(p), 'stop_hook_active': True}, 'block') is None, name
            assert decide({'transcript_path': str(p)}, 'off') is None, name
            assert decide({'transcript_path': str(p), 'session_id': 'abcdef12'}, 'observe') is None, name
        log = (Path(td) / 'state' / 'board-post-reach' / 'observe.jsonl').read_text().splitlines()
        assert len(log) == sum(1 for _, (e, w) in cases.items() if w), len(log)
        assert all('uds:' in l or 'codex' in l for l in log)
        assert sum('"ack: ' in l for l in log) == 1, log
        blocked = decide({'transcript_path': str(p), 'session_id': 'abcdef12'}, 'block')   # p = the last case written (ok) → None
        assert blocked is None
        p.write_text('\n'.join(json.dumps(e) for e in cases['hand-over message, no reply, no post → ack miss'][0]) + '\n')
        r = decide({'transcript_path': str(p), 'session_id': 'abcdef12'}, 'block')['reason']
        assert '📨' in r and 'uds:/tmp/cc-socks/7.sock' in r and '📮' not in r, r
        assert decide({'transcript_path': str(Path(td) / 'missing.jsonl')}, 'block') is None   # fail-open

        # ---- watch: the output asked for a background watch and the other side cannot message this session
        rid = '20990101T010203Z-claude-a1b2c3'
        asked = ('posted u\n📋 この依頼の今: [作業中] 番 = codex/0a0a0a0a / 開いた blocker なし\n'
                 f'→ 相手の書き込みで起こされるように、 background で見張る (Claude = Bash の run_in_background): python3 /e/board.py watch --root /b --agent claude --session role-p-owner-review --request {rid}\n'
                 "→ 次に動く codex/0a0a0a0a に知らせる (生きている): codex queue --thread 0a0a --message 'x inbox --agent codex --session r --sync'\n")
        woke = (f'📮 p/t blocker 2099-01-01T01:15 from codex/role-p-w: 相談\n→ 続きを見張る (background): python3 /e/board.py watch --root /b'
                f' --agent claude --session role-p-owner-review --request {rid} --since E2\n')
        bg = call('Bash', {'command': f'python3 /e/board.py watch --root /b --agent claude --session role-p-owner-review --request {rid}', 'run_in_background': True})
        fg = call('Bash', {'command': f'python3 /e/board.py watch --root /b --agent claude --session role-p-owner-review --request {rid}'})
        queued = call('Bash', {'command': "codex queue --thread 0a0a --message 'x'"})
        wcases = {
            'answer to a Codex question, no watch → miss': ([u('go'), call('Bash'), res(asked), queued, text('答えた')], [('watch', rid)], {}),
            'answer + background watch → ok': ([u('go'), call('Bash'), res(asked), queued, bg, text('見張る')], [], {}),
            'answer + foreground watch → miss': ([u('go'), call('Bash'), res(asked), queued, fg], [('watch', rid)], {}),
            'a live Claude counterpart named in the output → ok': ([u('go'), call('Bash'), res(asked.replace('codex queue', 'x') + reach), call('SendMessage', {'to': 'x'})], [], {}),
            'a watch already running here → ok': ([u('go'), call('Bash'), res(asked), queued], [], {'WATCHES': lambda: [f'python3 /e/board.py watch --request {rid}']}),
            'the board names a live Claude counterpart → ok': ([u('go'), call('Bash'), res(asked), queued], [], {'LIVE': lambda *a: True}),
            'the request is closed → ok': ([u('go'), call('Bash'), res(asked), queued], [], {'LIVE': lambda *a: None}),
            'a watch woke and was read, not re-armed → miss': ([u('<task-notification>done</task-notification>'), call('Read'), res(woke), text('読んだ')], [('watch', rid)], {}),
            'a watch woke and was re-armed → ok': ([u('<task-notification>done</task-notification>'), call('Read'), res(woke), bg], [], {}),
        }
        assert WATCH_PROC.search(f'/usr/bin/python3 /e/board.py watch --root /b --request {rid}') and \
            WATCH_PROC.search(f'python3 -u board.py watch --request {rid}') and \
            WATCH_PROC.search(f'/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python /e/board.py watch --request {rid}')
        assert not WATCH_PROC.search(f"/bin/zsh -c python3 - <<'EOF' … board.py watch --request {rid}")   # a shell quoting the line
        assert watching(rid, [f'python3 /e/board.py watch --request {rid} --since E']) and not watching(rid, [f'python3 b.py watch --request {rid}x'])
        for name, (entries, want, stand) in wcases.items():
            saved = {k: globals()[k] for k in stand}; globals().update(stand)
            try:
                p = Path(td) / 'w.jsonl'; p.write_text('\n'.join(json.dumps(e) for e in entries) + '\n')
                got = watch_misses(current_turn(load_entries(p)))
                assert got == want, (name, got, want)
                out = decide({'transcript_path': str(p), 'session_id': 'abcdef12'}, 'block')
                assert bool(out) == bool(want) and (not want or '👁' in out['reason']), (name, out)
            finally:
                globals().update(saved)

        # ---- turn: the board says this session's move is due; told once per post
        me = 'abcdef12-0000-4000-8000-000000000001'
        row = {'request_id': rid, 'project': 'p', 'thread_id': 't', 'status': 'blocked', 'label': '相談待ち', 'native': 'abcdef12',
               'event_id': '20990101T011500Z-codex-d4e5f6', 'kind': 'blocker', 'created_at': '2099-01-01T01:15:00Z', 'by': 'codex', 'title': 'x'}
        other = dict(row, native='99999999', event_id='E-other', request_id='20990101T000000Z-claude-000001')
        globals()['TURNS'] = lambda root: [row, other]
        p = Path(td) / 't.jsonl'; p.write_text('\n'.join(json.dumps(e) for e in [u('物理の話'), text('答え')]) + '\n')
        out = decide({'transcript_path': str(p), 'session_id': me}, 'block')
        assert out and '📮 掲示板でこの session の番' in out['reason'] and rid in out['reason'] and 'E-other' not in out['reason'] \
            and '20990101T000000Z-claude-000001' not in out['reason'], out
        assert decide({'transcript_path': str(p), 'session_id': me}, 'block') is None   # told once per post
        row2 = dict(row, event_id='20990101T020000Z-codex-aaaaaa', kind='submit', status='submitted', label='確認待ち')
        globals()['TURNS'] = lambda root: [row2]
        p.write_text('\n'.join(json.dumps(e) for e in [u('go'), call('Bash', {'command': f'board.py show --request {rid} --sync'}), text('読んだ')]) + '\n')
        assert decide({'transcript_path': str(p), 'session_id': me}, 'block') is None   # named in this turn = told, and marked
        p.write_text('\n'.join(json.dumps(e) for e in [u('next'), text('x')]) + '\n')
        assert decide({'transcript_path': str(p), 'session_id': me}, 'block') is None   # not again
        row3 = dict(row, event_id='20990101T030000Z-codex-bbbbbb')
        globals()['TURNS'] = lambda root: [row3]
        modes = {'claude': 'block', 'codex': 'block', 'ack': 'block', 'watch': 'block', 'turn': 'observe'}
        assert decide({'transcript_path': str(p), 'session_id': me}, 'block', modes) is None   # observe: recorded, not blocked
        log = (Path(td) / 'state' / 'board-post-reach' / 'observe.jsonl').read_text()
        assert '"turn: p/t [相談待ち] blocker by codex' in log, log[-300:]
        assert decide({'transcript_path': str(p), 'session_id': me}, 'block', dict(modes, turn='off')) is None
        globals()['TURNS'] = lambda root: (_ for _ in ()).throw(OSError('locked'))
        assert decide({'transcript_path': str(p), 'session_id': me}, 'block') is None   # a board that cannot be read = quiet
    print('board-post-reach-check selftest: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
