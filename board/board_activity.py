#!/usr/bin/env python3
"""board_activity.py — what the repository holding a collaborator board shows about a request outside the board: commits after it, and commits that name it.

A collaborator board (`<project>/board/`) lives inside the project repository. A request on it can be read and acted on
with a commit alone (no claim, no note), and the board then still says 「引受待ち」 while the work moved (measured: a
commit named the thread and carried out part of the request; the board stayed at requested and the requester's
dashboard said the counterpart's session had not been opened). Two signals, read from the local checkout's
history (no network, nothing written):

- `evidence(...)` — for the requester's side: the counterpart's commits after the request (how many, the last one) and
  the ones whose message names the thread id or the request id. Counterpart = the authors the members table maps to the
  waiting role; without such an entry, every author but this checkout's `user.email` and bots.
- `unposted(...)` — for the counterpart's side: this checkout's own commits that name a request still waiting on one of
  its own roles. Needs the members table (without it nothing is reported, so a requester's own commit naming its
  request is never mistaken for the counterpart's).

Members table = `<board>/members.json` (optional, written by the project's members):

    {"members": {"<git user.email>": ["role-<project>-<function>", ...]}}

It is a separate file, not a board.json field: board.json refuses a field an older engine does not know, which would
stop every board command on a machine whose engine has not been updated yet (board_config.py docstring).

Usage: board_activity.py --selftest
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import board_config as bc

MEMBERS = 'members.json'
SINCE_DAYS = 120          # history read per board: requests older than this are past the dashboard's interest
NAMED_MAX = 3             # named commits carried per thread (the dashboard shows the first)
BOT_RE = re.compile(r'\[bot\]@|^noreply@github\.com$')
SEP_FIELD, SEP_REC = '\x1f', '\x1e'


def load_members(root) -> dict[str, list[str]]:
    """{lowercased git user.email: [role id, ...]} from `<board>/members.json`; {} when absent or unreadable."""
    try:
        data = json.loads((Path(root) / MEMBERS).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    table = data.get('members') if isinstance(data, dict) else None
    if not isinstance(table, dict):
        return {}
    return {str(k).strip().lower(): [str(r) for r in v] for k, v in table.items() if isinstance(v, list)}


def local_email(root) -> str:
    return bc.git(root, 'config', 'user.email').lower()


def _when(text):
    try:
        return dt.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def commits(root, *, days=SINCE_DAYS) -> list[dict] | None:
    """Commits of the repository holding the board, newest first, leaving out commits that touch only the board's own
    directory (posts are events already). None when the board is a whole repository (its commits are its posts) or the
    history cannot be read. Reads HEAD and its upstream (a fetched remote commit counts before it is merged)."""
    top, sub = bc.toplevel(root), bc.subdir(root)
    if top is None or not sub:
        return None
    refs = ['HEAD'] + (['@{u}'] if bc.git(top, 'rev-parse', '--verify', '-q', '@{u}') else [])
    try:
        p = subprocess.run(['git', '-C', str(top), 'log', *refs, f'--since={days} days ago',
                            f'--format=%H{SEP_FIELD}%ae{SEP_FIELD}%cI{SEP_FIELD}%B{SEP_REC}', '--', '.', f':(exclude){sub}'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    rows = []
    for rec in p.stdout.split(SEP_REC):
        parts = rec.lstrip('\n').split(SEP_FIELD)
        if len(parts) < 4 or not parts[0]:
            continue
        at = _when(parts[2])
        if at is not None:
            rows.append({'commit': parts[0], 'email': parts[1].strip().lower(), 'at': at, 'message': parts[3]})
    return rows


def _request(workflow):
    w = workflow or {}
    since = _when(((w.get('request') or {}).get('created_at')))
    role = str((w.get('waiting_on') or {}).get('session_id') or '')
    return since, role


def _names(row, tokens) -> bool:
    return any(t and t in row['message'] for t in tokens)


def _brief(row) -> dict:
    return {'commit': row['commit'][:7], 'at': row['at'].isoformat(timespec='minutes')}


def evidence(thread_id, workflow, rows, members, mine) -> dict | None:
    """The counterpart's commits after the request (requester's view). None when there is no request or no history."""
    since, role = _request(workflow)
    if rows is None or since is None:
        return None
    who = {email for email, roles in members.items() if role and role in roles}
    by = 'members' if who else 'not-local'

    def theirs(row):
        if who:
            return row['email'] in who
        return row['email'] != mine and not BOT_RE.search(row['email'])

    after = [r for r in rows if r['at'] > since and theirs(r)]
    tokens = (thread_id, (workflow or {}).get('request_id'))
    named = [_brief(r) for r in sorted(after, key=lambda r: r['at']) if _names(r, tokens)][:NAMED_MAX]
    last = max((r['at'] for r in after), default=None)
    return {'since': since.isoformat(timespec='minutes'), 'by': by, 'commits': len(after),
            'last_at': last.isoformat(timespec='minutes') if last else None, 'named': named}


def unposted(thread_id, workflow, rows, members, mine) -> list[dict]:
    """This checkout's commits naming a request that still waits, unclaimed, on one of this checkout's roles."""
    w = workflow or {}
    since, role = _request(w)
    if rows is None or since is None or w.get('status') != 'requested' or not mine or role not in members.get(mine, []):
        return []
    tokens = (thread_id, w.get('request_id'))
    return [_brief(r) for r in sorted(rows, key=lambda r: r['at'])
            if r['email'] == mine and r['at'] > since and _names(r, tokens)][:NAMED_MAX]


def board_activity(root) -> tuple | None:
    """(rows, members, mine) for a board inside a project repository, else None (whole-repository boards)."""
    rows = commits(root)
    if rows is None:
        return None
    return rows, load_members(root), local_email(root)


# ---------------------------------------------------------------- selftest

def _selftest() -> int:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / 'proj'
        board = repo / 'board'
        (board / 'events').mkdir(parents=True)
        def git(*args, env=None):
            subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, env=env)
        git('init', '-q', '-b', 'main')
        git('config', 'user.email', 'Writer@example.org')
        git('config', 'user.name', 'writer')

        def commit(path, msg, email, when):
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(msg + '\n', encoding='utf-8')
            git('add', path)
            env = dict(os.environ, GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_EMAIL=email, GIT_AUTHOR_NAME='x',
                       GIT_COMMITTER_NAME='x', GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when,
                       GIT_CONFIG_NOSYSTEM='1', HOME=td)
            git('commit', '-q', '-m', msg, env=env)

        commit('notes/a.md', 'before the request', 'partner@example.org', '2030-01-01T00:00:00+00:00')
        commit('notes/b.md', 'partner: does part 3 of thread 2030-01-02-demo-ask', 'partner@example.org', '2030-01-03T00:00:00+00:00')
        commit('notes/c.md', 'writer: mentions 2030-01-02-demo-ask in its own notes', 'writer@example.org', '2030-01-03T01:00:00+00:00')
        commit('notes/d.md', 'bump a dependency (2030-01-02-demo-ask)', '1+dependabot[bot]@users.noreply.github.com', '2030-01-03T02:00:00+00:00')
        commit('board/events/x.json', 'board post naming 2030-01-02-demo-ask', 'partner@example.org', '2030-01-03T03:00:00+00:00')
        commit('notes/e.md', 'partner: unrelated work', 'partner@example.org', '2030-01-04T00:00:00+00:00')
        commit('notes/f.md', 'writer: acts on request r-1 without posting', 'writer@example.org', '2030-01-04T01:00:00+00:00')

        rows = commits(board, days=100000)
        assert rows is not None and all(not r['message'].startswith('board post') for r in rows), rows
        assert commits(repo, days=100000) is None, 'a whole-repository board has no outside history'
        w = {'status': 'requested', 'request_id': 'r-1', 'waiting_on': {'agent': 'claude', 'session_id': 'role-proj-partner'},
             'request': {'created_at': '2030-01-02T00:00:00Z'}}
        mine = local_email(board)
        assert mine == 'writer@example.org', mine

        # requester's view without a members table: every author but this checkout's and bots
        ev = evidence('2030-01-02-demo-ask', w, rows, {}, mine)
        assert ev['by'] == 'not-local' and ev['commits'] == 2, ev                       # b and e (not a: before; c, f: mine; d: bot)
        assert [n['commit'] for n in ev['named']] == [rows[-2]['commit'][:7]], ev    # only b names the thread
        assert ev['last_at'].startswith('2030-01-04T00:00'), ev
        # foil: dropping the local-author filter would count c and f
        assert evidence('2030-01-02-demo-ask', w, rows, {}, '')['commits'] == 4

        # with a members table the counterpart is exactly the mapped author
        table = {'partner@example.org': ['role-proj-partner'], 'writer@example.org': ['role-proj-writer']}
        (board / MEMBERS).write_text(json.dumps({'members': {'Partner@example.org': ['role-proj-partner'],
                                                            'writer@example.org': ['role-proj-writer']}}), encoding='utf-8')
        assert load_members(board) == table
        ev = evidence('2030-01-02-demo-ask', w, rows, table, mine)
        assert ev['by'] == 'members' and ev['commits'] == 2, ev
        assert evidence('2030-01-02-demo-ask', dict(w, request={}), rows, table, mine) is None
        assert evidence('2030-01-02-demo-ask', w, None, table, mine) is None

        # counterpart's view: this checkout's commit names a request waiting on one of its own roles
        w_mine = dict(w, waiting_on={'agent': 'claude', 'session_id': 'role-proj-writer'})
        got = unposted('2030-01-02-demo-ask', w_mine, rows, table, mine)
        assert [g['commit'] for g in got] == [r['commit'][:7] for r in sorted(rows, key=lambda r: r['at'])
                                             if r['email'] == mine], got               # c (thread id) and f (request id)
        assert unposted('2030-01-02-demo-ask', w, rows, table, mine) == [], 'waiting on another role'
        assert unposted('2030-01-02-demo-ask', dict(w_mine, status='working'), rows, table, mine) == [], 'claimed'
        assert unposted('2030-01-02-demo-ask', w_mine, rows, {}, mine) == [], 'no table, no report'

        (board / MEMBERS).write_text('{not json', encoding='utf-8')
        assert load_members(board) == {}
        assert board_activity(board)[1] == {} and board_activity(repo) is None
    print('board_activity selftest: ok')
    return 0


if __name__ == '__main__':
    bc.utf8_stdio()
    if sys.argv[1:] == ['--selftest']:
        sys.exit(_selftest())
    print(__doc__.split('\n\n')[0])
    sys.exit(2)
