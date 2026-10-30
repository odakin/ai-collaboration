#!/usr/bin/env python3
"""Read-only localhost board. A page is served at once from the last render (the first one from the local checkout),
and a synchronized render is made in the background; the page asks /version and swaps itself in when that is newer.
No mutation endpoints."""
import argparse
import importlib.util
import json
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
# request, the local one about 1.5 s; the cached page is served in milliseconds.
MIN_REFRESH_S=15
CSP="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port',type=int,default=8769)
    ap.add_argument('--root',type=Path,help='the board directory (holds board.json and events/)')
    ap.add_argument('--board',help='a board in the workspace by name')
    ap.add_argument('--local',action='store_true',help='read local checkout instead of synchronizing remote')
    a=ap.parse_args()
    a.root=bc.resolve(a.root,a.board)
    labels=({} if bc.is_locked(a.root) else bc.load(a.root).get('labels',{}))
    shown_root=str(a.root).replace(str(Path.home()),'~')

    def render(sync):
        if sync and not a.local:
            with board.snapshot(a.root) as root: payload=html.payload_from(root,None)
        else:
            payload=html.payload_from(a.root,None)
        payload.update(root=shown_root,labels=labels)
        return html.build(payload).encode(),{'head':payload.get('head'),'generated_at':payload.get('generated_at')}

    cache={'body':None,'version':{},'at':0.0,'refreshing':False,'error':None,'synced':False}
    lock=threading.Lock()

    def refresh():
        try:
            body,ver=render(True)
            with lock: cache.update(body=body,version=ver,at=time.time(),error=None,synced=True)
        except (ValueError,OSError,subprocess.SubprocessError) as ex:
            with lock: cache['error']=str(ex)[-400:]
        finally:
            with lock: cache['refreshing']=False

    def kick(force=False):
        with lock:
            if cache['refreshing'] or (not force and time.time()-cache['at']<MIN_REFRESH_S): return
            cache['refreshing']=True
        threading.Thread(target=refresh,daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,body,ctype):
            self.send_response(status)
            self.send_header('Content-Type',ctype)
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',CSP)
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            # No file serving, arbitrary paths, cross-origin API, or write methods.
            if self.headers.get('Host') not in {f'127.0.0.1:{a.port}',f'localhost:{a.port}'}:
                self.send_error(403); return
            path,_,query=self.path.split('#')[0].partition('?')
            if path not in {'/','/demo','/version'}:
                self.send_error(404); return
            try:
                if path=='/demo':
                    p=html.demo_payload(); self.reply(200,html.build(p).encode(),'text/html; charset=utf-8'); return
                if path=='/version':
                    kick(force=query=='refresh=1')
                    with lock:
                        v=dict(cache['version'],refreshing=cache['refreshing'],synced=cache['synced'],error=cache['error'])
                    self.reply(200,json.dumps(v).encode(),'application/json'); return
                with lock: body=cache['body']
                if body is None:   # the first view after start: the local checkout now, the synchronized one behind it
                    body,ver=render(False)
                    with lock:
                        if cache['body'] is None: cache.update(body=body,version=ver,at=0.0)
                kick()
                self.reply(200,body,'text/html; charset=utf-8')
            except (ValueError,OSError,subprocess.SubprocessError) as ex:
                body=('<h1>掲示板を更新できませんでした</h1><p>未処理がゼロという意味ではありません。再読み込みしてください。</p><pre>'+escape(str(ex))+'</pre>').encode()
                self.reply(503,body,'text/html; charset=utf-8')
        def log_message(self,*args): pass
    server=HTTPServer(('127.0.0.1',a.port),Handler)
    print(f'Board: http://127.0.0.1:{a.port}/  Demo: /demo',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
