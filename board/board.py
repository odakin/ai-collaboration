#!/usr/bin/env python3
"""Board CLI: one-command request/claim/submit/accept, note, touch, addressed inbox (--json for runners), boards, init. See CONTRACT.md."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from board_workflow import KINDS, COARSE, LABELS, reduce_workflow, same_session, is_role, address_label
import board_config as bc
import board_transport as bt

ENGINE=Path(__file__).resolve().parent
SCHEMA_PATH=ENGINE/'schema/event.schema.json'
spec=importlib.util.spec_from_file_location('board_view', ENGINE/'board-view.py')
view=importlib.util.module_from_spec(spec); spec.loader.exec_module(view)


GIT_TIMEOUT=int(os.environ.get('AGENT_BOARD_GIT_TIMEOUT','120'))  # seconds per git call (clone/push of the temporary checkout)
NOTIFY_POLL_S=2     # watch: how often the local last-push note is looked at between remote checks
DEFAULT_REVIEWER_ENV='AGENT_BOARD_DEFAULT_REVIEWER'   # request: reviewer session id when --reviewer is absent; <project> expands
LAUNCH_CONFIG_DIR_ENV='AGENT_BOARD_LAUNCH_CONFIG_DIR'  # request to a role: the CLI config dir the worker runs under (a logged-in account); owner wiring
LAUNCH_MODEL_ENV='AGENT_BOARD_LAUNCH_MODEL'            # request to a role: default --model (else --expect-model, else the requester's own model)
LAUNCH_EFFORT_ENV='AGENT_BOARD_LAUNCH_EFFORT'          # request to a role: the effort when --effort is not given (else the requester's CLAUDE_EFFORT)
EFFORTS=bc.EFFORTS                                      # lowest first (a board's launch_effort_floor is one of them)
LAUNCH_CLI_ENV='AGENT_BOARD_LAUNCH_CLI'                # the CLI executable (default `claude`; tests point it at a stub)
LAUNCH_DEFAULT_ENV='AGENT_BOARD_LAUNCH_DEFAULT'        # `1` = on an owner board, a request to a role starts the worker at once unless --no-launch (owner wiring)
LAUNCH_REMOTE_CONTROL_ENV='AGENT_BOARD_LAUNCH_REMOTE_CONTROL'  # `1` = the worker keeps the account's remoteControlAtStartup (default: off for that session only); `follow` = the same, set by the fallback line for a requester the owner drives through Remote Control (the worker follows the requester's exposure)
LAUNCH_NO_REMOTE_CONTROL={'remoteControlAtStartup': False}   # --settings JSON: higher than the user settings file, which stays as it is
LAUNCH_IN_PLACE={'worktree': {'bgIsolation': 'none'}}        # --settings JSON: the worker edits the repository's own working tree (the CLI's background default refuses that until EnterWorktree)
LAUNCH_SURFACE_ENV='AGENT_BOARD_LAUNCH_SURFACE'          # request to a role: `desktop` = print the desktop app's start_session arguments (the worker shows in the app's list); default `background` = the CLI line
CODEX_LAUNCHER_ENV='AGENT_BOARD_CODEX_LAUNCHER'          # request to a Codex role: the launcher (default: layer-1 claude-config scripts/codex-app-launch.py next to this engine; tests point it at a stub)
CODEX_MODEL_ENV='AGENT_BOARD_CODEX_MODEL'                # request to a Codex role: the model when --expect-model is not given (else Codex's own config.toml)
CODEX_EFFORT_ENV='AGENT_BOARD_CODEX_EFFORT'              # request to a Codex role: the effort when --effort is not given (else Codex's own config.toml)
CODEX_LAUNCHED='起動した: Codex thread'                   # the note a Codex launch posts on its request; a second launch reads it and stops


def run(root, *args, check=True):
    p=subprocess.run(['git','-C',str(root),*args],capture_output=True,check=False,timeout=GIT_TIMEOUT)
    if check and p.returncode:
        raise ValueError(f'git {args[0]} failed: '+p.stderr.decode(errors='replace')[:1200])
    return p


def watch_wake(thread, seen, me, quiet, pending):
    """watch: events to report now, or None to keep watching.

    New events from the other side whose kind is in `quiet` (e.g. status notes) do not end the watch; they are
    kept in `pending` and reported together with the next event of another kind, so the watcher is woken only
    when there is something to act on and still sees the progress notes that came before it.
    """
    new=[e for e in thread if e['event_id'] not in seen
         and not same_session(_actor(e),me)]
    if not new: return None
    if all(e.get('kind') in quiet for e in new):
        pending.extend(new); return None
    out=pending+new; pending.clear(); return out


def transient_sync_error(ex):
    """watch: a failed sync (network reset, git timeout) is retried; a validation error still ends the watch."""
    if isinstance(ex,(subprocess.TimeoutExpired,OSError)): return True
    return isinstance(ex,ValueError) and str(ex).startswith('git ')


# A stop or a question reported in a note (heuristic for a hint only; it never decides anything).
STOP_WORDS=re.compile(r'(?i)停止|止ま|止め|中断|blocker|ブロッカー|判断を|返してほしい|返して欲しい|教えてほしい|確認してほしい|指示を'
                      r'|please\s+(?:advise|confirm)|\bstopped\b|\bblocked\b|\bwaiting\s+for\s+(?:your|the\s+requester)')


def _who(addr):
    """agent/session for one line: a role id alone and in full (either vendor acts under it), a native id with its agent
    by its first 8 characters."""
    if not addr: return '—'
    sid=addr.get('session_id') or ''
    return sid if is_role(sid) else f"{addr.get('agent')}/{sid[:8]}"


def _actor(e):
    a=(e or {}).get('actor') or {}
    return {'agent':a.get('agent'),'session_id':a.get('session_id')}


def request_state_line(w):
    """One line: the request's state as the caller just read it, with the open blocker and the command that answers it.

    Measured (a review request answered across two vendors): each side wrote from its last read — a note sent as the
    answer to a blocker (the request stayed blocked), a note naming an answered blocker as still open, and an answer
    aimed at that answered blocker while a new one was open. The posting and watch commands hold the remote's latest
    events, so they print the state instead of leaving it to each side's memory. None outside a request workflow."""
    if not w or not w.get('request'): return None
    st=w.get('status'); rid=w['request']['event_id']
    head=f"📋 この依頼の今: [{LABELS.get(st,st)}] 番 = {_who(w.get('waiting_on')) if w.get('waiting_on') else '— (終了)'}"
    b=w.get('blocker')
    if st=='blocked' and b:
        return (f"{head} / 開いた blocker = {b['event_id']} ({_who(_actor(b))}, {b.get('created_at','')[:16]}Z)"
                f" → 答えるのは依頼元の update --request {rid} --reply-to {b['event_id']} (note は答えにならない)")
    q,ans=w.get('question'),w.get('answer')
    if q and ans:
        return f"{head} / 開いた blocker なし (最後の blocker {q['event_id']} は update {ans['event_id']} で回答済み)"
    return f"{head} / 開いた blocker なし"


def kind_hints(ev, w, me):
    """Warnings for a post whose kind will not do what its text asks (printed last, on stderr; the post is not stopped).

    w = the request's state before this post, me = (agent, session). A note never moves a request (CONTRACT.md,
    request-and-receipt workflow): the reviewer's note does not answer an open blocker, and a claimant's stop posted as
    a note does not reach the requester as a question."""
    if not w or not w.get('request'): return []
    rid=w['request']['event_id']; kind=ev.get('kind')
    is_reviewer=same_session(w.get('reviewer'),me)
    is_claimant=bool(w.get('claim')) and same_session(_actor(w['claim']),me)
    b=w.get('blocker') if w.get('status')=='blocked' else None
    if kind=='note' and is_reviewer and b:
        return [f"⚠️ 開いた blocker {b['event_id']} ({_who(_actor(b))}, {b.get('created_at','')[:16]}Z) は未回答のまま。"
                f" note は依頼を動かさない (blocked のまま = 相手は submit できない)。 答えは update --request {rid} --reply-to {b['event_id']}"]
    if kind=='note' and is_claimant and not b and STOP_WORDS.search(ev.get('summary') or ''):
        return ["ℹ️ note は依頼を動かさない。 依頼元の判断を待つ停止・質問なら blocker で出す"
                " (依頼元の inbox に質問として載り、 依頼元の update で作業中に戻る)"]
    if kind=='update' and is_reviewer and not b and ev.get('reply_to'):
        q,ans=w.get('question'),w.get('answer')
        if q and ans and ev['reply_to']==q['event_id']:
            return [f"ℹ️ blocker {q['event_id']} は update {ans['event_id']} で回答済みで、 開いた blocker は無い"
                    " = この update は依頼を動かさない記録として載る"]
    return []


def other_party(w, me):
    """For a note inside a request, the participant on the other side: the claimant (else the assignee) for the
    reviewer, the reviewer for anyone else. me = (agent, session)."""
    if same_session(w.get('reviewer'),me):
        return _actor(w['claim']) if w.get('claim') else w.get('assigned_to')
    return w.get('reviewer')


def watch_report(key, new, thread, me, *, root, agent, session, request, quiet=()):
    """The lines a watch prints when it wakes: each new event; under a blocker that is still open and addressed to this
    session, the command that answers it; the request's state as just synced (request_state_line); and the full
    commands to re-read and to resume (no elided arguments, so the next watch is one paste)."""
    w=reduce_workflow(thread,view.now_utc())
    open_b=(w.get('blocker') or {}).get('event_id') if w.get('status')=='blocked' else None
    lines=[]
    for e in new:
        act=e['actor']
        lines.append(f"📮 {key[0]}/{key[1]} {e.get('kind')} {e.get('created_at','')[:16]} from {act.get('agent')}/{act.get('session_id')}: {(e.get('summary') or '')[:600]}")
        if e.get('kind')=='blocker' and e['event_id']==open_b and same_session(w.get('reviewer'),me):
            lines.append(f"   → この blocker に答える = update --request {request} --reply-to {e['event_id']} (note は答えにならない)")
    s=request_state_line(w)
    if s: lines.append(s)
    eng=Path(__file__).resolve(); q=''.join(f' --quiet-kind {k}' for k in sorted(quiet))
    lines.append(f"→ 読み直す: python3 {eng} show --root {root} --agent {agent} --session {session} --request {request} --sync")
    lines.append(f"→ 続きを見張る (background): python3 {eng} watch --root {root} --agent {agent} --session {session}"
                 f" --request {request}{q} --since {new[-1]['event_id']}")
    return lines


def source_gate(source, policy):
    # Classification is an explicit decision by the caller after reading source
    # instructions. Detect encryption without opening source content.
    if policy == 'no-post': raise ValueError('source policy forbids posting')
    if not source.is_dir(): raise ValueError('source directory missing')
    run(source,'rev-parse','--show-toplevel')
    encrypted=run(source,'check-attr','filter','--','CLAUDE.md').stdout.decode()
    if 'git-crypt' in encrypted and policy != 'encrypted-metadata-only':
        raise ValueError('encrypted source requires encrypted-metadata-only')
    if policy not in {'ordinary','encrypted-metadata-only'}:
        raise ValueError('explicit source classification required')


def board_branch(root):
    """The board's branch (board.json), read before cloning; `main` for a locked or unreadable config."""
    try: return bc.load(root)['branch']
    except ValueError: return 'main'


FRESH_S=10          # a fetch this young is reused by the same process (the post right after the event was built)
OPTIMISTIC_S=60     # a post trusts the branch head this machine fetched or pushed this recently (any process); a rejected push fetches
_FETCHED={}         # str(root) -> (commit, time.time()) of the last fetch in this process
_REUSED=False       # whether the last snapshot() reused such a fetch (a transition refused on a reused read is retried fresh)


@contextlib.contextmanager
def snapshot(root, fresh=False, optimistic=False):
    """The board as the remote holds it now, as a read-only board directory (board.json + events/) that `read` reads.

    Default transport (board_transport): one `git fetch`, then the fetched commit's tree as a persistent directory
    built once per machine from the blob cache (each event decrypted once, hard-linked) — seconds, independent of the
    board's size. `fresh=True` forces a new fetch (a rejected push); otherwise a fetch younger than FRESH_S in this
    process is reused, and with `optimistic=True` so is a branch head this machine fetched or pushed within
    OPTIMISTIC_S (posts: the push rejects a stale base, and the caller then reads fresh — one round trip saved on
    every post while a watch or a recent post keeps the machine current). Synchronized reads (`--sync`) never pass
    optimistic. `AGENT_BOARD_TRANSPORT=clone` keeps the previous transport (snapshot_clone) for one release.
    Neither transport touches the caller's index or working tree while reading.
    """
    if bt.transport()=='clone':
        with snapshot_clone(root) as dest: yield dest
        return
    if bc.is_locked(root): raise ValueError('board is encrypted and locked (unlock the repository before synchronized reads and posts)')
    repo=bt.Repo(root); key=str(Path(root).resolve())
    sha,at=_FETCHED.get(key,('',0.0))
    global _REUSED
    _REUSED=not (fresh or not sha or time.time()-at>FRESH_S)
    if not _REUSED and optimistic and not fresh and repo.fetched_age()<OPTIMISTIC_S:
        sha=repo.remote_sha(); _REUSED=bool(sha)
    if not _REUSED:
        sha=repo.fetch(); _FETCHED[key]=(sha,time.time())
    if not sha: raise ValueError(f'the remote has no branch {repo.branch} yet: push the board before synchronized posting')
    yield repo.materialized(sha)


def fetched(root, sha):
    """Record that the remote is known to be at `sha` (after this process pushed it)."""
    _FETCHED[str(Path(root).resolve())]=(sha,time.time())


@contextlib.contextmanager
def snapshot_clone(root):
    """Previous transport: clone the board's remote into a private temporary directory and yield the board directory.

    Never touches the caller's index or working tree. A board that is a subdirectory of a project repository
    (`<project>/board/`) is cloned partially (no file contents) with only that subdirectory checked out, so a
    large project costs commits and trees, not its files. Cost: the clone plus a `git-crypt unlock` of every file
    (measured 24 ms per file), which is why board_transport replaced it.
    """
    remote=run(root,'remote','get-url','origin').stdout.decode().strip()
    common=Path(run(root,'rev-parse','--path-format=absolute','--git-common-dir').stdout.decode().strip())
    sub=bc.subdir(root); branch=board_branch(root)
    with tempfile.TemporaryDirectory(prefix='agent-board-') as td:
        dest=Path(td)/'checkout'
        if sub:
            run(root,'clone','--quiet','--no-local','--filter=blob:none','--no-checkout','--branch',branch,'--single-branch',remote,str(dest))
            run(dest,'sparse-checkout','set','--no-cone','/'+sub+'/')
            run(dest,'checkout','--quiet',branch)
        else:
            run(root,'clone','--quiet','--no-local','--branch',branch,'--single-branch',remote,str(dest))
        board_dir=dest/sub if sub else dest
        # Reuse existing encryption capability. No key material is printed/exported.
        if bc.is_locked(board_dir):
            key=common/'git-crypt/keys/default'
            if not key.is_file(): raise ValueError('unlock the source board before using synchronized posting')
            # unlock smudges every tracked file, one git-crypt process each: ~30 ms per event file, so a board of
            # ~1000 events takes ~30 s (measured 2026-10-12: 986 files, 32 s). The old 30 s limit refused every post.
            p=subprocess.run(['git-crypt','unlock',str(key)],cwd=dest,capture_output=True,timeout=600)
            if p.returncode: raise ValueError('temporary board could not be unlocked')
        yield board_dir


def read(root):
    if bc.is_locked(root): raise ValueError('board is encrypted and locked')
    # EventList carries invalid-history diagnostics into the shared reducer.
    # Readers surface them; writers must check the target before every attempt.
    events, _=view.load_events(root)
    return events


NONE_TOUCH='(none)'  # a touch note's set when the session holds no path any more (an empty list is an ordinary note)
NO_POST_PARTS={'secrets-config','secrets','.secrets'}


def touch_base(root=None):
    """The workspace that holds the checkouts (board_config.workspace): touches are `<checkout>/<path>` below it."""
    return bc.workspace(root)


def norm_touch(raw, base=None):
    """A path a session declares it will write, as `<repo>/<path>` below the workspace (one name per file, symlinks resolved).

    Outside the workspace (shared-drive folders, home dotfiles) and credential repos are no-post sources: refused, so
    not even an opaque status reaches the board. A git-crypt file (or a file in a repo whose CLAUDE.md is git-crypt)
    becomes `h:<sha256 prefix>` = sessions still collide on the same file, but the board never names it.
    """
    base=Path(os.path.realpath(base or touch_base()))
    p=Path(os.path.expanduser(raw))
    p=Path(os.path.realpath(p if p.is_absolute() else base/p))
    try: rel=p.relative_to(base)
    except ValueError: raise ValueError(f'{raw}: workspace ({base}) の外 = 掲示板に載せない (no-post)。 相手とは直接 message で調整する')
    if not rel.parts: raise ValueError(f'{raw}: repo か file を指す')
    if NO_POST_PARTS & set(rel.parts): raise ValueError(f'{raw}: 認証情報の置き場 = 掲示板に載せない (no-post)')
    repo=base/rel.parts[0]; inner=Path(*rel.parts[1:]) if len(rel.parts)>1 else None
    if (repo/'.git').exists():
        probe=[str(inner)] if inner else []
        if inner and p.is_dir(): probe.append(str(inner/'x'))
        attrs=run(repo,'check-attr','filter','--','CLAUDE.md',*probe,check=False).stdout.decode()
        if 'git-crypt' in attrs: return 'h:'+hashlib.sha256(rel.as_posix().encode()).hexdigest()[:16]
    return rel.as_posix()


def touch_overlaps(a, b):
    if a.startswith('h:') or b.startswith('h:'): return a==b
    a=a.rstrip('/'); b=b.rstrip('/')
    return a==b or a.startswith(b+'/') or b.startswith(a+'/')


def touch_state(events, now, hours, *, project=None, thread=None):
    """Who holds which path now: {(agent, session): {'name', 'last', 'paths': {path: (since, 'project/thread')}}}.

    A session's set in a thread is the `touches` of its latest note that carries any (empty `touches` = an ordinary
    note, ignored; `(none)` = holds nothing). A path's `since` is when it entered that unbroken set, so the first
    declarer keeps a file while others queue behind it. Sets older than `hours` (a session that died) do not count.
    """
    per={}
    for e in sorted((e for e in events if e.get('kind')=='note' and e.get('touches')), key=lambda e: e.get('created_at','')):
        pk,tid=(e.get('project') or {}).get('key'),e.get('thread_id')
        if (project and pk!=project) or (thread and tid!=thread): continue
        act=e.get('actor') or {}; k=(act.get('agent'),act.get('session_id'),pk,tid)
        old=per.get(k,{}).get('paths',{})
        per[k]={'paths':{p:old.get(p,e['created_at']) for p in e['touches'] if p!=NONE_TOUCH},'last':e['created_at'],'name':act.get('task'),'summary':e.get('summary')}
    cutoff=view.iso_z(now-view.dt.timedelta(hours=hours)); out={}
    for (agent,sid,pk,tid),v in per.items():
        if not v['paths'] or v['last']<cutoff: continue
        s=out.setdefault((agent,sid),{'name':v['name'],'last':v['last'],'summary':v['summary'],'paths':{}})
        if v['last']>=s['last']: s['last'],s['name'],s['summary']=v['last'],v['name'] or s['name'],v['summary']
        for p,since in v['paths'].items():
            if p not in s['paths'] or since<s['paths'][p][0]: s['paths'][p]=(since,f'{pk}/{tid}')
    return out


def touch_owner(state, path):
    """The session that declared an overlapping path first, or None."""
    best=None
    for who,s in state.items():
        for p,(since,thr) in s['paths'].items():
            if touch_overlaps(p,path) and (best is None or (since,who)<(best['since'],best['who'])):
                best={'who':who,'since':since,'thread':thr,'path':p,'name':s['name']}
    return best


def touch_verdict(state, me, paths, labels=None):
    """labels: token -> the path as typed, shown locally beside an `h:` token (the board itself never holds it)."""
    lines=[]; blocked=False
    for tok in paths:
        o=touch_owner(state,tok); p=f'{tok} (= {labels[tok]})' if tok.startswith('h:') and labels and tok in labels else tok
        if o is None or o['who']==me:
            lines.append(f"🟢 {p} — 書いてよい ({'この session が持ち主' if o else '宣言している session は居ない'})"); continue
        blocked=True; agent,sid=o['who']
        lines.append(f"🔴 {p} — 先に {o['name'] or '—'} ({agent}/{sid[:8]}) が {o['since'][:16]}Z から {o['path']} を宣言 ({o['thread']})。"
                     f" 書かない: 中身を相手に SendMessage で渡すか、 相手が手放すまで待つ (touching --path {(labels or {}).get(tok,tok)} --wait を background で)")
    return lines, blocked


def post(root, event, *, before_push=None, landed=None):
    """Post one event; `landed` (a list), when given, receives the thread's events as they stand after the post."""
    # Caller has completed source_gate (and, on a collaborators board, check_post) before entering a snapshot.
    from board_schema import errors
    schema=json.loads(SCHEMA_PATH.read_text())
    errs=errors(event,schema)
    if errs: raise ValueError('; '.join(errs))
    if event['source_policy']=='encrypted-metadata-only':
        if not re.fullmatch(r'r-[a-f0-9]{10,}',event['thread_id']):
            raise ValueError('restricted thread requires opaque r-<10+ hex> identifier')
    rel=Path('events')/event['project']['key']/event['thread_id']/(view.compact(view.parse_ts(event['created_at']))+'--'+event['event_id']+'.json')
    if bt.transport()=='clone': return _post_clone(root,event,rel,before_push=before_push,landed=landed)
    return _post_fetch(root,event,rel,before_push=before_push,landed=landed)


def _validate_post(dest, event, cfg):
    """The transition check both transports run against the board as just read; returns (events, same-thread events,
    existing identical event or None)."""
    if cfg['audience']=='collaborators' and event['source_policy']!='ordinary':
        raise ValueError('a collaborators board takes ordinary posts only')
    if cfg['audience']=='collaborators' and event['project']['key'] not in cfg['sources']:
        raise ValueError(f"project {event['project']['key']} is not a source of this board")
    events=read(dest)
    view.assert_writable(events, event['project']['key'], event['thread_id'], event['event_id'])
    existing=next((e for e in events if e['event_id']==event['event_id']),None)
    same=[e for e in events if e['project']['key']==event['project']['key'] and e['thread_id']==event['thread_id']]
    if existing:
        if {k:v for k,v in existing.items() if not k.startswith('_')} != event:
            raise ValueError('event_id already exists with different content')
        return events,same,existing
    if event['kind']=='submit':
        current=reduce_workflow(same,view.now_utc())
        if current['claim'] is None or view.parse_ts(current['claim']['lease_until']) <= view.now_utc():
            raise ValueError('claim expired; reclaim before submission')
    w=reduce_workflow(same+[event],view.now_utc())
    if w['errors']: raise ValueError('; '.join(w['errors']))
    if event['kind'] == 'claim' and view.parse_ts(event['lease_until']) <= view.now_utc():
        raise ValueError('new claim already expired')
    return events,same,None


def _post_fetch(root, event, rel, *, before_push=None, landed=None):
    """Default transport: fetch, validate against the fetched tree, add the event as one commit through the object
    store, push; a rejected push (another writer won) fetches again and revalidates, three attempts."""
    repo=bt.Repo(root)
    encrypted='git-crypt' in run(repo.top,'check-attr','filter','--',repo.prefix+str(rel)).stdout.decode()
    text=(json.dumps(event,ensure_ascii=False,indent=2)+'\n').encode()
    for attempt in range(3):
        with snapshot(root,fresh=attempt>0,optimistic=attempt==0) as dest:
            if not (dest/bc.CONFIG).is_file():
                # Fail closed: an unpushed local board.json must not decide who reads a post (measured: a migration window).
                raise ValueError(f'the remote of this board has no {bc.CONFIG} yet: commit and push it before posting')
            cfg=bc.load(dest)  # the remote's settings decide, not a stale local copy
            if cfg['encryption']=='git-crypt' and not encrypted: raise ValueError('board event encryption is not configured')
            base=(dest/bt.BASE_FILE).read_text().strip()
            try:
                events,same,existing=_validate_post(dest,event,cfg)
            except ValueError:
                # Refused against a read reused from seconds ago: another writer may have moved the thread
                # (measured in a test mixing transports). Read the remote again before deciding.
                if attempt==0 and _REUSED: continue
                raise
            if existing:
                if landed is not None: landed[:]=same
                return event['event_id']
        blob=repo.write_blob(str(rel),text)
        if cfg['encryption']=='git-crypt' and not repo.blob_bytes(blob).startswith(view.GITCRYPT_MAGIC): raise ValueError('refusing to push an unencrypted event')
        sha=repo.commit(base,str(rel),blob)
        if before_push: before_push(attempt)
        if repo.push(sha):
            fetched(root,sha); repo.notify(sha); repo.fast_forward(sha,cfg['audience'])
            if landed is not None: landed[:]=same+[event]
            return event['event_id']
    raise ValueError(f"posting failed after three attempts; post it again with `retry --event-id {event['event_id']}` "
                     'and the same --agent, --session and --policy, plus --project (or --source) as in this command '
                     '(retry checks the source before it reads the saved event)')


def _post_clone(root, event, rel, *, before_push=None, landed=None):
    """Previous transport (AGENT_BOARD_TRANSPORT=clone): post through a temporary clone of the remote."""
    with snapshot_clone(root) as dest:
        if not (dest/bc.CONFIG).is_file():
            # Fail closed: an unpushed local board.json must not decide who reads a post (measured: a migration window).
            raise ValueError(f'the remote of this board has no {bc.CONFIG} yet: commit and push it before posting')
        cfg=bc.load(dest)  # the remote's settings decide, not a stale local copy
        # Global user identity may be absent in test/CI; inherit transport identity only.
        for field in ('user.name','user.email'):
            v=run(root,'config','--get',field,check=False).stdout.decode().strip()
            if v: run(dest,'config',field,v)
        encrypted='git-crypt' in run(dest,'check-attr','filter','--',str(rel)).stdout.decode()
        if cfg['encryption']=='git-crypt' and not encrypted: raise ValueError('board event encryption is not configured')
        branch=cfg['branch']
        for attempt in range(3):
            events,same,existing=_validate_post(dest,event,cfg)
            if existing:
                if landed is not None: landed[:]=same
                return event['event_id']
            p=dest/rel; p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps(event,ensure_ascii=False,indent=2)+'\n')
            run(dest,'add','--',str(rel)); run(dest,'commit','--quiet','-m','Add event')
            blob=run(dest,'show',f'HEAD:./{rel.as_posix()}').stdout
            if cfg['encryption']=='git-crypt' and not blob.startswith(view.GITCRYPT_MAGIC): raise ValueError('refusing to push an unencrypted event')
            if before_push: before_push(attempt)
            pushed=run(dest,'push','origin',f'HEAD:{branch}',check=False)
            if pushed.returncode==0:
                if landed is not None: landed[:]=same+[event]
                return event['event_id']
            run(dest,'fetch','--quiet','origin',branch)
            # Reset only this disposable checkout, then revalidate the transition
            # against the winner. A concurrent claim cannot sneak through rebase.
            run(dest,'reset','--hard',f'origin/{branch}')
        raise ValueError(f"posting failed after three attempts; post it again with `retry --event-id {event['event_id']}` "
                     'and the same --agent, --session and --policy, plus --project (or --source) as in this command '
                     '(retry checks the source before it reads the saved event)')


def _session_model():
    """Optional companion tool (layer-1 claude-config, cloned next to this engine). Raises when it is absent."""
    lib=ENGINE.parent.parent/'claude-config'/'scripts'/'lib'/'session_model.py'
    spec=importlib.util.spec_from_file_location('session_model',lib); sm=importlib.util.module_from_spec(spec); spec.loader.exec_module(sm)
    return sm


def native_session(agent, session, events):
    """The native id (or its 8-character prefix) behind a session address: the address itself, or for a role id the
    native id prefix that the acting session put in its name when it claimed (worker hand-off text:
    '<native id, 8 chars> (<model>)'). None when a role has no such named event yet."""
    if not session: return None
    if not session.startswith(('role-','resident-')): return session
    names=[(e.get('actor') or {}).get('task') or '' for e in events
           if (e.get('actor') or {}).get('agent')==agent and (e.get('actor') or {}).get('session_id')==session]
    return next((n[:8] for n in reversed(names) if re.match(r'[0-9a-f]{8}(?![0-9a-z])',n)),None)


def live_address(agent, session, events):
    """SendMessage address (`uds:<socket>`) of a Claude session that is alive on this machine, or ''.

    Read from the harness's live registry of every config dir (companion `session_model.live_address`): a session
    started with another config dir (an account-pinned Remote Control server, i.e. a session started from a phone)
    is often not listed by ListAgents and not reachable by name, but its socket address reaches it across config
    dirs and accounts on one machine (measured). A role id resolves through native_session.
    Never raises; '' when unknown, another vendor, or another machine.
    """
    if agent!='claude' or not session: return ''
    sid=native_session(agent,session,events)
    if not sid: return ''
    try:
        hit=_session_model().live_address(sid)
    except Exception:
        return ''
    return (hit or {}).get('address') or ''


def _codex_threads():
    """Optional companion reader of Codex's local threads (layer-1 claude-config next to this engine). Raises when absent."""
    lib=ENGINE.parent.parent/'claude-config'/'scripts'/'lib'/'codex_threads.py'
    spec=importlib.util.spec_from_file_location('codex_threads',lib); ct=importlib.util.module_from_spec(spec); spec.loader.exec_module(ct)
    return ct


def codex_queue_note(session, events, thread_key, lead='次に動く'):
    """The command that hands a Codex thread on this machine one line about the post, or None.

    A Codex session has no SendMessage. The Codex CLI's `codex queue --thread <id> --message <text>` queues a user
    message for an existing thread: a thread loaded in a running client gets it as a new turn after its current turn;
    a thread not open anywhere gets it when it is next opened (measured; reader = claude-config
    scripts/lib/codex_threads.py). The thread id comes from the address or, for a role, from the claimant's name.
    Never raises.
    """
    try:
        ct=_codex_threads()
        tid=ct.resolve(native_session('codex',session,events) or '')
        if not tid: return None
        held=ct.held_lock_ids()
        state=('生きている = 今の turn の後に新しい turn として届く' if held and tid in held else
               '今は開いていない = 次に開いた時に届く' if held is not None else '生きているかは読めない')
        rows=ct.thread_rows([tid])
        if held is not None and not rows and tid not in held: return None  # not a thread of this machine
        msg=f"掲示板 {thread_key}: 書き込みあり。 inbox --agent codex --session {session} --sync で読む"
        return f"→ {lead} codex/{tid[:8]} に知らせる ({state}。 Codex に SendMessage は無い): {ct.queue_hint(tid, msg)}"
    except Exception:
        return None


def role_agent(addr, events):
    """The vendor that acts under an address: for a role id, the agent of the latest event posted under it (a role is
    not one vendor: CONTRACT.md#role-any-agent; a request to `claude` + a role may be claimed by a Codex thread), else
    the address's own agent."""
    sid=(addr or {}).get('session_id')
    if not is_role(sid): return (addr or {}).get('agent')
    acted=[(e.get('actor') or {}).get('agent') for e in sorted(events,key=lambda e:e.get('created_at','')) if (e.get('actor') or {}).get('session_id')==sid]
    return acted[-1] if acted else addr.get('agent')


def counterpart_note(me, ev, events):
    """After a post: one line telling the poster how to reach the session that must act next on this machine
    (post-then-push, CONTRACT#post-then-push): a Claude session's SendMessage address, or for a Codex thread the
    `codex queue` command. A Codex poster has no SendMessage, so a live Claude counterpart is named without asking it to
    send one. A note inside a request reaches the other participant (other_party), whoever's turn it is (measured:
    without the line, a note answering a blocker reached the worker only when someone relayed it by hand). None
    otherwise. Never raises."""
    try:
        same=[e for e in events if e['project']['key']==ev['project']['key'] and e['thread_id']==ev['thread_id']]
        wf=reduce_workflow(same+[ev],view.now_utc())
        note=ev.get('kind')=='note'
        w=other_party(wf,me) if note else wf.get('waiting_on')
        lead='相手の' if note else '次に動く'
        if not w or same_session(w,me): return None
        w=dict(w,agent=role_agent(w,same+[ev]))
        if w.get('agent')=='codex':
            return codex_queue_note(w.get('session_id'),same+[ev],f"{ev['project']['key']}/{ev['thread_id']}",lead)
        addr=live_address(w.get('agent'),w.get('session_id'),same+[ev])
        if not addr: return None
        who=_who(w)
        if me and me[0]=='codex':
            return (f"→ {lead} {who} はこの機械で生きている ({addr})。 Codex には SendMessage が無い = 相手は自分の watch"
                    " か次の --sync で読む (Claude 側は request・claim・submit の後に watch を回す)。 急ぐなら本人に 1 行")
        return (f"→ {lead} {who} はこの機械で生きている: SendMessage の to = {addr} で thread id と書いた中身を 1 行"
                " (名前で届かない別の設定フォルダ・別アカウントの session にもこの宛先なら届く)")
    except Exception:
        return None


def codex_target_model(to_session):
    """(model, effort) of a Codex thread on this machine (local state, read-only), or None. Never raises."""
    try:
        ct=_codex_threads(); tid=ct.resolve(to_session)
        rows=ct.thread_rows([tid]) if tid else []
        return (rows[0].get('model'),rows[0].get('reasoning_effort'),tid) if rows and rows[0].get('model') else None
    except Exception:
        return None


def effort_note(got, want):
    """The tail added when the addressed live session's known effort is not the --effort asked for. Not a refusal,
    unlike a model mismatch: an effort is switched without losing the context (desktop: set_session_effort)."""
    if not want or not got or got.lower()==want.lower(): return ''
    return f" effort は {got} で --effort {want} と違う = 送る前に相手の effort を {want} にする (desktop なら set_session_effort) か、 文面に書く。"


def target_model_note(to_session, expect=None, agent=None, effort=None):
    """One line about the model the addressed session actually runs on, read before posting (never after).

    The title tag and the chip text do not decide a session's model; its transcript's last assistant turn does
    (layer-1 scripts/lib/session_model.py). A role id names a session that does not exist yet, so its model is
    whatever the app opens it with. With `expect` (a tier such as fable / opus, or a model-id substring), a
    known model that does not match refuses the post; an unknown model (another machine, no answer yet) is
    reported and lets the post through. With `effort`, a live session's known effort (the desktop app's record, or
    Codex's local state) that differs is reported. Rule: claude-config/conventions/multi-session-coordination.md#delegate-model-routing
    """
    if not to_session: return None
    if to_session.startswith(('role-','resident-')):
        return (f"宛先 {to_session} は役割 id = まだ無い session。 この request が出す起動の 1 行で開けば model と effort は固定"
                f" (model = --expect-model、 effort = --effort。 無ければ owner の既定、 それも無ければ起票元と同じ)。 手で開く窓 (chip・別の機械) では成り行き = hand-off 文の model の行が頼り。")
    if agent=='codex':
        got=codex_target_model(to_session)
        if not got:
            return f"宛先 codex/{to_session[:8]} の model はこの機の Codex の記録に無い (別の機の thread か、 まだ無い)。 仕事の難しさに合うかは送る前にしか直せない = 相手に model を聞くか文面に書く。"
        model,got_effort,tid=got
        line=(f"宛先 codex/{tid[:8]} の実際の model = {model}{(' effort '+got_effort) if got_effort else ''} (Codex の手元の記録)。 仕事の難しさに合うか送る前に見る (規約 #delegate-model-routing)。"
              +effort_note(got_effort,effort))
        if expect and expect.lower() not in model.lower():
            raise ValueError(f"宛先の model が --expect-model {expect} と違う: {model}。 合う宛先に変える / 自分でやる / 本人に 1 行で聞く。 承知の上なら --expect-model を外して送る")
        return line
    try:
        sm=_session_model()
        rows=[sm.describe(s) for s in sm.resolve(to_session)]
    except Exception:
        rows=[]
    known=[r for r in rows if r.get('model')]
    if not known:
        if expect: return f"宛先 {to_session[:8]} の model はこの機の記録に無い (別の機の session か、 まだ応答が無い) = --expect-model {expect} は確かめられない。 送る前に相手の機で session-model.py を回すか、 相手に聞く。"
        return f"宛先 {to_session[:8]} の model はこの機の記録に無い (別の機の session か、 まだ応答が無い)。 仕事の難しさに合うかは送る前にしか直せない = 相手に model を聞くか文面に書く。"
    r=known[0]
    line=(f"宛先 {r['sessionId'][:8]} の実際の model = {r['model']} (tier {r['tier']}、 最後の応答 {r['model_at'][:16]}{', name=' + r['name'] if r.get('name') else ''})。 仕事の難しさに合うか送る前に見る (規約 #delegate-model-routing)。"
          +effort_note(r.get('app_effort') or '',effort))
    if expect and expect.lower() not in (r['model'].lower(), r['tier'].lower()) and expect.lower() not in r['model'].lower():
        raise ValueError(f"宛先の model が --expect-model {expect} と違う: {r['model']} (tier {r['tier']})。 合う宛先に変える / 自分でやる / 本人に 1 行で聞く (名指しの宛先でも同じ)。 承知の上なら --expect-model を外して送る")
    return line


REVIEW_INTENT=re.compile(r'(?i)盲検|査読|レビュー|blind|cold-?eyes|referee|\breview(?:s|er|ed)?\b')
REVIEW_TARGET_CHECK=ENGINE.parent/'scripts'/'check-review-target.py'


def check_review_target(a):
    """A blind review is only as blind as its target (conventions/cold-eyes-isolation.md#contamination-channels (d)).

    A request whose summary or acceptance reads like a review names the referee copy the receiver opens
    (--review-target; scripts/check-review-target.py: no comment text left) or says --not-blind (the receiver may
    read the repository and its records). Measured: a deny list in the spec did not stop a header comment of the
    target that recorded the previous round's verdict. A person's request (--agent human, e.g. a chat bridge) is
    their own words, not an agent's spec, and is not gated."""
    targets=[str(Path(t).expanduser()) for t in (getattr(a,'review_target',None) or [])]
    if targets:
        p=subprocess.run([sys.executable,'-I',str(REVIEW_TARGET_CHECK),*targets],capture_output=True,text=True,timeout=60)
        if p.returncode==1:
            raise ValueError('--review-target は referee copy でない (対象 file 自体が来歴を運ぶ):\n'+p.stdout[-2000:])
        if p.returncode: raise ValueError('check-review-target.py が走らなかった: '+(p.stderr or p.stdout)[-600:])
        if '⚠️' in p.stdout:   # warnings (not refused): a sentence that may read as the target's own revision history
            print(p.stdout.rstrip()[-2000:],file=sys.stderr)
        for t in targets:
            q=subprocess.run(['git','-C',str(Path(t).parent),'ls-files','--error-unmatch',Path(t).name],capture_output=True)
            if q.returncode:
                print(f'⚠️ {t} は git に登録されていない = 別の機械の受け手には届かない (commit + push してから投稿する)',file=sys.stderr)
        a.reference=list(dict.fromkeys([*a.reference,*targets]))
        return
    if a.agent=='human' or getattr(a,'not_blind',False): return
    if REVIEW_INTENT.search(' '.join(x for x in (a.summary,a.acceptance) if x)):
        raise ValueError('要約が査読に読める: 盲検なら --review-target <comment を剥がした写し>、 受け手に repo と記録を'
                         '読ませる非盲検の検収なら --not-blind (cold-eyes-isolation.md#contamination-channels (d))')


def event_from(a, events):
    restricted=a.policy=='encrypted-metadata-only'
    if a.command=='request' or (a.command=='note' and not a.request):
        if not restricted and a.project != a.source.resolve().name.replace('_', '-'): raise ValueError('project must equal source checkout basename (underscores written as hyphens)')
        if not a.thread or (not restricted and not a.project): raise ValueError(f'{a.command} needs --thread and --project (or restricted policy)')
        if a.command=='request':
            if not a.to or not a.to_session: raise ValueError('request needs --to and --to-session')
            if not restricted and not a.acceptance: raise ValueError('request needs --acceptance')
            if not restricted: check_review_target(a)   # before ev['references']=a.reference below
        pk, tid, repo=a.project or 'restricted',a.thread,a.repo
    else:
        req=next((e for e in events if e['event_id']==a.request and e['kind']=='request'),None)
        if req is None: raise ValueError('--request must identify an existing request')
        if req['source_policy']!=a.policy: raise ValueError('source policy differs from request')
        pk,tid,repo=req['project']['key'],req['thread_id'],req['project']['repo']
        if a.command in ('accept','revise') and not a.reply_to:
            # Name the submission here instead of the schema's bare "$: missing reply_to" (measured: the reviewer could not tell what was missing).
            subs=[e for e in events if e.get('request_id')==a.request and e['kind']=='submit']
            latest=max(subs,key=lambda e:e['created_at'])['event_id'] if subs else None
            raise ValueError(f'{a.command} needs --reply-to <the submission you checked>'+(f': the latest submission is {latest}' if latest else ': no submission yet'))
        if a.command in ('submit','release') and not a.reply_to:
            # Same for the worker side (measured: "$: missing reply_to" alone, then the request id was tried and refused).
            claims=[e for e in events if e.get('request_id')==a.request and e['kind']=='claim']
            cur=max(claims,key=lambda e:e['created_at'])['event_id'] if claims else None
            raise ValueError(f'{a.command} needs --reply-to <your current claim, not the request>'+(f': the latest claim is {cur}' if cur else ': no claim yet'))
    kind=a.command
    # Existing template supplies metadata; workflow fields are added below.
    ev,path=view.build_template(kind='update',project=pk,thread=tid,task=a.session_name or 'workflow',agent=a.agent,
        repo=repo,restricted=restricted,lease_hours=a.lease_hours,summary=a.summary,now=view.now_utc())
    ev.update(schema_version=2,kind=kind)
    ev['actor']['instance']=a.instance or a.agent+'@'+view.socket.gethostname().split('.')[0]
    ev['actor']['session_id']=a.session
    if a.session_name and not restricted: ev['actor']['task']=a.session_name
    if a.event_id: ev['event_id']=a.event_id
    ev['request_id']=ev['event_id'] if (kind=='request' or (kind=='note' and not a.request)) else a.request
    if kind=='claim': ev['lease_until']=view.iso_z(view.now_utc()+view.dt.timedelta(hours=a.lease_hours))
    if a.reply_to: ev['reply_to']=a.reply_to
    if restricted:
        ev['summary']={**view.RESTRICTED_SUMMARY,**COARSE}[kind]
        if a.deliverable or a.reference or a.summary or a.acceptance or a.project or a.repo or getattr(a,'touch',None):
            raise ValueError('restricted posts forbid descriptive metadata; use source-side records')
    else:
        if not a.summary: raise ValueError('--summary required')
        if '``' in a.summary or '``' in (a.acceptance or ''):
            # Empty backticks are the fingerprint of a shell that command-substituted a `token` inside a
            # double-quoted argument (measured: a thread name vanished from a posted note). Refuse, since events are immutable.
            raise ValueError('summary/acceptance contains empty backticks (``) — the shell probably expanded a `...` token; quote the argument with single quotes and retry')
        if kind=='accept' and not a.reference:
            # The schema needs >= 1 reference on an ordinary accept; say so here instead of the bare "$.references: too few items".
            raise ValueError('accept needs --reference (the evidence you checked: the results / receipt file or a link)')
        ev['references']=a.reference
        if a.deliverable: ev['deliverables']=a.deliverable
        if getattr(a,'touch',None):
            if kind!='note': raise ValueError('--touch is for note (touch / untouch) only')
            ev['touches']=list(dict.fromkeys(a.touch))
    if kind=='request':
        ev['assignee']={'agent':a.to,'session_id':a.to_session}
        ev['acceptance']='Confirm completion in source.' if restricted else a.acceptance
        if not restricted and is_codex_role_request(a): ev['details']=codex_details(codex_fields(a))   # every machine reads where and how it starts
    if kind=='handover':
        if not a.to or not a.to_session or not a.role: raise ValueError('handover needs --to, --to-session, --role')
        ev.update(target={'agent':a.to,'session_id':a.to_session},handover_role=a.role)
    return ev


def safety_stop_handoff_text():
    """One refusal/recovery contract for Claude and Codex worker hand-offs."""
    return (
        "4. If a provider safety refusal occurs, stop the affected work and do not resend into the same window, "
        "reproduce the stopped output, or automatically retry on another model. The worker or requester records "
        "a board note (state and artifact paths only), then releases the current claim using its event id; "
        "the requester asks the owner about closing the window and a permitted next scope. A live process "
        "still counts for duplicate prevention. Read claude-config/conventions/tool-call-robustness.md"
        "#api-safety-filter-on-main-response.\n")


def restricted_handoff_parts(policy, source, session_name):
    """The parts of the claim and submit steps that differ for a restricted request (encrypted-metadata-only): the board
    refuses --summary, --session-name and --deliverable on its posts, and a restricted request names no project to find
    the source checkout from, so every post needs --source (measured: a worker given the ordinary steps was refused at
    claim, and once those were patched by hand, again at submit for --deliverable). Returns (source flag, claim tail,
    submit tail, restricted)."""
    if policy!='encrypted-metadata-only':
        return ('',f" --session-name '{session_name}' --summary '<one line>'",
                " plus `--reply-to <your claim's event id>` and `--deliverable <path>` for each deliverable.",False)
    src=f" --source {Path(source).resolve()}" if source else ' --source <the source checkout the requester named>'
    return (src,'',(" plus `--reply-to <your claim's event id>` only: a restricted post refuses --summary, --session-name"
                    " and --deliverable, so name the deliverables in the source's own record, not on the board."),True)


def handoff_text(root, role, request_id, spec, model, effort, surface='background', project=None, policy=None, reason=None, worktree=False, source=None):
    """What a worker window starts from (CONTRACT.md#worker-handoff-text): role, request, spec, the model and effort it
    must run on, and the first two steps. Written to a file and passed to the CLI whole, so quoting never bites.
    A desktop window gets a step 0: the app starts it on the requester's model when the asked one is higher, and on
    another effort (measured), so the worker reads the app's record first and stops when it differs. Step 0 holds back
    the request and its materials only; a session's own start-up reads are not the task. The claim and submit steps
    carry the whole command: a worker told only to `claim` with a session name found --root, --request, --project and
    --policy by refused posts (measured)."""
    run=(f" This window must run on {model}"+(f" at {effort} effort" if effort else '')
         +(f" (why this model and effort: {reason})" if reason else '')+'.') if model else ''
    eng=Path(__file__).resolve()
    hold=''
    if surface=='desktop' and model:
        sm_cli=ENGINE.parent.parent/'claude-config'/'scripts'/'session-model.py'
        hold=(f"0. First run `python3 {sm_cli} self`: if the app's record (`app の記録`) is not {model}"+(f" with effort {effort}" if effort else '')
              +", stop at once without reading the request or its materials and say so in one line; the requester switches you and sends `go`.\n")
    # A desktop window is the owner's own window: an approval asked there and relayed by the requester reached the owner
    # twice (measured), so the worker asks in its window only.
    ask=(" Ask the owner for any approval or OK in this window, where the owner reads it; do not ask the requester to relay it."
         if surface=='desktop' else '')
    scope=(f" --project {project}" if project else '')+(f" --policy {policy}" if policy else '')
    # The requester relays a worker's summary to the owner, and labels made up during the work (option letters, item
    # numbers) came through it unexplained, where the owner could not read them (measured).
    plain=(" Write every `submit` and `note` summary in plain words: do not use labels made up during the work (option"
           " letters, item or finding numbers); if you keep one, say what it refers to right after it.")
    # Where the work lands: a worker that went into a worktree pushed it to a branch the sessions reading main did not
    # see, and merging it back waited on the owner (measured). A worktree only when the requester asked for one.
    tree=(" Work in a git worktree of your own (the requester asked for one): call EnterWorktree before your first edit and"
          " commit and push its branch. Merging that branch into the main branch needs the owner's OK: do not merge it"
          " yourself; name the branch in the submit." if worktree else
          " Work in the repository's own working tree on its main branch: do not call EnterWorktree or create a branch;"
          " commit by explicit paths and push to main.")
    src,claim_tail,submit_tail,restricted=restricted_handoff_parts(policy,source,f"<your native session id, 8 chars> ({model or '<model>'})")
    if restricted: plain=''
    return (f"You are the board worker for role `{role}`, request `{request_id}`, spec `{spec or '(the request itself)'}`; execute it yourself.{run}{tree}\n"
            +hold+
            f"1. `python3 {eng} inbox --root {root} --agent claude --session {role} --sync`; if the request is not visible, do not read the spec — ask the requester or `watch`.\n"
            f"2. `python3 {eng} claim --root {root} --agent claude --session {role} --request {request_id}{scope}{src}{claim_tail}`; if refused with *another live claim exists*, stop and say so in one line.\n"
            f"3. Do the work the spec asks for; when done, `submit` with the same --root, --session, --request{scope}{src},{submit_tail}{plain}{ask}\n" + safety_stop_handoff_text())


def own_model(session):
    """The requester's own model (its transcript), or '' (companion absent, headless, another machine)."""
    try: return _session_model().model_of(session) or ''
    except Exception: return ''


def launch_settings(expect, session, effort=None):
    """(model, effort) a role's worker is started on: model = --expect-model, else the owner's default, else the
    requester's own model; effort = --effort, else the owner's default, else the requester's CLAUDE_EFFORT. Without
    --effort a worker asked for at another effort than its requester's got the requester's in the record, the
    start_session arguments and the hand-off text, and the launch check then refused the corrected arguments (measured)."""
    model=(expect or os.environ.get(LAUNCH_MODEL_ENV) or own_model(session) or '').strip()
    return model,launch_effort(effort)


def launch_effort(effort=None):
    """The effort a role's worker is started on (launch_settings' second half, without reading any transcript)."""
    return (effort or os.environ.get(LAUNCH_EFFORT_ENV) or os.environ.get('CLAUDE_EFFORT') or '').strip()


def check_effort_floor(cfg, effort, quote):
    """A Claude role's worker asked for below the board's `launch_effort_floor` (board.json; absent = no floor) is
    refused in one line naming where the rule is written, before anything is written or posted. The board reads the
    floor from its own config, so every entry path meets it (measured: requesters also call the engine directly,
    skipping a forwarder's wiring). The owner's own words naming that effort, verbatim (--effort-quote), let it
    through; they go to the launch record. Without a known effort nothing is refused."""
    floor=(cfg.get('launch_effort_floor') or {}).get('effort'); e=(effort or '').strip().lower()
    if floor not in EFFORTS or e not in EFFORTS or EFFORTS.index(e)>=EFFORTS.index(floor): return
    rule=((cfg.get('launch_effort_floor') or {}).get('rule') or '').strip() or f'{bc.CONFIG} の launch_effort_floor'
    if not ' '.join((quote or '').split()):
        raise ValueError(f"worker の effort {e} はこの掲示板の下限 {floor} より低い = 起こさない (規則 = {rule})。"
                         f" --effort {floor} 以上で出し直す。 本人がこの effort を名指したときだけ --effort-quote '<本人の発言そのまま>' を付けて通す")
    print(f"ℹ️ 下限 {floor} より低い effort {e} で起こす = 本人の名指し「{' '.join(quote.split())}」 (起動の記録に残す)")


def model_tier(model):
    """'claude-fable-5-1' → 'fable' (Mythos counts as fable, the same tier). The shared session-model helper decides when
    it is there; a board whose machine has no claude-config checkout (a co-author's) falls back to the family word in
    the id, and an id with none of them is its own tier."""
    m=(model or '').strip().lower()
    try: t=(_session_model().tier(m) or '').lower()
    except Exception: t=''
    if t: return t
    for word,tier in (('fable','fable'),('mythos','fable'),('opus','opus'),('sonnet','sonnet'),('haiku','haiku')):
        if word in m: return tier
    return m


def check_model_allow(cfg, model, quote):
    """A Claude role's worker asked for on a model tier that the board's `launch_model_allow` (board.json; absent = every
    tier) does not list is refused in one line naming where the rule is written, before anything is written or posted
    (the same two entry points as the effort floor, so every path meets it). The owner's own words naming that model,
    verbatim (--model-quote), let it through; they go to the launch record. Without a known model nothing is refused
    (the model = --expect-model, else the owner's default, else the requester's own = launch_settings)."""
    allow=cfg.get('launch_model_allow') or {}
    tiers=[str(t).strip().lower() for t in (allow.get('tiers') or []) if str(t).strip()]
    m=(model or '').strip()
    if not tiers or not m: return
    t=model_tier(m)
    if t in tiers: return
    rule=(allow.get('rule') or '').strip() or f'{bc.CONFIG} の launch_model_allow'
    if not ' '.join((quote or '').split()):
        raise ValueError(f"worker の model {m} (tier {t}) はこの掲示板が起こす model ({' / '.join(tiers)}) に無い = 起こさない (規則 = {rule})。"
                         f" --expect-model {tiers[0]} で出し直す。 本人がこの model を名指したときだけ --model-quote '<本人の発言そのまま>' を付けて通す")
    print(f"ℹ️ 掲示板が起こす model ({' / '.join(tiers)}) に無い {m} で起こす = 本人の名指し「{' '.join(quote.split())}」 (起動の記録に残す)")


def write_outbox(root, name, text):
    path=outbox_dir(root)/name; path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.write_text(text,encoding='utf-8'); path.chmod(0o600)
    return path


def write_launch_record(root, request_id, **fields):
    """The request's launch record (`<request id>.launch.json` in the outbox, never posted): the model, effort and
    surface the board chose for its worker. The claim check and the desktop launch check read it back."""
    rec=dict(fields,request_id=request_id,created_at=view.iso_z(view.now_utc()))
    return write_outbox(root,request_id+'.launch.json',json.dumps(rec,ensure_ascii=False,indent=1))


def launch_record(root, request_id):
    try: return json.loads((outbox_dir(root)/(request_id+'.launch.json')).read_text(encoding='utf-8'))
    except Exception: return None


def model_label(model, effort):
    """'claude-fable-5-1', 'xhigh' → 'Fable 5.1 xhigh' (the tail of a worker's title in the app's list)."""
    m=re.match(r'claude-([a-z]+)-(\d+)(?:-(\d+))?',model or '')
    name=(m.group(1).capitalize()+' '+m.group(2)+('.'+m.group(3) if m.group(3) else '')) if m else (model or '')
    return (name+(' '+effort if effort else '')).strip()


STAY_NESTED=('。 worker は依頼元の下に子のまま並ぶ (既定 = 一覧の上の段に独立させない)。 子の turn の終わりの知らせは依頼元に届くが、 依頼元が動くのは掲示板の提出と blocker だけで、 子が本人に出す問いは取り次がない (本人は worker の窓で答える)。 独立させるなら --detach')


def remote_control_fallback(root, request_id, session, model, effort, worktree=False, effort_quote=None, model_quote=None):
    """The line a requester runs when start_session is refused because the owner drives it through Remote Control (the
    app starts sessions only for instructions typed in the desktop app = measured). The worker then starts as a
    background CLI session with Remote Control on, under the same config dir, so it is listed where the owner reads (the
    phone's list); it is not the requester's child. `follow` = the worker takes the requester's exposure: the owner kept
    Remote Control on in the requester's window, which a refused start shows, so the forwarder lets it through even on
    an account shared with others (the owner's choice). A requester not on Remote Control does not get this refusal."""
    cfg=(os.environ.get(LAUNCH_CONFIG_DIR_ENV) or '').strip()
    env=(f'{LAUNCH_CONFIG_DIR_ENV}={shlex.quote(cfg)} ' if cfg else '')+f'{LAUNCH_REMOTE_CONTROL_ENV}=follow '
    line=(env+f'python3 {shlex.quote(str(ENGINE/"board.py"))} launch --root {shlex.quote(str(root))} --agent claude'
          +(f' --session {shlex.quote(session)}' if session else '')+f' --request {request_id} --surface background'
          +(f' --expect-model {shlex.quote(model)}' if model else '')+(f' --effort {shlex.quote(effort)}' if effort else '')
          +(f' --effort-quote {shlex.quote(effort_quote)}' if effort_quote else '')
          +(f' --model-quote {shlex.quote(model_quote)}' if model_quote else '')+(' --worktree' if worktree else '')+' --launch')
    return ('  start_session が「desktop アプリで打った指示からしか起こせない」 と断られたら (本人が Remote Control から操作中)、'
            ' 代わりにこの 1 行 = Remote Control つきの CLI の背景 session (本人のスマホの一覧に出る。 依頼元の子にはならない。'
            ' 依頼元と同じ account に載る = 依頼元が Remote Control に載っているときだけ使う):\n  '+line)


def desktop_plan(root, role, request_id, spec, expect, session, title=None, project=None, summary=None, detach=False, policy=None, effort=None, reason=None, worktree=False, source=None, effort_quote=None, model_quote=None):
    """The desktop app's start_session arguments for a role's worker (the worker is listed in the app, unlike a
    background CLI session). The board cannot call the app: the requesting Claude session calls start_session with
    these arguments. Returns (arguments, file). Title = the task first and the model last (measured: a title that
    starts with tags is cut to the same prefix for every child in the app's list). The worker stays the requester's
    child, listed under it (the owner's choice of view: the workers sit under the session that sent them). Only with
    detach does the launch record ask the requester to detach it once its model is right, so that its turn ends stop
    reaching the requester; the requester does not relay a child's questions to the owner either way (relayed, they
    reached the owner twice, measured), and the board's watch carries submit and blocker."""
    model,effort=launch_settings(expect,session,effort)
    text=handoff_text(root,role,request_id,spec,model,effort,surface='desktop',project=project,policy=policy,reason=reason,worktree=worktree,source=source)
    write_outbox(root,request_id+'.handoff.txt',text)
    name=role[len('role-'):] if role.startswith('role-') else role
    if project and name.startswith(project+'-'): name=name[len(project)+1:]
    name=re.sub(r'[^a-z0-9-]+','-',name.lower()).strip('-')[:24].strip('-') or 'worker'
    head=(title or re.split(r'[。:：(（]',summary or '')[0] or name).strip()
    head=head if len(head)<=40 else head[:39]+'…'
    label=model_label(model,effort)
    args={'initiation':'user_asked','context':'fresh','title':head+(' · '+label if label else ''),'name':name,'use_worktree':bool(worktree),
          'prompt':text,'background':(f'Board request {request_id} for role {role}, posted by session {(session or "")[:8]}. The request and its'
                                      ' spec are the task; report through the board (claim, a note at each milestone, submit). The requester'
                                      ' reviews the submission on the board.')}
    if model: args['model']=model
    if effort: args['effort']=effort
    path=write_outbox(root,request_id+'.start_session.json',json.dumps(args,ensure_ascii=False,indent=1))
    write_launch_record(root,request_id,role=role,spec=spec,model=model,effort=effort,surface='desktop',title=args['title'],
                        name=name,requester=session,detach=bool(detach),**({'reason':reason} if reason else {}),
                        **({'effort_quote':effort_quote} if effort_quote else {}),**({'model_quote':model_quote} if model_quote else {}),
                        **({'worktree':True} if worktree else {}))
    return args,path


def claim_model_check(a):
    """Refuse a claim that does not match the request's launch record (the record is on the machine that posted the
    request; elsewhere nothing is checked): a claimant on another model tier (--model-ok = the requester or the owner
    accepted the model it runs), and a subagent (Agent tool) claiming a request launched for a desktop window, which the
    owner cannot see in the app's list (--subagent-ok = the requester or the owner accepted it; a request meant for a
    subagent is posted with --surface agent).

    The claimant: the session running this command (CLAUDE_CODE_SESSION_ID, else the native id at the head of
    --session-name), and inside it the transcript whose last tool call is this claim. A subagent shares its parent's
    session id and environment, so reading the session alone took the parent's model for the subagent's (measured)."""
    if a.command!='claim' or a.agent!='claude' or not a.request: return
    rec=launch_record(a.root,a.request) or {}
    want=rec.get('model') or ''
    if not want and rec.get('surface')!='desktop': return
    m=re.match(r'([0-9a-f]{8})(?![0-9a-z])',(a.session_name or '').strip())
    native=(os.environ.get('CLAUDE_CODE_SESSION_ID') or (m.group(1) if m else '')
            or (a.session if a.session and not a.session.startswith(('role-','resident-')) else ''))
    if not native: return
    try:
        sm=_session_model(); rows=[sm.describe(s) for s in sm.resolve(native)]
    except Exception: return
    if len(rows)!=1: return
    actor=None
    try:
        if hasattr(sm,'acting_transcript'): actor=sm.acting_transcript(rows[0]['sessionId'],[a.request,'claim'])
    except Exception: actor=None
    if actor and actor.get('subagent') and rec.get('surface')=='desktop' and not getattr(a,'subagent_ok',False):
        raise ValueError(f'claim refused: this claim runs in a subagent (Agent tool) of session {native[:8]}, but the request was launched for a'
                         ' desktop window the owner sees in the app\'s list. Say so to the requester in one line and end: the requester'
                         ' opens the worker with start_session (the arguments the request printed). If the requester or the owner chose a'
                         ' subagent for this request, claim again with --subagent-ok')
    if getattr(a,'model_ok',False) or not want: return
    got=(actor or {}).get('model') or rows[0].get('model') or rows[0].get('app_model') or ''
    if got and sm.tier(got)!=sm.tier(want):
        who=f'this subagent of {native[:8]}' if actor and actor.get('subagent') else f'this session ({native[:8]})'
        raise ValueError(f'claim refused: {who} runs {got}, the request was launched for {want}. Say so to the requester'
                         ' in one line and end the turn (it switches the model and sends go); if the requester or the owner said this'
                         ' model is fine, claim again with --model-ok')


def launch_cli_settings(rc_off, worktree=False):
    """The --settings JSON of a background worker ('' = none). Remote Control off (rc_off) and, unless the requester
    asked for a worktree, the worker edits the repository's own working tree: the CLI's background default refuses
    Edit/Write under the session's cwd until EnterWorktree, so a worker that had cd'd into the repository went into a
    worktree and pushed its work to that branch instead of main (measured). The setting has to ride on --settings: an
    environment variable on the launch line does not reach the job (measured)."""
    s=dict(LAUNCH_NO_REMOTE_CONTROL) if rc_off else {}
    if not worktree: s.update(LAUNCH_IN_PLACE)
    return json.dumps(s) if s else ''


def launch_plan(root, role, request_id, spec, expect, session, project=None, policy=None, effort=None, reason=None, worktree=False, source=None, effort_quote=None, model_quote=None):
    """The command that starts the addressed worker as a background CLI session with model, effort and config dir pinned.

    Returns (argv, env, shell line, hand-off file). Model = --expect-model, else the owner's default, else the
    requester's own model (the chip's old default); effort = --effort, else the owner's default, else the requester's; config dir =
    the owner's default (a logged-in account: measured, the default dir of one machine was not logged in and the
    banner showed usage billing). Remote Control is off for the worker's session unless LAUNCH_REMOTE_CONTROL_ENV=1:
    an account with remoteControlAtStartup otherwise lists every worker on the desktop app's Remote Control shelf,
    which reads as work sent to another machine (measured). The worker works in the repository's own working tree
    unless worktree (launch_cli_settings). The board does not start the worker itself unless --launch is given: the
    requester's shell does, with the hand-off text read from the file."""
    model,effort=launch_settings(expect,session,effort)
    cfg=os.path.expanduser((os.environ.get(LAUNCH_CONFIG_DIR_ENV) or '').strip())
    text=handoff_text(root,role,request_id,spec,model,effort,project=project,policy=policy,reason=reason,worktree=worktree,source=source)
    path=write_outbox(root,request_id+'.handoff.txt',text)
    write_launch_record(root,request_id,role=role,spec=spec,model=model,effort=effort,surface='background',requester=session,
                        **({'reason':reason} if reason else {}),**({'effort_quote':effort_quote} if effort_quote else {}),
                        **({'model_quote':model_quote} if model_quote else {}),**({'worktree':True} if worktree else {}))
    cli=os.environ.get(LAUNCH_CLI_ENV) or 'claude'
    rc_off=os.environ.get(LAUNCH_REMOTE_CONTROL_ENV,'').strip() not in ('1','follow')
    settings=launch_cli_settings(rc_off,worktree)
    argv=([cli,'--bg']+(['--model',model] if model else [])+(['--effort',effort] if effort else [])
          +(['--settings',settings] if settings else [])+[text])
    env=dict(os.environ); env.pop('CLAUDECODE',None)
    if cfg: env['CLAUDE_CONFIG_DIR']=cfg
    line=((f'CLAUDE_CONFIG_DIR={shlex.quote(cfg)} ' if cfg else '')+shlex.quote(cli)+' --bg'+(f' --model {shlex.quote(model)}' if model else '')
          +(f' --effort {shlex.quote(effort)}' if effort else '')+(f' --settings {shlex.quote(settings)}' if settings else '')
          +f' "$(cat {shlex.quote(str(path))})"')
    return argv,env,line,path


def announce_launch(a, ev, audience):
    """For a request addressed to a Claude role: write the hand-off file, print the launch line, return (argv, env);
    None otherwise. Printed on --preview too (the command is part of what the requester reviews before posting)."""
    if is_codex_role_request(a): return codex_announce(a,ev,audience)
    if a.command!='request' or a.to!='claude' or not (a.to_session or '').startswith('role-'): return None
    # Default surface: on an owner board a desktop requester gets the desktop arguments (the owner sees that worker in
    # the app; a background CLI session is listed nowhere), whatever entry path called the engine (measured: a session
    # that called the engine directly skipped the forwarder's wiring and got the CLI line). Others get the CLI line.
    desktop_requester=os.environ.get('CLAUDE_CODE_ENTRYPOINT')=='claude-desktop'
    note=premium_note(*launch_settings(a.expect_model,a.session,a.effort),getattr(a,'reason',None))
    if note: print(note)
    surface=(getattr(a,'surface',None) or os.environ.get(LAUNCH_SURFACE_ENV)
             or ('desktop' if audience=='owner' and desktop_requester else 'background')).strip()
    if surface=='agent':
        # Work the owner does not watch, run as the requester's own subagent: no window to open, so only the record
        # (the claim check compares the subagent's model with it) and the hand-off text the Agent tool's prompt carries.
        model,effort=launch_settings(a.expect_model,a.session,a.effort)
        text=handoff_text(a.root,a.to_session,ev['event_id'],(a.reference or [None])[0],model,effort,project=a.project,policy=a.policy,reason=a.reason,source=a.source)
        hpath=write_outbox(a.root,ev['event_id']+'.handoff.txt',text)
        write_launch_record(a.root,ev['event_id'],role=a.to_session,model=model,effort=effort,surface='agent',requester=a.session,
                            **({'reason':a.reason} if a.reason else {}),**({'effort_quote':a.effort_quote} if a.effort_quote else {}),
                            **({'model_quote':a.model_quote} if a.model_quote else {}))
        print(f'→ 受け手は依頼元の Agent tool (subagent) で起こす = app の一覧に出ない (本人が見ない手元の仕事だけ)。'
              f' model {model or "?"} / effort {effort or "?"} を Agent の引数に、 prompt は hand-off 文 = {hpath}。'
              ' 本人が見る・話しかける worker なら --surface desktop で出し直す')
        return None
    if surface=='desktop':
        # The worker the owner wants to watch: a desktop session is listed in the app (a background CLI session with
        # Remote Control off is listed nowhere, and with it on it sits on the shelf shared with other machines = measured).
        detach=bool(getattr(a,'detach',False))
        args,spath=desktop_plan(a.root,a.to_session,ev['event_id'],(a.reference or [None])[0],a.expect_model,a.session,
                                title=getattr(a,'title',None),project=a.project,summary=ev.get('summary'),detach=detach,policy=a.policy,effort=a.effort,reason=a.reason,
                                worktree=getattr(a,'worktree',False),source=a.source,effort_quote=a.effort_quote,model_quote=a.model_quote)
        sm_cli=ENGINE.parent.parent/'claude-config'/'scripts'/'session-model.py'
        want=' / '.join(x for x in (args.get('model'),('effort '+args['effort']) if args.get('effort') else '') if x)
        print(f'→ 受け手を desktop app の session として起こす (本人の左の一覧に出る)。 起こすのは依頼元の Claude の start_session'
              f' (この shell からは起こせない)。 引数 = {spath} (全文が下):\n  '+json.dumps(args,ensure_ascii=False))
        print(f'  起こした後: python3 {sm_cli} <返りの local_…> で app の記録が {want or "頼んだ値"} かを読む。'
              ' start_session は呼び元より高い model と effort の指定を黙って捨てる (実測) = 違えば set_session_model → set_session_effort'
              ' の順で直し (worker は step 0 で止まって 1 行返す)、 記録が合ってから go を送る。 本人に「起きた」 と言うのはその後'
              +('。 記録が合ったら detach_session(<local_…>) = 一覧の上の段に独立させる (--detach の指定。 子の turn の終わりの知らせが'
                ' 依頼元に来なくなる。 提出と blocker は掲示板の watch で届く)' if detach else STAY_NESTED))
        print(remote_control_fallback(a.root,ev['event_id'],a.session,args.get('model'),args.get('effort'),getattr(a,'worktree',False),a.effort_quote,a.model_quote))
        if getattr(a,'launch',False): print('  (--launch は CLI の起動だけ = desktop の session は依頼元が start_session で起こす)')
        return None
    # A role names a window nobody has opened: print the command that opens it with model, effort and account
    # pinned (measured: the chip opens on the parent's model, and a pasted hand-off ran on whatever the window had).
    argv,env,line,hpath=launch_plan(a.root,a.to_session,ev['event_id'],(a.reference or [None])[0],a.expect_model,a.session,project=a.project,policy=a.policy,effort=a.effort,reason=a.reason,
                                    worktree=getattr(a,'worktree',False),source=a.source,effort_quote=a.effort_quote,model_quote=a.model_quote)
    if audience=='owner':
        print(f'→ 受け手を起こす (model・effort・account を固定、 貼り付け不要。 依頼元の shell でそのまま):\n  {line}')
    else:
        # The board cannot tell whose side a role is on; a collaborator opens theirs in their own environment.
        print(f'→ 受け手を起こす 1 行 (共同研究者も読む掲示板: 役割が依頼元の側のときだけ依頼元の shell で。'
              f' 相手の側の役割は相手が自分の環境で開く):\n  {line}')
    print(f'  (hand-off 文 = {hpath}。 desktop の窓で steer したいときだけ chip、 その文面もこの file)')
    return argv,env


def is_codex_role_request(a):
    return a.command=='request' and a.to=='codex' and (a.to_session or '').startswith('role-')


def this_host():
    return socket.gethostname().split('.')[0]


def same_host(x, y):
    n=lambda h: (h or '').strip().lower().split('@')[-1].split('.')[0]
    return bool(n(x)) and n(x)==n(y)


def codex_defaults():
    """(model, effort) from Codex's own config (top-level keys of $CODEX_HOME/config.toml), '' when absent."""
    home=Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex'); got={}
    try:
        for line in (home/'config.toml').read_text(encoding='utf-8').splitlines():
            s=line.strip()
            if s.startswith('['): break
            m=re.match(r'(model|model_reasoning_effort)\s*=\s*"([^"]+)"',s)
            if m: got[m.group(1)]=m.group(2)
    except OSError: pass
    return got.get('model',''),got.get('model_reasoning_effort','')


def codex_fields(a):
    """How a Codex role's worker starts (CONTRACT.md#codex-worker-launch): the machine, model, effort, working directory
    and surface. Written into the request's `details` (one `launch-<key>: <value>` line each), so a session on another
    machine reads the same values and the launch host is on record before anything starts."""
    if getattr(a,'_codex_fields',None): return a._codex_fields
    dm,de=codex_defaults()
    cwd=a.launch_cwd or str(bc.workspace(a.root))
    home=str(Path.home())
    f={'host':a.launch_host or this_host(),
       'model':(a.expect_model or os.environ.get(CODEX_MODEL_ENV) or dm or '').strip(),
       'effort':(a.effort or os.environ.get(CODEX_EFFORT_ENV) or de or '').strip(),
       'cwd':'~'+cwd[len(home):] if cwd==home or cwd.startswith(home+os.sep) else cwd,
       'surface':'background' if a.surface=='background' else 'codex-app'}
    if getattr(a,'title',None): f['title']=' '.join(a.title.split())   # the thread's name in the app (measured: --title was ignored)
    if a.surface=='background': f['headless-reason']=' '.join((a.headless_reason or '').split())
    a._codex_fields=f
    return f


def codex_details(f):
    return '\n'.join(f'launch-{k}: {v}' for k,v in f.items() if v)


def parse_codex_details(text):
    return {m.group(1):m.group(2).strip() for m in re.finditer(r'(?m)^launch-([a-z-]+):[ \t]*(.*)$',text or '')}


def codex_handoff_text(root, role, request_id, spec, f, project=None, policy=None, source=None):
    """What a Codex worker thread starts from: the Codex counterpart of handoff_text. Step 0 reads this thread's own
    model and effort from Codex's local record (the launcher pins them; a text pasted into a window opened by hand runs
    on whatever that window has). The Codex app runs the thread, so the owner may watch it and talk to it there, but the
    requester reads the board: questions for the requester go to the board as a blocker. Board commands run one at a
    time with their values typed out: the app's sandbox has no network, and the Codex rule that runs the board's commands
    outside it matches a plain lone command only (measured: a push chained after another command with `;` stayed
    sandboxed, and so did a claim whose --session-name used `${CODEX_THREAD_ID:0:8}`; the same worker's plain `inbox
    --sync` and `note` reached the board)."""
    eng=Path(__file__).resolve(); launcher=codex_launcher(); m,e=f.get('model'),f.get('effort')
    scope=(f" --project {project}" if project else '')+(f" --policy {policy}" if policy else '')
    run=(f" This thread must run on {m}"+(f" at {e} effort" if e else '')+'.') if m else ''
    src,claim_tail,submit_tail,restricted=restricted_handoff_parts(policy,source,f"<the first 8 characters of your thread id, typed out> ({m or '<model>'})")
    hold=(f"0. First run `python3 {launcher} check-self --model {m}"+(f" --effort {e}" if e else '')+"`: if it does not print ✅,"
          " stop at once without reading the request or its materials and say so in one line.\n") if m else ''
    return (f"You are the board worker for role `{role}`, request `{request_id}`, spec `{spec or '(the request itself)'}`; execute it yourself.{run}\n"
            +hold+
            f"1. `python3 {eng} inbox --root {root} --agent codex --session {role} --sync`; if the request is not visible, do not read the spec — say so in one line and stop.\n"
            f"2. `python3 {eng} claim --root {root} --agent codex --session {role} --request {request_id}{scope}{src}{claim_tail}`"
            +('' if restricted else " (read the thread id first with a separate `echo $CODEX_THREAD_ID`)")
            +"; if refused with *another live claim exists*, stop and say so in one line.\n"
            f"3. Do the work the spec asks for; when done, `submit` with the same --root, --agent, --session, --request{scope}{src},{submit_tail}"
            +('' if restricted else " Write every `submit` and `note` summary in plain words: do not use labels made up during the work (option letters, item"
            " or finding numbers); if you keep one, say what it refers to right after it.")
            +" Ask a question for the requester as a"
            " `blocker` on the board: the requester reads the board, not this window (the owner may also watch this window and"
            " talk to you here). Run each board command on its own, with every value typed out: not chained with `;`, `&&` or a"
            " pipe, and with no `$` expansion (`$VAR`, `${…}`, `$(…)`) in it. A Codex rule runs exactly such plain commands"
            " outside the sandbox, which has no network; any other form stays inside and cannot reach the board.\n"
            + safety_stop_handoff_text())


def codex_launcher():
    return Path(os.environ.get(CODEX_LAUNCHER_ENV) or ENGINE.parent.parent/'claude-config'/'scripts'/'codex-app-launch.py')


def codex_plan(root, role, request_id, spec, f, project=None, policy=None, title=None, source=None):
    """(argv, shell line, hand-off file) that start the worker through the launcher (claude-config
    scripts/codex-app-launch.py): a thread with model, effort, sandbox and working directory pinned, whose hand-off is
    queued and run by the Codex app, so the owner sees its progress and can talk to it there (measured: a `codex exec`
    thread is listed nowhere in the app; a thread the shared daemon runs shows no progress there). A board worker posts:
    the board's cache and checkout writable, and the board engine's worker subcommands allowed outside the sandbox by a
    Codex rule (the app's sandbox has no network); network on for the daemon fallback (approval never: it runs
    unattended). The thread's name = the request's --title (else the summary's first clause) and the model."""
    text=codex_handoff_text(root,role,request_id,spec,f,project=project,policy=policy,source=source)
    hpath=write_outbox(root,request_id+'.handoff.txt',text)
    rec=write_launch_record(root,request_id,role=role,spec=spec,model=f.get('model'),effort=f.get('effort'),surface='codex-app',
                            launch_host=f.get('host'),cwd=f.get('cwd'))
    label=' '.join(x for x in (f.get('model'),f.get('effort')) if x)
    name=((title or role)[:60]+(' · '+label if label else ''))
    argv=[sys.executable,str(codex_launcher()),'start','--cwd',os.path.expanduser(f['cwd']),'--prompt-file',str(hpath),
          '--name',name,'--host',f['host'],'--record',str(rec),'--json']
    if f.get('model'): argv+=['--model',f['model']]
    if f.get('effort'): argv+=['--effort',f['effort']]
    # The sandbox keeps `.git` read-only inside writable roots unless the git dir itself is named (measured: a worker's
    # `--sync` was refused at .git/FETCH_HEAD; naming the git dir let it write).
    cache=Path(os.environ.get('AGENT_BOARD_CACHE_DIR') or Path.home()/'.cache'/'agent-board')
    gd=run(root,'rev-parse','--path-format=absolute','--git-common-dir',check=False).stdout.decode().strip()
    argv+=['--network','--writable-root',str(cache),'--writable-root',str(Path(root).resolve())]+(['--writable-root',gd] if gd else [])
    argv+=['--allow-board-engine',str(Path(__file__).resolve())]
    line=' '.join(shlex.quote(x) for x in ['python3',*argv[1:]] if x!='--json')
    return argv,line,hpath


def codex_headless_line(root, request_id, f, hpath):
    """The headless `codex exec` line, printed only when the requester chose it with a reason (--surface background
    --headless-reason): its thread is listed nowhere in the Codex app. The reason travels in CODEX_EXEC_REASON, which
    the launch check reads (claude-config hooks/codex-headless-launch-check.sh)."""
    out=outbox_dir(root)/(request_id+'.final.txt')
    cli=(_codex_threads().codex_binary() if _codex_threads_ok() else None) or 'codex'
    parts=[cli,'exec','--json','-o',str(out),'--skip-git-repo-check','-C',os.path.expanduser(f['cwd'])]
    if f.get('model'): parts+=['-m',f['model']]
    if f.get('effort'): parts+=['-c',f'model_reasoning_effort="{f["effort"]}"']
    parts+=['-c','approval_policy="never"','-c','sandbox_mode="workspace-write"']
    return (f"CODEX_EXEC_REASON={shlex.quote(f.get('headless-reason') or '')} "+' '.join(shlex.quote(x) for x in parts)
            +f' "$(cat {shlex.quote(str(hpath))})" </dev/null')


def _codex_threads_ok():
    try: _codex_threads(); return True
    except Exception: return False


def codex_announce(a, ev, audience):
    """For a request to a Codex role: write the hand-off and the launch record, print how the worker starts, and return
    (argv, env) when it starts on this machine (None when another machine launches it, or for the headless line)."""
    f=codex_fields(a); rid=ev['event_id']; spec=(a.reference or [None])[0]
    if f['surface']=='background':
        text=codex_handoff_text(a.root,a.to_session,rid,spec,f,project=a.project,policy=a.policy,source=a.source)
        hpath=write_outbox(a.root,rid+'.handoff.txt',text)
        write_launch_record(a.root,rid,role=a.to_session,spec=spec,model=f.get('model'),effort=f.get('effort'),surface='background',
                            launch_host=f['host'],cwd=f['cwd'],headless_reason=f.get('headless-reason'))
        print('→ 受け手を headless の codex exec で起こす (理由 = '+f.get('headless-reason','')+')。 Codex アプリのどこにも出ない。'
              ' 依頼元の shell でそのまま (理由は CODEX_EXEC_REASON で起動の検査に渡る):\n  '+codex_headless_line(a.root,rid,f,hpath))
        return None
    argv,line,hpath=codex_plan(a.root,a.to_session,rid,spec,f,project=a.project,policy=a.policy,source=a.source,
                               title=f.get('title') or re.split(r'[。:：(（]',ev.get('summary') or '')[0].strip() or None)
    print('→ 受け手を Codex アプリに出る形で起こす (thread を作って起動文を予約し、 アプリに開かせる = アプリが走らせる。'
          f' model {f.get("model") or "既定"} / effort {f.get("effort") or "既定"} / cwd {f["cwd"]} / 機械 {f["host"]} を固定):\n  {line}')
    print(f'  (hand-off 文 = {hpath}。 進行はアプリに出て、 その窓から話しかけられる)')
    if not same_host(f['host'],this_host()):
        print(f'→ 起動する機械 = {f["host"]} (この機械 {this_host()} ではない) = ここでは起こさない。 {f["host"]} の session が'
              f' board.py launch --request {rid} で起こす (掲示板の details に機械・model・effort・cwd がある)')
        return None
    a._codex_launch=True
    return argv,dict(os.environ)


def codex_launched(events, request_id):
    return [e for e in events if e.get('kind')=='note' and e.get('request_id')==request_id
            and (e.get('summary') or '').startswith(CODEX_LAUNCHED)]


def run_codex_launch(a, request_id, argv, env):
    """Run the launcher, print what started, and post the launch note on the request (the record another machine's
    session reads before it would start the same worker). A refused launch (another machine, sealed sandbox leaking
    instructions) raises with the launcher's own words."""
    p=subprocess.run(argv,env=env,capture_output=True,text=True,timeout=180,cwd=str(Path.home()))
    if p.returncode not in (0,1):
        raise ValueError('Codex の起動が止まった (exit '+str(p.returncode)+'): '+((p.stderr or '')+(p.stdout or '')).strip()[-1200:])
    try: out=json.loads((p.stdout or '').strip().splitlines()[-1])
    except Exception: raise ValueError('Codex の起動の出力が読めない: '+(p.stdout or p.stderr or '')[-600:])
    tid=out.get('thread_id') or '?'
    print(f"→ 起動した: Codex thread {tid} ({out.get('host')}, model {out.get('model')} / effort {out.get('effort')}"
          f"{', アプリに開かせた' if out.get('revealed') else ''})。 読んだ指示 file: {', '.join(out.get('instruction_sources') or []) or '(なし)'}")
    if p.returncode==1: print('  ⚠️ thread の model・effort が頼んだ値と違う (起動の道具の出力を見る)')
    summary=f"{CODEX_LAUNCHED} {tid} ({out.get('host')}, {out.get('model')} {out.get('effort')})。 同じ依頼を別の機械で起こさない"
    try: post_request_note(a,request_id,summary)
    except Exception as ex:  # the worker runs; only the record is missing
        print(f'⚠️ 起動の記録 (note) を掲示板に載せられなかった: {ex}。 手で note を出す: summary = {summary}',file=sys.stderr)
    return out


def post_request_note(a, request_id, summary):
    import copy
    if a.policy=='encrypted-metadata-only':
        print('  (不透明な thread なので起動の記録は掲示板に載せない = 他の機械からは起動済みが見えない)'); return
    with snapshot(a.root,fresh=True) as dest: events=read(dest)
    n=copy.copy(a); n.command='note'; n.request=request_id; n.reply_to=None; n.event_id=None; n.touch=None
    n.deliverable=[]; n.reference=[]; n.acceptance=None; n.summary=summary; n.to=None; n.to_session=None
    ev=event_from(n,events)
    from board_schema import errors
    same=[e for e in events if e['project']['key']==ev['project']['key'] and e['thread_id']==ev['thread_id']]
    probs=errors(ev,json.loads(SCHEMA_PATH.read_text()))+[x for x in reduce_workflow(same+[ev],view.now_utc())['errors'] if x.startswith(ev['event_id']+':')]
    if probs: raise ValueError('; '.join(probs))
    print('posted '+post(a.root,ev)+' (起動の記録)')


def cmd_launch(a):
    """`launch --request <id>`: on a Claude role, open its worker window (launch_claude_role); on a Codex role,
    start the worker of a Codex-role request on this machine from what the request carries
    (its `details` lines), after reading the board again: refused when the request names another machine, when a launch
    note is already on the request, or when the work was already claimed (CONTRACT.md#codex-worker-launch)."""
    if not a.request: raise ValueError('launch needs --request <request id>')
    with snapshot(a.root,fresh=True) as dest: events=read(dest)
    req=next((e for e in events if e['event_id']==a.request and e['kind']=='request'),None)
    if req is None: raise ValueError('request not found: '+a.request)
    asg=req.get('assignee') or {}
    if asg.get('agent')=='claude' and str(asg.get('session_id','')).startswith('role-'):
        return launch_claude_role(a,req,events)
    if asg.get('agent')!='codex' or not str(asg.get('session_id','')).startswith('role-'):
        raise ValueError('launch は Codex か Claude の役割 id 宛ての依頼だけ (この依頼の宛先 = '+_who(asg)+')')
    f=parse_codex_details(req.get('details'))
    if not f.get('host'): raise ValueError('この依頼には起動の情報 (details の launch-* 行) が無い = 依頼元が request を出し直す')
    done=codex_launched(events,a.request)
    if done: raise ValueError('起動済み: '+done[-1]['summary']+' = 二重に起こさない')
    same=[e for e in events if (e['project']['key'],e['thread_id'])==(req['project']['key'],req['thread_id'])]
    st=reduce_workflow(same,view.now_utc()).get('status')
    if st not in ('requested','stale'): raise ValueError(f'この依頼は {st} = 受け手はもう居る (か終わった)。 起こさない')
    if not same_host(f['host'],this_host()):
        raise ValueError(f"この依頼の起動する機械 = {f['host']} (この機械 = {this_host()})。 {f['host']} の session が起こす")
    if f.get('surface')=='background':
        raise ValueError('この依頼は headless の codex exec を選んでいる (理由 = '+f.get('headless-reason','')+') = 依頼元の shell が起こす')
    a.policy=req['source_policy']; a.project=req['project']['key']
    spec=next(iter(req.get('references') or []),None)
    argv,line,_=codex_plan(a.root,asg['session_id'],a.request,spec,f,project=a.project,policy=a.policy,source=getattr(a,'source',None),
                           title=f.get('title') or re.split(r'[。:：(（]',req.get('summary') or '')[0].strip() or None)
    print('→ 起こす: '+line)
    run_codex_launch(a,a.request,argv,dict(os.environ))


def premium_note(model, effort, reason):
    """A role's worker asked for on the top tier or at max effort with no reason: one line when the request is posted
    or its worker opened (the desktop launch check stops such a start on machines that turn its premium gate on). The
    board does not judge the work from its words: measured, every word rule missed some of the model choices people
    made."""
    m=(model or '').lower()
    top='fable' in m or 'mythos' in m
    mx=(effort or '').lower()=='max'
    if not (top or mx) or reason: return ''
    what=' と '.join(x for x in (('Fable' if top else ''),('max' if mx else '')) if x)
    return (f'⚠️ {what} の worker を理由なしで頼んでいる。 worker 自身が物理の中身 (導出・議論の正否・どう述べるか) を判断し、'
            ' 生み出す仕事か。 与えられた文や基準に照らして読む仕事なら --expect-model / --effort を一段下げて出し直す。'
            " 要るなら --reason '<worker が何を導出・判断するか>' を付ける (起動を検査する機械では、 理由が無いと起動の段で止まる)")


def launch_claude_role(a, req, events):
    """`launch --request <id>` on a Claude role: open the worker window for a request already on the board (a
    co-author's AI, another machine or another session posted it, so this machine has no launch record) the way a
    request to a role does: the launch record, the hand-off file and the start_session arguments (or the CLI line),
    with nothing posted. Without it the receiving side wrote its card by hand, and neither its model nor its effort was
    checked against anything (measured: a co-author's prose review went out as a top-tier, max-effort card). Model and
    effort = --expect-model / --effort, else the owner's defaults, else this session's. Refused once the work has a
    receiver (a second window for the same request), and below the board's effort floor (check_effort_floor)."""
    same=[e for e in events if (e['project']['key'],e['thread_id'])==(req['project']['key'],req['thread_id'])]
    st=reduce_workflow(same,view.now_utc()).get('status')
    if st not in ('requested','stale'): raise ValueError(f'この依頼は {st} = 受け手はもう居る (か終わった)。 起こさない')
    check_effort_floor(bc.load(a.root),launch_effort(a.effort),a.effort_quote)
    check_model_allow(bc.load(a.root),launch_settings(a.expect_model,a.session,a.effort)[0],a.model_quote)
    role=req['assignee']['session_id']
    surface=(a.surface or os.environ.get(LAUNCH_SURFACE_ENV)
             or ('desktop' if os.environ.get('CLAUDE_CODE_ENTRYPOINT')=='claude-desktop' else 'background')).strip()
    if surface=='agent': raise ValueError('launch: --surface desktop か background (subagent に窓は要らない)')
    project=req['project']['key']; policy=req['source_policy']; spec=next(iter(req.get('references') or []),None)
    note=premium_note(*launch_settings(a.expect_model,a.session,a.effort),a.reason)
    if note: print(note)
    poster=(req.get('actor') or {}).get('session_id') or '?'
    if surface=='desktop':
        args,spath=desktop_plan(a.root,role,a.request,spec,a.expect_model,a.session,title=a.title,project=project,
                                summary=req.get('summary'),detach=a.detach,policy=policy,effort=a.effort,reason=a.reason,worktree=a.worktree,source=getattr(a,'source',None),
                                effort_quote=a.effort_quote,model_quote=a.model_quote)
        args['background']=(f'Board request {a.request} for role {role}, posted by {poster} and opened here by session'
                            f' {(a.session or "")[:8]}. The request and its spec are the task; report through the board (claim,'
                            ' a note at each milestone, submit). The poster reviews the submission on the board.')
        spath=write_outbox(a.root,a.request+'.start_session.json',json.dumps(args,ensure_ascii=False,indent=1))
        print(f'→ 既にある依頼 {a.request} の worker を desktop app の session として起こす引数 (掲示板には何も書いていない)。'
              ' 起こすのはこの session の start_session (本人が押す card なら initiation だけ own_initiative に替える)。'
              f' 引数 = {spath} (全文が下):\n  '+json.dumps(args,ensure_ascii=False))
        print('  起こした後: app の記録で model・effort を読み、 違えば set_session_model → set_session_effort → worker の 1 行を待って go'
              +('。 合ったら detach_session (--detach の指定)' if a.detach else STAY_NESTED))
        return
    argv,env,line,hpath=launch_plan(a.root,role,a.request,spec,a.expect_model,a.session,project=project,policy=policy,
                                    effort=a.effort,reason=a.reason,worktree=a.worktree,source=getattr(a,'source',None),effort_quote=a.effort_quote,
                                    model_quote=a.model_quote)
    print(f'→ 既にある依頼 {a.request} の worker を起こす 1 行 (掲示板には何も書いていない):\n  {line}')
    if a.launch: print('→ 起動した: '+launch(argv,env,cwd=bc.workspace(a.root)).replace('\n','\n  '))


def launch_now(a, audience):
    """Whether a request's worker starts now (CONTRACT.md#worker-handoff-text): --launch always (the requester says
    the role is its own to open); the owner's wiring default only on an owner board, since a role on a collaborator
    board may be a collaborator's and a worker started here would claim under it."""
    if a.launch: return True
    return audience=='owner' and os.environ.get(LAUNCH_DEFAULT_ENV,'').strip()=='1' and not a.no_launch


def launch(argv, env, cwd=None):
    """Start the worker now (in the workspace, so the projects' instructions load); returns the CLI's output (the
    background session id and the attach/logs/stop lines)."""
    p=subprocess.run(argv,env=env,cwd=str(cwd) if cwd else None,capture_output=True,text=True,timeout=120)
    if p.returncode: raise ValueError('launch failed: '+(p.stderr or p.stdout)[-800:])
    return (p.stdout or '').strip()


def reviewer_for(a, cfg):
    """The reviewer session id of a request: --reviewer, else the environment default (owner boards, ordinary
    posts; `<project>` expands to the project key), else None (the requester stays the reviewer)."""
    r=(getattr(a,'reviewer',None) or '').strip()
    if not r and a.policy=='ordinary' and cfg.get('audience')=='owner':
        r=(os.environ.get(DEFAULT_REVIEWER_ENV) or '').strip().replace('<project>',a.project or '')
    if not r: return None
    if r==a.session: return None
    if r==a.to_session: raise ValueError('reviewer and assignee sessions must differ')
    return r


def outbox_dir(root):
    """Where an attempted post is kept for `retry`: never inside a tracked tree."""
    root=Path(root)
    if not bc.subdir(root) and (root/'.local').is_dir(): return root/'.local/outbox'  # a whole-repo board with its ignored .local/
    common=Path(run(root,'rev-parse','--path-format=absolute','--git-common-dir').stdout.decode().strip())
    return common/'board-outbox'/(bc.subdir(root).replace('/','_') or 'root')


def cmd_boards(a):
    rows=bc.discover(a.workspace)
    if a.json:
        print(json.dumps([{'name':b['name'],'root':str(b['root']),'locked':b['locked'],'error':b['error'],
                           **({k:b['config'].get(k) for k in ('audience','encryption','branch','sources')} if b['config'] else {})}
                          for b in rows],ensure_ascii=False,indent=2)); return
    for b in rows:
        c=b['config'] or {}
        state='🔒 locked' if b['locked'] else ('🔴 '+b['error']) if b['error'] else f"{c['audience']} / encryption {c['encryption']}"
        src=f" / sources {','.join(c['sources'])}" if c.get('sources') else ''
        print(f"{b['name']}  {str(b['root']).replace(str(Path.home()),'~')}  [{state}{src}]")
    if not rows: print(f'no board under {a.workspace or bc.workspace()} (board.json in a checkout or its board/ directory)')


def cmd_init(a, ap):
    if not a.root: ap.error('init needs --root <new board directory> (for a shared project: <project>/board)')
    if a.audience not in bc.AUDIENCES: ap.error('init needs --audience owner|collaborators')
    if a.encryption not in bc.ENCRYPTIONS: ap.error('init needs --encryption none|git-crypt (none = the repository\'s private membership is the only boundary)')
    sources=[s for s in (a.sources or '').split(',') if s]
    root=Path(os.path.expanduser(str(a.root))).absolute()
    readable=[s for s in a.readable.split(',') if s] if a.readable is not None else None
    files=bc.scaffold(root,audience=a.audience,encryption=a.encryption,sources=sources,branch=a.branch,name=a.name,readable=readable)
    top=bc.toplevel(root)
    print('\n'.join(f'wrote {f}' for f in files))
    if top:
        rel=' '.join(str(Path(os.path.realpath(f)).relative_to(top)) for f in files)
        print(f'→ commit them in {top}: git -C {top} add {rel} && git -C {top} commit -m "Add board" -- {rel} && git -C {top} push')
        if a.audience=='collaborators':
            here=Path(__file__).resolve().parent.parent
            url=subprocess.run(['git','-C',str(here),'remote','get-url','origin'],capture_output=True,text=True).stdout.strip()
            if url.startswith('git@github.com:'): url='https://github.com/'+url[len('git@github.com:'):]
            url=(url[:-4] if url.endswith('.git') else url) or '<https URL of this engine>'
            print(f"→ collaborators need this engine next to their checkout; let the project clone and update it at session start "
                  f"(claude-config conventions/shared-repo.md#sibling-repo-auto-clone): python3 <claude-config>/scripts/install-collaborator-check.py "
                  f"install {top} --item 'repo {here.name} {url} AI_COLLABORATION_DIR -- the board engine'")
    else:
        print('→ the directory is not in a Git repository yet: create or clone the repository whose members are this board\'s readers')


def inbox_show(a, root, *, board_name=None, collect=None):
    """inbox / show for one board. `collect` (a list) gathers rows across boards instead of printing."""
    with snapshot(root) if a.sync else contextlib.nullcontext(root) as root:
        events=read(root); all_threads=view.derive(events,view.now_utc())
        if any(issue.unscoped for issue in events.invalid):
            raise ValueError('unscoped invalid history: inbox/request state cannot be determined')
        me={'agent':a.agent,'session_id':a.session}
        threads={k:v for k,v in all_threads.items() if same_session((v.get('workflow') or {}).get('waiting_on'),me) or (v.get('workflow') or {}).get('errors')
                 or (a.include_closed and v['closed'] and v.get('workflow') and view.participated(v,me))}
        for p, why in view.history_warnings(events):
            print(f'ℹ️ history {p.name}: {why}', file=sys.stderr if a.json else sys.stdout)
        tag=(lambda row: dict(row,board=board_name)) if board_name else (lambda row: row)
        if a.command == 'show':
            found=[(pk,tid,t) for (pk,tid),t in all_threads.items()
                   if (t.get('workflow') or {}).get('request_id') == a.request]
            if collect is not None:
                if len(found)==1: collect.append(tag(view.workflow_row(*found[0],reader=me)))
                return
            if len(found) != 1: raise ValueError('request not found or ambiguous: '+a.request)
            pk,tid,t=found[0]; w=t['workflow']
            if a.json:
                print(json.dumps(view.workflow_row(pk,tid,t,reader=me),ensure_ascii=False,indent=2))
            else:
                print(f"{pk}/{tid} [{w['label']}] request={w['request_id']}")
                print(w.get('title') or '')
                print('\n'.join(view.handoff_lines(w)))
                for err in w.get('errors',[]): print('🔴 '+err)
                print(w.get('next_action') or 'この依頼は終了しています。')
            return
        if a.json:
            rows=[tag(view.workflow_row(pk,tid,t,reader=me)) for (pk,tid),t in sorted(threads.items())]
            if collect is not None: collect.extend(rows); return
            print(json.dumps(rows,ensure_ascii=False,indent=2)); return
        if board_name: print(f'== board {board_name}')
        print(view.render(threads,events.invalid,surface=True,project=None,now=view.now_utc(),locked=False,board=board_name)
            or 'このセッション宛ての対応待ちはありません。')
        if a.include_closed:
            for (pk,tid),t in sorted(threads.items()):
                if t['closed']:
                    print(f"✓ {pk}/{tid} [{t['workflow']['label']}] (対応不要)")
                    print('\n'.join(view.handoff_lines(t['workflow'])))
        # Progress of requests this session filed or is assigned to but that are waiting on someone else:
        # not actionable, but the requester wants to see claims/submissions without reading history.
        mine=[]
        for (pk,tid),t in sorted(all_threads.items()):
            w=t.get('workflow') or {}
            if not w or same_session(w.get('waiting_on'),me) or w.get('status') in {'accepted','abandoned'}: continue
            if any(same_session(w.get(k),me) for k in ('requester','assignee','reviewer')):
                mine.append(f"⏳ {pk}/{tid} [{w.get('label')}] waiting on {address_label(w.get('waiting_on'))} — {w.get('title') or ''}")
        if mine: print('自分が関与する進行中 (対応は相手側):'); print('\n'.join(mine))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=sorted(KINDS|{'inbox','show','retry','sessions','watch','touch','untouch','touching','boards','init','launch'}))
    ap.add_argument('--root',type=Path,help='the board directory (holds board.json and events/)')
    ap.add_argument('--board',help='a board in the workspace by name (`boards` lists them)')
    ap.add_argument('--all-boards',action='store_true',help='inbox / show: every unlocked board in the workspace')
    ap.add_argument('--workspace',type=Path,help='boards / --all-boards: the directory holding the checkouts (default: AGENT_BOARD_WORKSPACE, else the parent of the engine checkout)')
    ap.add_argument('--audience',help='init: owner | collaborators'); ap.add_argument('--encryption',help='init: none | git-crypt')
    ap.add_argument('--sources',help='init: comma-separated project keys whose collaborators read the board'); ap.add_argument('--branch',default='main',help='init: the branch posts go to')
    ap.add_argument('--name',help='init: board name (default: the checkout, or the project for <project>/board)')
    ap.add_argument('--readable',help='init: comma-separated public checkouts the readers can see anyway (default for a collaborators board: this engine\'s checkout)')
    ap.add_argument('--agent',choices=['claude','codex','human','other'])
    ap.add_argument('--session',help='stable task/session ID from the calling app; keep across compaction')
    ap.add_argument('--session-name',help='human-readable session label')
    ap.add_argument('--instance',help='optional host/surface metadata; not routing identity')
    ap.add_argument('--source',type=Path)
    ap.add_argument('--policy',choices=['ordinary','encrypted-metadata-only','no-post'])
    ap.add_argument('--project'); ap.add_argument('--repo'); ap.add_argument('--thread',help='thread id; today:<slug> = <local yyyy-mm-dd>-<slug>')
    ap.add_argument('--request'); ap.add_argument('--reply-to'); ap.add_argument('--event-id')
    ap.add_argument('--to',choices=['claude','codex','human','other'])
    ap.add_argument('--to-session'); ap.add_argument('--role',choices=['assignee','reviewer'])
    ap.add_argument('--expect-model',help='request/handover: refuse to post when the addressed session\'s actual model (its transcript) is known and does not match this tier (fable/opus) or model-id substring')
    ap.add_argument('--effort',choices=EFFORTS,help=f'request to a role: the effort its worker starts on, in the launch record, the start_session arguments, the CLI line, the hand-off text and the title (default: env {LAUNCH_EFFORT_ENV}, else the requester\'s CLAUDE_EFFORT); request/handover to a live session: report when its known effort differs')
    ap.add_argument('--reason',help='request to a role / launch --request for a Claude role: why its worker needs the top tier or max'
                    ' effort (what it must derive or judge); kept in the launch record and the hand-off line. The desktop launch'
                    ' check asks for it on machines that turn the premium gate on (claude-config multi-session-coordination.md#premium-launch-reason)')
    ap.add_argument('--effort-quote',help='request to a role / launch --request for a Claude role: the board owner\'s own words naming'
                    ' an effort below the board\'s launch_effort_floor (board.json), verbatim; without them such an effort is refused.'
                    ' Kept in the launch record')
    ap.add_argument('--model-quote',help='request to a role / launch --request for a Claude role: the board owner\'s own words naming'
                    ' a model whose tier the board\'s launch_model_allow (board.json) does not list, verbatim; without them such a model is'
                    ' refused. Kept in the launch record')
    ap.add_argument('--summary'); ap.add_argument('--acceptance')
    ap.add_argument('--deliverable',action='append',default=[]); ap.add_argument('--reference',action='append',default=[])
    ap.add_argument('--review-target',action='append',default=[],help='request: a file the receiver reviews blind; refused '
                    'unless it is a referee copy (no comment text, scripts/check-review-target.py). Added to the references')
    ap.add_argument('--not-blind',action='store_true',help='request: reads like a review, but the receiver may read the '
                    'repository and its records (claude-config multi-session-coordination.md#review-handoff)')
    ap.add_argument('--lease-hours',type=float,default=12)
    ap.add_argument('--sync',action='store_true',help='read latest remote inbox in an isolated checkout')
    ap.add_argument('--preview',action='store_true',help='validate and show the proposed event without posting')
    ap.add_argument('--json',action='store_true',help='inbox: waiting rows; show: one request object; boards: the list; warnings go to stderr')
    ap.add_argument('--include-closed',action='store_true',help='inbox: also show completed requests involving this exact session (not actionable)')
    ap.add_argument('--interval',type=float,default=30,help='watch: seconds between remote checks (default transport: one ls-remote round trip, a read only when the branch moved; clone transport: a full read)')
    ap.add_argument('--launch',action='store_true',help='request to a role: start the worker now with the printed CLI command (background session; the id is printed)')
    ap.add_argument('--no-launch',action='store_true',help=f'request to a role: only print the command even when {LAUNCH_DEFAULT_ENV}=1 (that default applies to owner boards only)')
    ap.add_argument('--surface',choices=['background','desktop','agent'],help=f'request to a role: desktop = print the desktop app\'s start_session arguments (the worker is listed in the app); background = the CLI line (default; env {LAUNCH_SURFACE_ENV}); agent = the requester runs it as its own subagent (Agent tool, not listed in the app: work the owner does not watch)')
    ap.add_argument('--title',help='request to a role (--surface desktop, or a Codex role): the worker\'s title in the app\'s list (default: the summary\'s first clause); the model is added at the end')
    ap.add_argument('--launch-host',help='request to a Codex role: the machine that starts the worker (default: this one). Written in the request; another machine\'s session starts it with `launch --request <id>`, this one does not')
    ap.add_argument('--launch-cwd',help='request to a Codex role: the worker\'s working directory (default: the workspace). A sealed blind-review judge is not a board worker: the worker starts it with codex-app-launch.py start --sealed (cold-eyes-isolation.md#board-blind-variant)')
    ap.add_argument('--headless-reason',help='request to a Codex role with --surface background: why a headless `codex exec` (listed nowhere in the Codex app) instead of the app-visible launch')
    ap.add_argument('--detach',action='store_true',help='request / launch to a role with --surface desktop: detach the worker from the requester once its model is right (default: it stays the requester\'s child, listed under it)')
    ap.add_argument('--worktree',action='store_true',help='request / launch to a Claude role: the worker works in a git worktree of its own'
                    ' (when it shares files with a parallel writer); merging its branch into main needs the owner\'s OK. Default: the'
                    ' repository\'s own working tree on main (a background CLI worker is started with worktree.bgIsolation none)')
    ap.add_argument('--nested',action='store_true',help='request / launch to a role with --surface desktop: the default (the worker stays the requester\'s child); accepted so older command lines still run')
    ap.add_argument('--model-ok',action='store_true',help='claim: the requester or the owner accepted the model this session runs although the request was launched for another')
    ap.add_argument('--subagent-ok',action='store_true',help='claim: the requester or the owner accepted a subagent (Agent tool) for a request launched for a desktop window')
    ap.add_argument('--reviewer',help='request: the session that receives the submission (default: the requester; env '
                    f'{DEFAULT_REVIEWER_ENV} with <project> on an owner board). A role id outlives this session; posted as a reviewer handover right after the request')
    ap.add_argument('--max-minutes',type=float,default=240,help='watch: give up after this long (exit 3)')
    ap.add_argument('--since',help='watch: treat events after this event id as new (resume after a restart)')
    ap.add_argument('--quiet-kind',action='append',default=[],choices=sorted(KINDS),
                    help='watch: event kind that does not end the watch (repeatable, e.g. note); shown with the next waking event')
    ap.add_argument('--path',action='append',default=[],help='touch / untouch / touching: a file or directory below the workspace (repeatable; relative = from the workspace)')
    ap.add_argument('--hours',type=float,default=12,help='touching: declarations older than this no longer hold a path (a session that died)')
    ap.add_argument('--wait',action='store_true',help='touching --path: return only when no earlier session holds the paths (background)')
    a=ap.parse_args()
    if a.command=='boards': return cmd_boards(a)
    if a.command=='init': return cmd_init(a,ap)
    if not a.agent: ap.error('--agent is required')
    if not a.session and a.agent=='codex': a.session=os.environ.get('CODEX_THREAD_ID')
    if not a.session and a.agent=='claude': a.session=os.environ.get('CLAUDE_CODE_SESSION_ID')  # native UUID the harness exports (desktop + CLI)
    if not a.session and a.command!='sessions': ap.error('--session requires the actual native session ID')
    if a.thread and a.thread.startswith('today:'): a.thread=f"{view.dt.date.today():%Y-%m-%d}-{a.thread[6:]}"  # local date, any shell
    if a.include_closed and a.command != 'inbox': ap.error('--include-closed is for inbox only')
    if a.effort and a.command not in {'request','handover','launch'}: ap.error('--effort is for request, handover and launch only')
    if a.detach and a.nested: ap.error('--detach and --nested contradict (nested is the default)')
    if a.reason and a.command not in {'request','launch'}: ap.error('--reason is for request and launch only')
    if a.effort_quote and a.command not in {'request','launch'}: ap.error('--effort-quote is for request and launch only')
    if a.model_quote and a.command not in {'request','launch'}: ap.error('--model-quote is for request and launch only')
    if a.command == 'show' and not a.request: ap.error('show requires --request')
    if a.all_boards:
        if a.command not in {'inbox','show'}: ap.error('--all-boards is for inbox / show')
        found=bc.discover(a.workspace)
        for b in found:
            if not b['config']: print(f"⚠️ board {b['name']} not read: {'locked' if b['locked'] else b['error']}",file=sys.stderr)
        rows=[] if (a.json or a.command=='show') else None
        for b in (b for b in found if b['config']): inbox_show(a,b['root'],board_name=b['name'],collect=rows)
        if a.command=='show':
            if len(rows)!=1: raise ValueError('request not found or ambiguous across boards: '+a.request)
            if a.json: print(json.dumps(rows[0],ensure_ascii=False,indent=2))
            else: print(f"board {rows[0]['board']}: rerun with --board {rows[0]['board']} for the full view")
        elif a.json: print(json.dumps(rows,ensure_ascii=False,indent=2))
        return
    if is_codex_role_request(a):
        # A Codex role's worker is started so the owner sees it in the Codex app (CONTRACT.md#codex-worker-launch);
        # the headless `codex exec` is listed nowhere there and is chosen only with a reason.
        if a.surface in ('desktop','agent'):
            ap.error('--surface desktop / agent は Claude の worker 用。 Codex の役割は既定 (アプリに出る起動) か --surface background --headless-reason')
        if a.surface=='background' and not (a.headless_reason or '').strip():
            ap.error("headless の codex exec は Codex アプリのどこにも出ない = 本人か依頼元が選んだときだけ: --headless-reason '<理由>' を付ける")
    elif any((a.launch_host,a.launch_cwd,a.headless_reason)):
        ap.error('--launch-host / --launch-cwd / --headless-reason は Codex の役割 id 宛ての request だけ')
    a.root=bc.resolve(a.root,a.board)
    ws=touch_base(a.root)
    if a.command=='launch':
        cmd_launch(a); return
    if a.command == 'touching':
        # Read-only. With --path the verdict covers the whole board (a file is one file whichever thread declared it);
        # --project / --thread narrow only the listing. Exit 2 = an earlier session holds a path, 3 = --wait timed out.
        me=(a.agent,a.session); labels={norm_touch(x,ws):x for x in a.path}; paths=list(labels); deadline=time.time()+a.max_minutes*60
        while True:
            with snapshot(a.root) if (a.sync or a.wait) else contextlib.nullcontext(a.root) as root:
                events=read(root)
            if paths:
                lines,blocked=touch_verdict(touch_state(events,view.now_utc(),a.hours),me,paths,labels)
                if blocked and a.wait:
                    if time.time()+a.interval<=deadline: time.sleep(a.interval); continue
                    print('\n'.join(lines)); print('touching: 時間切れ (先の session がまだ持っている)'); sys.exit(3)
                print('\n'.join(lines)); sys.exit(2 if blocked else 0)
            state=touch_state(events,view.now_utc(),a.hours,project=a.project,thread=a.thread)
            for (agent,sid),st in sorted(state.items(),key=lambda kv: kv[1]['last']):
                print(f"{st['name'] or '—'} ({agent}/{sid[:8]}) 最後の宣言 {st['last'][:16]}Z{' ← この session' if (agent,sid)==me else ''}")
                if st.get('summary'): print(f"    「{st['summary'][:200]}」")
                for p,(since,thr) in sorted(st['paths'].items()): print(f'    {p}  ({since[:16]}Z から、 {thr})')
            if not state: print(f'いま file を宣言している session はありません (過去 {a.hours:g} 時間)。')
            if a.thread:
                # Everything the thread ever declared or cited, released or not: where a closing sweep finds the day's work.
                notes=[e for e in events if e.get('kind')=='note' and e.get('thread_id')==a.thread and e.get('touches')
                       and (not a.project or (e.get('project') or {}).get('key')==a.project)]
                repos=sorted({p.split('/')[0] for e in notes for p in e['touches'] if p!=NONE_TOUCH and not p.startswith('h:')})
                refs=list(dict.fromkeys(r for e in notes for r in e.get('references') or []))
                if repos: print('この thread で宣言された repo: '+', '.join(repos))
                if refs: print('この thread の touch / untouch が挙げた参照: '+', '.join(refs))
            if not a.sync: print('(手元の写し。 最新は --sync)')
            return
    if a.command == 'watch':
        # A post is a record, not a push: a session working on a request sees the other side's note,
        # answer or review only when it reads again. Run this in the background after claim/request
        # (Claude: Bash run_in_background) so the session is woken when the other side writes to the thread.
        if not a.request: ap.error('watch requires --request')
        me={'agent':a.agent,'session_id':a.session}; deadline=time.time()+a.max_minutes*60; key=None; seen=None
        quiet=set(a.quiet_kind); pending=[]
        # Default transport: between reads, the remote's branch head is asked with `ls-remote` (one round trip, no
        # transfer) every --interval seconds, and the local `last-push` note of this machine's posters every
        # NOTIFY_POLL_S; the thread is read again only when either moved. The clone transport reads every interval.
        repo=bt.Repo(a.root) if bt.transport()!='clone' else None; last_remote=last_note=None; next_remote=0.0
        while True:
            try:
                if repo is not None and key is not None:
                    # the remote is asked once per --interval (one SSH round trip); the local note every NOTIFY_POLL_S
                    note=repo.notified(); remote=last_remote
                    if time.time()>=next_remote: remote=repo.ls_remote(); next_remote=time.time()+a.interval
                    if (remote,note)==(last_remote,last_note):
                        if time.time()+NOTIFY_POLL_S>deadline: print('watch: 新しい書き込みなし (時間切れ)'); sys.exit(3)
                        time.sleep(NOTIFY_POLL_S); continue
                    last_remote,last_note=remote,note
                with snapshot(a.root,fresh=True) as root:
                    events=read(root)
                    if key is None:
                        found=[k for k,t in view.derive(events,view.now_utc()).items()
                               if (t.get('workflow') or {}).get('request_id')==a.request]
                        if len(found)!=1: raise ValueError('request not found or ambiguous: '+a.request)
                        key=found[0]
                        if repo is not None: last_remote,last_note=repo.remote_sha(),repo.notified(); next_remote=time.time()+a.interval
                    thread=[e for e in events if (e['project']['key'],e['thread_id'])==key]
            except Exception as ex:  # noqa: BLE001  only sync failures are retried, see transient_sync_error
                if not transient_sync_error(ex): raise
                print('watch: 同期に失敗 ('+(str(ex).splitlines() or [type(ex).__name__])[0][:200]+')、 '
                      +str(int(a.interval))+' 秒後にやり直す',file=sys.stderr)
                if time.time()+a.interval>deadline: print('watch: 新しい書き込みなし (時間切れ)'); sys.exit(3)
                time.sleep(a.interval); continue
            ids=[e['event_id'] for e in thread]
            if seen is None:
                if a.since and a.since not in ids: raise ValueError('--since event not in this thread: '+a.since)
                seen=set(ids[:ids.index(a.since)+1]) if a.since else set(ids)
            new=watch_wake(thread,seen,me,quiet,pending)
            if new:
                print('\n'.join(watch_report(key,new,thread,me,root=a.root,agent=a.agent,session=a.session,
                                              request=a.request,quiet=quiet)))
                return
            seen.update(ids)
            if time.time()+a.interval>deadline: print('watch: 新しい書き込みなし (時間切れ)'); sys.exit(3)
            if repo is None: time.sleep(a.interval); continue
            next_remote=time.time()+a.interval   # just read: the next remote check is a full interval away; the note is polled meanwhile
    if a.command=='sessions':
        with snapshot(a.root) if a.sync else contextlib.nullcontext(a.root) as root:
            events=read(root)
            for p, why in events.invalid:
                print(f'🔴 invalid history (address list may be incomplete): {p.name}: {why}')
            for p, why in view.history_warnings(events):
                print(f'⚠️ history {p.name}: {why}')
            # Directory derived from history: who posted as whom, what they called themselves, where they were
            # last seen, and what is waiting on them. Roles (resident-*/role-*) are stable addresses a human
            # assigns to a session; native ids are ephemeral per session. Never a liveness registry.
            # A role id is one address whichever vendor acts under it (CONTRACT.md#role-any-agent): one row, its agents joined.
            seen={}; agents={}
            def key(agent, sid):
                if is_role(sid): agents.setdefault(sid,set()).add(agent); return ('*',sid)
                return (agent,sid)
            for e in events:
                act=e.get('actor',{})
                if act.get('session_id'):
                    k=key(act['agent'],act['session_id']); r=seen.setdefault(k,{'name':None,'instance':None,'last':None,'n':0,'projects':set()})
                    r['n']+=1; r['last']=max(r['last'] or '',e.get('created_at','')); r['projects'].add((e.get('project') or {}).get('key'))
                    if act.get('task') and act.get('task')!='workflow' and len(act['task'])<=80: r['name']=act['task']  # early writers stored the summary here
                    if act.get('instance'): r['instance']=act['instance']
                for x in [e.get('assignee',{}),e.get('target',{})]:
                    if isinstance(x,dict) and x.get('session_id'): seen.setdefault(key(x['agent'],x['session_id']),{'name':None,'instance':None,'last':None,'n':0,'projects':set()})
            threads=view.derive(events,view.now_utc()); waiting={}
            for (pk,tid),t in threads.items():
                w=(t.get('workflow') or {}).get('waiting_on')
                if w: waiting.setdefault(key(w['agent'],w['session_id']),[]).append(f'{pk}/{tid}')
            for k,r in sorted(seen.items()):
                agent,sid=k; kind='role' if is_role(sid) else 'native'
                if agent=='*': agent='|'.join(sorted(a for a in agents.get(sid,()) if a))
                print(f"{agent} / {sid}  [{kind}] name={r['name'] or '—'} instance={r['instance'] or '—'} last={(r['last'] or '—')[:16]} events={r['n']} projects={','.join(sorted(p for p in r['projects'] if p)) or '—'} waiting_on={len(waiting.get(k,[]))}")
                for th in waiting.get(k,[]): print(f'    ↳ waiting: {th}')
            print('Known session addresses from history; not a live-process registry. A session is reachable only if its id is known here or handed to you by the owner.')
        return
    if a.command in {'inbox', 'show'}:
        inbox_show(a,a.root); return
    # ---- posting
    cfg=bc.load(a.root)
    if a.command=='request' and a.to=='claude' and (a.to_session or '').startswith('role-'):
        check_effort_floor(cfg,launch_effort(a.effort),a.effort_quote)   # before the board is fetched or anything is written
        check_model_allow(cfg,launch_settings(a.expect_model,a.session,a.effort)[0],a.model_quote)
    if cfg['audience']=='collaborators':
        # A board for one project's collaborators: its project and checkout are the defaults, and the only choice.
        if not a.policy: a.policy='ordinary'
        if a.policy!='ordinary': bc.check_post(cfg,a.root,project=None,policy=a.policy)  # refuse before building anything
        if not a.project and len(cfg['sources'])==1 and (a.command in {'request','touch','untouch'} or (a.command=='note' and not a.request)):
            a.project=cfg['sources'][0]
        if not a.source:
            top=bc.toplevel(a.root); key=a.project or (cfg['sources'][0] if len(cfg['sources'])==1 else None)
            if top and key and top.name==key: a.source=top
    if not a.source and a.project and a.project!='restricted': a.source=ws/a.project  # project key = checkout basename in the workspace
    if not a.source or not a.policy:
        # 足りない方だけを挙げる (= 両方を挙げると、 自動で決まる --source に誤った値を渡して詰まる)
        missing=[f for f,v in (('--source',a.source),('--policy',a.policy)) if not v]
        ap.error('posting requires '+' and '.join(missing))
    touch_cmd=a.command if a.command in {'touch','untouch'} else None
    if a.command=='handover':
        # CONTRACT: a handover replies to the request itself, so either flag names it (measured: --reply-to alone was refused
        # with "--request must identify an existing request", and --request alone with "missing reply_to"; a submission id in
        # --reply-to was refused only as "handover must name the request" = the reviewer had to guess the fix each time)
        if not a.request and a.reply_to: a.request=a.reply_to
        elif a.request and not a.reply_to: a.reply_to=a.request
        elif a.request and a.reply_to and a.request!=a.reply_to:
            ap.error(f'handover replies to the request itself: --reply-to must be the request id {a.request} '
                     f'(or leave it out), not {a.reply_to}')
    if touch_cmd and (a.policy!='ordinary' or a.request or not a.thread or not a.project):
        ap.error(f'{touch_cmd} needs --policy ordinary, --project and --thread (no --request): paths are metadata, restricted posts carry none')
    if a.command=='touch' and not a.path: ap.error('touch needs --path')
    source_gate(a.source,a.policy) # before constructing an event or temporary files
    outbox=outbox_dir(a.root)
    if a.command=='retry':
        if not a.event_id or not re.fullmatch(r'[a-zA-Z0-9-]+',a.event_id): ap.error('retry requires --event-id')
        saved=outbox/(a.event_id+'.json')
        ev=json.loads(saved.read_text())
        if ev['source_policy']!=a.policy or ev['actor']['agent']!=a.agent or ev['actor']['session_id']!=a.session:
            raise ValueError('retry identity/policy differs from saved event')
        print('posted '+post(a.root,ev)); return
    labels={}
    for attempt in range(2):
      # A post's own read is optimistic (no fetch when this machine fetched or pushed within OPTIMISTIC_S); an event
      # that cannot be built against that read (a request not there yet) is rebuilt after a fresh fetch.
      with snapshot(a.root,optimistic=attempt==0,fresh=attempt>0) as dest:
        events=read(dest)
        if touch_cmd:
            # The note restates the session's whole set in this thread (touch adds, untouch removes; nothing left = `(none)`).
            me=(a.agent,a.session); labels={norm_touch(x,ws):x for x in a.path}; want=list(labels)
            cur=list(touch_state(events,view.now_utc(),a.hours,project=a.project,thread=a.thread).get(me,{'paths':{}})['paths'])
            if touch_cmd=='touch':
                new=cur+[p for p in want if p not in cur]; released=[]
                a.summary=a.summary or ('触る: '+', '.join(want))[:1000]
            else:
                new=[p for p in cur if want and not any(touch_overlaps(p,w) for w in want)]; released=[p for p in cur if p not in new]
                a.summary=a.summary or ('手放す: '+(', '.join(released) or '(なし)'))[:1000]
            a.touch=new or [NONE_TOUCH]; a.command='note'
        try:
            ev=event_from(a,events)
            view.assert_writable(events, ev['project']['key'], ev['thread_id'], ev['event_id'])
        except ValueError:
            if attempt==0 and _REUSED: continue
            raise
      break
    # What the board's readers may see is checked before anything leaves this machine (owner boards pass).
    bc.check_post(cfg,a.root,project=ev['project']['key'],policy=a.policy,
        texts=[('--summary',ev.get('summary')),('--acceptance',ev.get('acceptance')),('--session-name',a.session_name)],
        refs=[('--reference',r) for r in ev.get('references') or []]+[('--deliverable',d) for d in ev.get('deliverables') or []],
        touches=[(t,labels.get(t,t)) for t in ev.get('touches') or [] if t!=NONE_TOUCH])
    if cfg['audience']=='owner' and a.policy=='ordinary':
        for b in bc.collaborator_boards_for(ev['project']['key'],ws):
            print(f"ℹ️ {ev['project']['key']} には共同研究者も読む掲示板がある ({str(b['root']).replace(str(Path.home()),'~')})。"
                  f" 共同研究者に見せる話なら --board {b['name']} で投稿する (この投稿は owner だけが読む)",file=sys.stderr)
    if a.command in {'request','handover'}:
        # The addressed session's model can only be matched to the work before sending (switching later costs
        # the context and cache); a title tag is a recommendation, so read the transcript instead.
        note=target_model_note(a.to_session,a.expect_model,a.to,a.effort)
        if note: print(note)
    claim_model_check(a)   # a worker on another model than its request was launched for does not take the work (measured: the app started one on the requester's model)
    if a.preview:
        from board_schema import errors
        probs=errors(ev,json.loads(SCHEMA_PATH.read_text()))
        same=[e for e in events if e['project']['key']==ev['project']['key'] and e['thread_id']==ev['thread_id']]
        probs+=reduce_workflow(same+[ev],view.now_utc())['errors']
        if probs: raise ValueError('; '.join(probs))
        print(json.dumps(ev,ensure_ascii=False,indent=2))
        announce_launch(a,ev,cfg['audience'])   # shown, not run: the requester sees the command it will get
        return
    from board_schema import errors
    probs=errors(ev,json.loads(SCHEMA_PATH.read_text()))
    if probs: raise ValueError('; '.join(probs))
    same=[e for e in events if e['project']['key']==ev['project']['key'] and e['thread_id']==ev['thread_id']]
    w_before=reduce_workflow(same,view.now_utc()) if a.request else None
    # A transition the reducer refuses now is refused here, before its id is printed and saved for `retry`: it is not
    # a network outcome (measured: an answer aimed at an already answered blocker printed its event id, then ERROR).
    bad=[x for x in reduce_workflow(same+[ev],view.now_utc())['errors'] if x.startswith(ev['event_id']+':')]
    if bad: raise ValueError('; '.join(bad))
    outbox.mkdir(parents=True,exist_ok=True,mode=0o700)
    saved=outbox/(ev['event_id']+'.json')
    with saved.open('x',encoding='utf-8') as f: json.dump(ev,f,ensure_ascii=False,indent=2)
    saved.chmod(0o600)
    print('event_id='+ev['event_id'],flush=True) # retain for ambiguous network outcomes
    landed=[]
    print('posted '+post(a.root,ev,landed=landed))
    print('Local view is a snapshot; use inbox --sync to read the latest remote state.')
    state=request_state_line(reduce_workflow(landed or same+[ev],view.now_utc()))
    if state: print(state)
    if touch_cmd:
        # Read again after the post: two sessions that declared one file within seconds learn here who came first.
        with snapshot(a.root) as root: events=read(root)
        me=(a.agent,a.session); state=touch_state(events,view.now_utc(),a.hours)
        if touch_cmd=='touch':
            lines,blocked=touch_verdict(state,me,[p for p in ev['touches'] if p!=NONE_TOUCH],labels)
            print('\n'.join(lines))
            if blocked: sys.exit(2)
            return
        for p in released:
            o=touch_owner(state,p)
            if o and o['who']!=me:
                print(f"→ {p} の次の持ち主 = {o['name'] or '—'} ({o['who'][0]}/{o['who'][1][:8]}): 生きていれば SendMessage で「手放した、 読み直してから書いてよい」 と 1 行")
        if not [w for w in touch_state(events,view.now_utc(),a.hours,project=a.project,thread=a.thread) if w!=me]:
            print(f'この thread ({a.project}/{a.thread}) で file を持つ session は他に居ない = 最後の 1 本。')
        return
    rid = ev['event_id'] if a.command=='request' else a.request
    if a.command=='request':
        reviewer=reviewer_for(a,cfg)
        if reviewer:
            # The receipt right moves to a standing id now, as one more event (old readers understand a handover):
            # the requesting window may close before the submission arrives (measured: most receipts after a
            # window closed needed a hand-written handover first).
            import copy
            h=copy.copy(a); h.command='handover'; h.request=ev['event_id']; h.reply_to=ev['event_id']; h.to=a.agent; h.to_session=reviewer
            h.role='reviewer'; h.event_id=None; h.touch=None; h.deliverable=[]; h.reference=[]; h.acceptance=None
            h.summary=None if a.policy=='encrypted-metadata-only' else f'検収役 = {reviewer} (依頼元 {a.session[:8]} の window が閉じても受領できる id。 依頼元が生きていれば同じ id で受領する)'
            hev=event_from(h,events+[ev])
            probs=errors(hev,json.loads(SCHEMA_PATH.read_text()))+[x for x in reduce_workflow(same+[ev,hev],view.now_utc())['errors'] if x.startswith(hev['event_id']+':')]
            if probs: raise ValueError('reviewer handover: '+'; '.join(probs))
            print('posted '+post(a.root,hev)+f' (検収役 = {a.agent}/{reviewer}: 提出は inbox --session {reviewer} に載る。 受領は --session {reviewer} --session-name \'<native id 8 chars> (<model>)\' で accept / revise)')
        plan=announce_launch(a,ev,cfg['audience'])
        if plan and launch_now(a,cfg['audience']):
            if getattr(a,'_codex_launch',False): run_codex_launch(a,ev['event_id'],*plan)
            else: print('→ 起動した: '+launch(*plan,cwd=bc.workspace(a.root)).replace('\n','\n  '))
        elif plan and cfg['audience']!='owner' and os.environ.get(LAUNCH_DEFAULT_ENV,'').strip()=='1' and not a.no_launch:
            print(f'→ 起動していない: 共同研究者も読む掲示板では {LAUNCH_DEFAULT_ENV}=1 は効かない。'
                  ' 役割が依頼元の側なら上の 1 行を実行する (次からは --launch)')
    if rid and a.command in {'request','claim','submit','blocker','revise','update'}:
        # A post is a record, not a push: the other side's reply reaches this session only if it reads again.
        if a.agent=='codex':
            # A Codex tool call is synchronous: a foreground watch blocks the turn and wakes nothing.
            print("→ Codex は background の watch で起こされない。 相手が同じ機械なら、 相手の投稿の出力が出す"
                  " codex queue の 1 行でこの thread に新しい turn が届く。 別の機械なら次の inbox --sync で読む"
                  " (desktop ならこの task に heartbeat を付けて inbox を読み直す。 --sync は承認の画面を経るので、 claim・返事・投稿の直前だけ)")
        else:
            print(f"→ 相手の書き込みで起こされるように、 background で見張る (Claude = Bash の run_in_background):"
                  f" python3 {Path(__file__).resolve()} watch --root {a.root} --agent {a.agent} --session {a.session} --request {rid}")
    if a.command in {'request','claim','submit','blocker','revise','update','handover','release','abandoned'} or (a.command=='note' and a.request):
        note=counterpart_note((a.agent,a.session),ev,events)
        if note: print(note)
    hints=kind_hints(ev,w_before,(a.agent,a.session))
    if hints:
        # last, on stderr: a caller that pipes stdout through `tail` still sees it, and `2>&1 | tail` keeps it
        sys.stdout.flush()
        print('\n'.join(hints),file=sys.stderr)

if __name__=='__main__':
    try: main()
    except (ValueError,OSError,subprocess.SubprocessError) as ex:
        print('ERROR: '+str(ex),file=sys.stderr); sys.exit(1)
