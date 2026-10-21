#!/usr/bin/env python3
"""Fetch an explicit list of literature (arXiv ids or URLs) into a fresh directory with a per-item provenance manifest (URL, version pin, HTTP status, PDF signature, size, sha256); --selftest.

Why: a reviewer or verification worker downloads the cited papers into its scratch area, and a batch
that "finished" is not a batch in which every item is the requested PDF (an error page, a captcha, a
truncated transfer and a later arXiv version all arrive as files). The reusable part is the record:
which identifier was asked for, which URL answered, with what status, and the digest of what was kept
(conventions/physics-verification-cycle.md#literature-fetch-and-reading-depth).

    python3 fetch-literature.py 2101.00001v2 hep-th/0001001v2 --out scratch/lit
    python3 fetch-literature.py --list sources.txt --out scratch/lit --manifest checks/lit.json

Items: arXiv ids (new style 2104.01798[vN], old style hep-th/0001001[vN]) or http(s) URLs; --list reads one
item per line (blank lines and '#' comments ignored). An id without vN fetches whatever version is current
and is flagged version_pinned=false: record the digest, and pin the version when the result must be
reproducible. Nothing is replaced: the run refuses before fetching if any target file or the manifest
already exists (collected evidence stays as it was). Exit 0 only when every item answered HTTP 200 with a
%PDF signature; otherwise 1 after writing the manifest, so the caller cannot mistake a partial batch for a
complete one. The signature is not an integrity check of the PDF. Fetch only what the task authorizes.
Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ARXIV_NEW = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
ARXIV_OLD = re.compile(r"^[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$")
UA = "Mozilla/5.0 (literature fetch for review; contact via the requester)"


def classify(item: str) -> dict:
    """Map one list item to url, file name and version pin (pure function)."""
    if ARXIV_NEW.match(item) or ARXIV_OLD.match(item):
        return {"item": item, "kind": "arxiv", "url": f"https://arxiv.org/pdf/{item}",
                "name": item.replace("/", "-") + ".pdf", "version_pinned": bool(re.search(r"v\d+$", item))}
    if item.startswith(("http://", "https://")):
        tail = re.sub(r"[^A-Za-z0-9._-]+", "-", item.split("://", 1)[1]).strip("-")[-120:]
        return {"item": item, "kind": "url", "url": item,
                "name": tail if tail.lower().endswith(".pdf") else tail + ".pdf", "version_pinned": None}
    raise SystemExit(f"not an arXiv id or http(s) URL: {item!r}")


def fetch_one(entry: dict, out: Path, timeout: float) -> dict:
    path = out / entry["name"]
    rec = dict(entry, path=str(path), http_status=None, final_url=None, content_type=None,
               pdf_signature=False, bytes=0, sha256=None, error=None,
               fetched_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    req = urllib.request.Request(entry["url"], headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            rec.update(http_status=r.status, final_url=r.geturl(), content_type=r.headers.get("Content-Type"))
    except urllib.error.HTTPError as e:
        body = e.read() or b""
        rec.update(http_status=e.code, error=f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        body = b""
        rec["error"] = f"{type(e).__name__}: {e}"
    if body:
        path.write_bytes(body)
        rec.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), pdf_signature=body.startswith(b"%PDF-"))
    rec["ok"] = rec["http_status"] == 200 and rec["pdf_signature"]
    return rec


def run(items: list[str], out: Path, manifest: Path, timeout: float, delay: float) -> int:
    entries = [classify(i) for i in items]
    names = [e["name"] for e in entries]
    if len(set(names)) != len(names):
        raise SystemExit("two items map to the same file name; list each source once")
    clash = [p for p in [out / n for n in names] + [manifest] if p.exists()]
    if clash:
        raise SystemExit("refusing to replace existing files (choose a fresh --out/--manifest): "
                         + ", ".join(map(str, clash)))
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for k, e in enumerate(entries):
        if k and delay:
            time.sleep(delay)
        rec = fetch_one(e, out, timeout)
        records.append(rec)
        flag = "ok " if rec["ok"] else "BAD"
        pin = {True: "pinned", False: "UNPINNED", None: "-"}[rec["version_pinned"]]
        print(f"{flag} {rec['item']} status={rec['http_status']} pdf={rec['pdf_signature']} "
              f"bytes={rec['bytes']} {pin} {(rec['sha256'] or '')[:12]} {rec['error'] or ''}".rstrip())
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    bad = [r["item"] for r in records if not r["ok"]]
    print(f"-- {len(records) - len(bad)}/{len(records)} ok; manifest -> {manifest}")
    return 0 if not bad else 1


def selftest() -> int:
    checks = {}
    c = classify("2104.01798")
    checks["new id unpinned"] = c["url"] == "https://arxiv.org/pdf/2104.01798" and c["version_pinned"] is False
    c = classify("hep-th/0001001v2")
    checks["old id pinned"] = c["name"] == "hep-th-0001001v2.pdf" and c["version_pinned"] is True
    try:
        classify("not an id")
        checks["junk refused"] = False
    except SystemExit:
        checks["junk refused"] = True
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "srv"
        root.mkdir()
        (root / "a.pdf").write_bytes(b"%PDF-1.4\n% synthetic\n%%EOF\n")
        (root / "b.pdf").write_bytes(b"<html>captcha</html>")

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(root), **kw)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            out, man = Path(d) / "lit", Path(d) / "lit.json"
            rc = run([f"{base}/a.pdf"], out, man, 5, 0)
            rec = json.loads(man.read_text())[0]
            checks["good item"] = rc == 0 and rec["ok"] and rec["http_status"] == 200 and len(rec["sha256"]) == 64
            try:
                run([f"{base}/a.pdf"], out, man, 5, 0)
                checks["rerun refused"] = False
            except SystemExit:
                checks["rerun refused"] = True
            out2, man2 = Path(d) / "lit2", Path(d) / "lit2.json"
            rc = run([f"{base}/a.pdf", f"{base}/b.pdf", f"{base}/missing.pdf"], out2, man2, 5, 0)
            recs = {Path(r["item"]).name: r for r in json.loads(man2.read_text())}
            checks["partial batch fails"] = rc == 1
            checks["non-PDF flagged"] = (recs["b.pdf"]["http_status"] == 200 and not recs["b.pdf"]["pdf_signature"]
                                         and not recs["b.pdf"]["ok"])
            checks["404 recorded"] = recs["missing.pdf"]["http_status"] == 404 and not recs["missing.pdf"]["ok"]
        finally:
            srv.shutdown()
    bad = [k for k, v in checks.items() if not v]
    print("selftest:", "PASS" if not bad else f"FAIL {bad}")
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("items", nargs="*", help="arXiv ids or http(s) URLs")
    ap.add_argument("--list", type=Path, help="file with one item per line ('#' comments allowed)")
    ap.add_argument("--out", type=Path, help="directory for the fetched files")
    ap.add_argument("--manifest", type=Path, help="manifest path (default: <out>/fetch-manifest.json)")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    items = list(a.items)
    if a.list:
        items += [s.split("#", 1)[0].strip() for s in a.list.read_text(encoding="utf-8").splitlines()]
    items = [i for i in items if i]
    if not items or not a.out:
        ap.error("give items (or --list) and --out")
    return run(items, a.out, a.manifest or a.out / "fetch-manifest.json", a.timeout, a.delay)


if __name__ == "__main__":
    sys.exit(main())
