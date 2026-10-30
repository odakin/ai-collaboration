#!/usr/bin/env python3
"""Localhost board viewer. A page is served at once from the last render (the first one from the local checkout),
and a synchronized render is made in the background; the page asks /version and swaps itself in when that is newer.

Read-only, except one opt-in write: with --handoff-dir, a request whose next move is on a role id (its worker is not
there or its lease expired, its submission waits for review, or its question waits for the reviewer) gets a button, and
POST /handoff puts it into that queue as one file per request. The server starts
nothing; whoever the owner wires to the queue (a coordinating session, a runner) opens the worker and moves the file to
<dir>/done/. Without --handoff-dir there is no write endpoint at all (CONTRACT.md#viewer-handoff-queue).
GET /due (read-only, always) lists the same requests as JSON, for a coordinating session that picks them up itself."""
import argparse
import hmac
import importlib.util
import json
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from html import escape
from pathlib import Path
import subprocess
import sys
import board

import board_config as bc
spec=importlib.util.spec_from_file_location('board_html',board.ENGINE/'board-html.py')
html=importlib.util.module_from_spec(spec); spec.loader.exec_module(html)

# A page view starts a background synchronization at most this often; /version?refresh=1 (the page's reload button)
# starts one at once. Measured: the synchronized render (fetch + derive) took 3-10 s per page view when it ran in the
# request, the local one about 1.5 s warm and 8 s cold (the first one after the process starts, so it is done at start);
# the cached page is served in milliseconds.
MIN_REFRESH_S=15
# A handed-off request whose file the consumer moved to done/ shows "started" this long (the worker is opening, or the
# review is under way, and the board has not moved yet); a second hand-off is refused meanwhile, so one click cannot
# open two workers.
STARTED_HOLD_S=3600
HANDOFF_STATES=('requested','stale','submitted','blocked')
RID=re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{5,120}')
CSP="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"


def handoff_waiting(payload):
    """Requests the viewer may hand off: an open workflow request whose next move is on a role id (Claude or Codex) =
    its worker is not there yet (requested) or its lease expired (stale), its submission waits for review (submitted), or
    its question waits for the reviewer (blocked). The same for a native session that has ended on this machine
    (`stranded`, board.session_state). A request someone is working on or has picked up (CONTRACT.md#pickup), or whose
    next move is on a session that may be alive, is not handed off. Keyed by request id."""
    out={}
    for t in payload.get('threads') or []:
        w=t.get('workflow') or {}
        nxt=w.get('waiting_on') or {}
        if t.get('closed') or w.get('status') not in HANDOFF_STATES or not w.get('request_id'): continue
        role=str(nxt.get('session_id','')).startswith('role-')
        # a request addressed to a session that has ended is stuck the same way; restricted threads carry no free text
        stranded=not role and t.get('project')!='restricted' and board.session_state(nxt.get('agent'),nxt.get('session_id'))=='ended'
        if (role or stranded) and not board.live_pickup(t.get('events') or [],w['request_id']):
            out[w['request_id']]={'request_id':w['request_id'],'project':t.get('project'),'thread_id':t.get('thread_id'),
                                  'title':(w.get('title') or '')[:300],'status':w.get('status'),'waiting_on':nxt,
                                  'assignee':w.get('assignee'),'reviewer':w.get('reviewer'),'stranded':stranded}
    return out


def handoff_states(qdir):
    """{request id: 'queued' | 'started'} from the queue directory (started = moved to done/ within STARTED_HOLD_S)."""
    if not qdir: return {}
    out={}
    done=qdir/'done'
    if done.is_dir():
        now=time.time()
        for f in done.glob('*.json'):
            try:
                if now-f.stat().st_mtime<STARTED_HOLD_S: out[f.stem]='started'
            except OSError: pass
    if qdir.is_dir():
        for f in qdir.glob('*.json'): out[f.stem]='queued'
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port',type=int,default=8769)
    ap.add_argument('--root',type=Path,help='the board directory (holds board.json and events/)')
    ap.add_argument('--board',help='a board in the workspace by name')
    ap.add_argument('--local',action='store_true',help='read local checkout instead of synchronizing remote')
    ap.add_argument('--handoff-dir',type=Path,help='turn on the hand-off button: POST /handoff writes <dir>/<request id>.json (nothing else)')
    ap.add_argument('--handoff-label',default='引き受けを頼む',help='the button text')
    ap.add_argument('--handoff-note',default='受付に渡しました',help='the line shown after a hand-off')
    a=ap.parse_args()
    a.root=bc.resolve(a.root,a.board)
    labels=({} if bc.is_locked(a.root) else bc.load(a.root).get('labels',{}))
    shown_root=str(a.root).replace(str(Path.home()),'~')
    qdir=a.handoff_dir.expanduser() if a.handoff_dir else None
    token=secrets.token_urlsafe(24)   # per process; only a page this server rendered carries it
    origins={f'http://127.0.0.1:{a.port}',f'http://localhost:{a.port}'}

    def render(sync):
        if sync and not a.local:
            with board.snapshot(a.root) as root: payload=html.payload_from(root,None)
        else:
            payload=html.payload_from(a.root,None)
        payload.update(root=shown_root,labels=labels)
        waiting=handoff_waiting(payload)
        if qdir: payload['handoff']={'token':token,'label':a.handoff_label,'note':a.handoff_note,'states':handoff_states(qdir),
                                     'stranded':[k for k,v in waiting.items() if v.get('stranded')]}
        return html.build(payload).encode(),{'head':payload.get('head'),'generated_at':payload.get('generated_at')},waiting

    cache={'body':None,'version':{},'waiting':{},'at':0.0,'refreshing':False,'error':None,'synced':False}
    # 'waiting' is computed on every render (not only with --handoff-dir) so GET /due can list it
    lock=threading.Lock()

    def refresh():
        try:
            body,ver,waiting=render(True)
            with lock: cache.update(body=body,version=ver,waiting=waiting,at=time.time(),error=None,synced=True)
        except (ValueError,OSError,subprocess.SubprocessError) as ex:
            with lock: cache['error']=str(ex)[-400:]
        finally:
            with lock: cache['refreshing']=False

    def kick(force=False):
        with lock:
            if cache['refreshing'] or (not force and time.time()-cache['at']<MIN_REFRESH_S): return
            cache['refreshing']=True
        threading.Thread(target=refresh,daemon=True).start()

    warmed=threading.Event()

    def warm():   # 起動したら最初の描画 (手元の checkout) と同期を先に済ませる = 起動後の最初の頁も待たせない
        try:
            body,ver,waiting=render(False)
            with lock:
                if cache['body'] is None: cache.update(body=body,version=ver,waiting=waiting,at=0.0)
        except (ValueError,OSError,subprocess.SubprocessError):
            pass
        finally:
            warmed.set()
        kick(force=True)

    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,body,ctype):
            self.send_response(status)
            self.send_header('Content-Type',ctype)
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',CSP)
            self.end_headers(); self.wfile.write(body)

        def answer(self,status,**obj):
            self.reply(status,json.dumps(obj,ensure_ascii=False).encode(),'application/json; charset=utf-8')

        def do_GET(self):
            # No file serving, arbitrary paths or cross-origin API.
            if self.headers.get('Host') not in {f'127.0.0.1:{a.port}',f'localhost:{a.port}'}:
                self.send_error(403); return
            path,_,query=self.path.split('#')[0].partition('?')
            if path not in {'/','/demo','/version','/due'}:
                self.send_error(404); return
            try:
                if path=='/demo':
                    p=html.demo_payload(); self.reply(200,html.build(p).encode(),'text/html; charset=utf-8'); return
                if path=='/due':   # read-only: the requests whose next move is on a role id, for a coordinating session to pick up itself
                    kick()
                    with lock: v=dict(cache['version'],synced=cache['synced'],due=list(cache['waiting'].values()))
                    self.answer(200,**v); return
                if path=='/version':
                    kick(force=query=='refresh=1')
                    with lock:
                        v=dict(cache['version'],refreshing=cache['refreshing'],synced=cache['synced'],error=cache['error'])
                    if qdir: v['handoffs']=handoff_states(qdir)
                    self.answer(200,**v); return
                warmed.wait(30)
                with lock: body=cache['body']
                if body is None:   # the warm-up failed: the local checkout now, the synchronized one behind it
                    body,ver,waiting=render(False)
                    with lock:
                        if cache['body'] is None: cache.update(body=body,version=ver,waiting=waiting,at=0.0)
                kick()
                self.reply(200,body,'text/html; charset=utf-8')
            except (ValueError,OSError,subprocess.SubprocessError) as ex:
                body=('<h1>掲示板を更新できませんでした</h1><p>未処理がゼロという意味ではありません。再読み込みしてください。</p><pre>'+escape(str(ex))+'</pre>').encode()
                self.reply(503,body,'text/html; charset=utf-8')

        def do_POST(self):
            # The one write (opt-in): queue a hand-off. Same-origin page only = Host and Origin are this server, the
            # body is JSON (a cross-site form cannot send it without a preflight this server never answers) and it
            # carries the token of a page this process rendered. Only a request that still waits for its worker.
            if not qdir or self.path!='/handoff':
                self.send_error(404); return
            if self.headers.get('Host') not in {f'127.0.0.1:{a.port}',f'localhost:{a.port}'} or self.headers.get('Origin') not in origins:
                self.send_error(403); return
            if not (self.headers.get('Content-Type') or '').startswith('application/json'):
                self.send_error(415); return
            try:
                n=int(self.headers.get('Content-Length') or 0)
            except ValueError:
                n=-1
            if not 0<n<=4096:
                self.send_error(400); return
            try:
                data=json.loads(self.rfile.read(n))
            except ValueError:
                self.send_error(400); return
            if not isinstance(data,dict) or not hmac.compare_digest(str(data.get('token','')),token):
                self.answer(403,ok=False,why='この頁は古い (サーバーが起動し直した)。 読み直してから押す'); return
            rid=str(data.get('request_id',''))
            if not RID.fullmatch(rid):
                self.send_error(400); return
            state=handoff_states(qdir).get(rid)
            if state:
                self.answer(200,ok=True,already=state,note=a.handoff_note); return
            with lock: req=cache['waiting'].get(rid)
            if not req:
                self.answer(409,ok=False,why='役割の番で止まっている依頼ではない (誰かが動いているか、 終わった)。 読み直して確かめる'); return
            try:
                qdir.mkdir(parents=True,exist_ok=True)
                rec=dict(req,asked_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),asked_by='viewer',board=shown_root)
                tmp=qdir/f'.{rid}.json.part'
                tmp.write_text(json.dumps(rec,ensure_ascii=False,indent=1),encoding='utf-8')
                os.replace(tmp,qdir/f'{rid}.json')
            except OSError as ex:
                self.answer(500,ok=False,why='待ち行列に書けない: '+str(ex)[-200:]); return
            self.answer(200,ok=True,queued=rid,note=a.handoff_note)

        def log_message(self,*args): pass
    server=HTTPServer(('127.0.0.1',a.port),Handler)
    print(f'Board: http://127.0.0.1:{a.port}/  Demo: /demo'+(f'  hand-off queue: {qdir}' if qdir else ''),flush=True)
    threading.Thread(target=warm,daemon=True).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
