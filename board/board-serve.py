#!/usr/bin/env python3
"""Read-only localhost board; reload reads current state. No mutation endpoints."""
import argparse
import importlib.util
from http.server import BaseHTTPRequestHandler, HTTPServer
from html import escape
from pathlib import Path
import subprocess
import sys
import board

import board_config as bc
spec=importlib.util.spec_from_file_location('board_html',board.ENGINE/'board-html.py')
html=importlib.util.module_from_spec(spec); spec.loader.exec_module(html)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port',type=int,default=8769)
    ap.add_argument('--root',type=Path,help='the board directory (holds board.json and events/)')
    ap.add_argument('--board',help='a board in the workspace by name')
    ap.add_argument('--local',action='store_true',help='read local checkout instead of synchronizing remote')
    a=ap.parse_args()
    a.root=bc.resolve(a.root,a.board)
    labels=({} if bc.is_locked(a.root) else bc.load(a.root).get('labels',{}))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # No file serving, arbitrary paths, cross-origin API, or write methods.
            if self.headers.get('Host') not in {f'127.0.0.1:{a.port}',f'localhost:{a.port}'}:
                self.send_error(403); return
            if self.path.split('#')[0] not in {'/','/demo'}:
                self.send_error(404); return
            try:
                if self.path=='/demo': payload=html.demo_payload()
                elif a.local: payload=html.payload_from(a.root,None)
                else:
                    with board.snapshot(a.root) as root: payload=html.payload_from(root,None)
                if self.path!='/demo': payload.update(root=str(a.root).replace(str(Path.home()),'~'),labels=labels)
                body=html.build(payload).encode(); status=200
            except (ValueError,OSError,subprocess.SubprocessError) as ex:
                body=('<h1>掲示板を更新できませんでした</h1><p>未処理がゼロという意味ではありません。再読み込みしてください。</p><pre>'+escape(str(ex))+'</pre>').encode(); status=503
            self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(body)
        def log_message(self,*args): pass
    server=HTTPServer(('127.0.0.1',a.port),Handler)
    print(f'Board: http://127.0.0.1:{a.port}/  Demo: /demo',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
