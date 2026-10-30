#!/usr/bin/env python3
"""Content-free progress check and receipt checks for a headless reviewer run in a sealed sandbox: tool-call and stop-reason counts, output-limit loop detection, seal-before-network order, web lookups, contamination-term counts; --selftest.

Why: a reviewer launched headless in a sealed sandbox (make-review-sandbox.py) prints nothing until it ends, and the
requester should not read its messages while it runs.  Two things were being done by hand with throw-away snippets:

  status   Is it alive or dead?  Reads only metadata of the session transcript (tool names, stop reasons, token
           counts, timestamps), never message text.  Flags the output-limit loop: consecutive responses that end with
           stop_reason "max_tokens" and consist of thinking only (output-cap-death-loop.md).  Such a run does not
           recover; stop it and relaunch with a lower reasoning effort or a split spec.
  receipt  After the run: (1) the sha256 in the Stage-1 seal file equals the sha256 of the sealed note;
           (2) the seal was written before the first network use (search / fetch / download) in the transcript,
           i.e. the blind stage really preceded the literature; (3) the list of web searches and URLs (check that the
           reviewer did not look up the requester or the manuscript); (4) counts of contamination terms in the result
           files and in the transcript (cold-eyes-isolation.md#post-check), each hit with its first places and the text
           around them (--context N, default 2), so the receipt can say why a transcript hit is benign.  Prints lines
           ready to paste into a receipt; save the output next to the receipt.

The transcript is found from the sandbox path: <config dir>/projects/<sandbox path with non-alphanumerics -> "-">/*.jsonl,
over $CLAUDE_CONFIG_DIR, ~/.claude and every ~/.claude-* (or --config-dir).  Several transcripts in that directory are
several launches (attempts); each is reported.  The transcripts of the subagents a launch started
(<session id>/subagents/*.jsonl) belong to that launch: status adds their tool counts, and receipt takes their network
use into the seal order and the web list and their text into the contamination counts.

Usage
  inspect-review-sandbox.py status  SANDBOX_DIR [--config-dir DIR ...]
  inspect-review-sandbox.py receipt SANDBOX_DIR [--results DIR] [--term T ...] [--terms-file FILE] [--context N]
                                    [--seal notes/stage1-seal.txt] [--sealed notes/stage1-blind.md] [--config-dir DIR ...]
  inspect-review-sandbox.py --selftest

Exit status of receipt: 0 = all checks hold, 1 = seal mismatch or network use before the seal, 2 = a contamination
term occurs in the result files (transcript hits are reported but do not change the exit status: paths and tool
descriptions produce benign hits).  Standard library only.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

NETWORK_TOOLS = ("WebSearch", "WebFetch")
URL_RE = re.compile(r"https?://[^\s\"'\\)>;,]+")
DENY_RE = re.compile(r"permission|denied|requires approval|haven't granted", re.I)
RESULT_NAMES = ("REVIEW-RESULTS.md", "ledger.yaml", "HANDOFF.md", "notes", "checks")


def slug_candidates(path: Path) -> list[str]:
    s = str(path)
    return list(dict.fromkeys([re.sub(r"[^A-Za-z0-9]", "-", s), s.replace("/", "-").replace("\\", "-")]))


def default_config_dirs() -> list[Path]:
    out = []
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        out.append(Path(env).expanduser())
    home = Path.home()
    out.append(home / ".claude")
    out.extend(sorted(p for p in home.glob(".claude-*") if p.is_dir()))
    return list(dict.fromkeys(out))


def find_transcripts(sandbox: Path, config_dirs: list[Path]) -> list[Path]:
    found = []
    for cfg in config_dirs:
        for slug in slug_candidates(sandbox):
            d = cfg / "projects" / slug
            if d.is_dir():
                found.extend(d.glob("*.jsonl"))
    return sorted(set(found), key=lambda p: p.stat().st_mtime)


def subagent_transcripts(main: Path) -> list[Path]:
    """Transcripts of the subagents (Agent tool) that a launch started: <session id>/subagents/*.jsonl next to it.

    A reviewer may delegate parts of the spec to subagents; their tool calls, downloads and contamination hits are
    recorded only there (measured: the downloads of a run were all in subagent transcripts, and the main one alone
    read as "no network use")."""
    d = main.with_suffix("") / "subagents"
    return sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []


def writes_seal(tool: str, inp: dict, seal_name: str) -> bool:
    """True if this tool call writes the seal file (a mere mention of its name in another file does not count)."""
    if tool in ("Write", "Edit"):
        return seal_name in Path(str(inp.get("file_path", ""))).name
    if tool == "Bash":
        cmd = str(inp.get("command", ""))
        if seal_name not in cmd:
            return False
        return bool(re.search(r"(>|\btee\b)[^|;&\n]*" + re.escape(seal_name), cmd))
    return False


def parse(transcript: Path, seal_name: str) -> dict:
    """Metadata of one transcript.  Message text is never stored, only counts, names, timestamps and lookups."""
    info = {
        "lines": 0, "first": None, "last": None,
        "tools": collections.Counter(), "stops": collections.Counter(),
        "cap_hits": 0, "thinking_only_cap": 0, "max_consecutive_thinking_cap": 0,
        "denied": 0, "seal_ts": None, "net": [],
    }
    run = 0
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            info["lines"] += 1
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            ts = obj.get("timestamp")
            if ts:
                info["first"] = info["first"] or ts
                info["last"] = ts
            msg = obj.get("message") or {}
            content = msg.get("content")
            blocks = content if isinstance(content, list) else []
            if obj.get("type") == "assistant":
                stop = msg.get("stop_reason")
                if stop:
                    info["stops"][stop] += 1
                kinds = {b.get("type") for b in blocks if isinstance(b, dict)}
                usage = msg.get("usage") or {}
                out_tok = usage.get("output_tokens") or 0
                think_tok = (usage.get("output_tokens_details") or {}).get("thinking_tokens") or 0
                if stop == "max_tokens":
                    info["cap_hits"] += 1
                    if not ({"text", "tool_use"} & kinds) and (think_tok >= out_tok > 0 or kinds <= {"thinking"}):
                        info["thinking_only_cap"] += 1
                        run += 1
                        info["max_consecutive_thinking_cap"] = max(info["max_consecutive_thinking_cap"], run)
                    else:
                        run = 0
                elif stop:
                    run = 0
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    name = b.get("name") or "?"
                    info["tools"][name] += 1
                    inp = b.get("input") or {}
                    blob = json.dumps(inp, ensure_ascii=False)
                    if writes_seal(name, inp, seal_name):
                        info["seal_ts"] = ts            # the latest write counts: a seal rewritten after a lookup is not a seal
                    if name == "WebSearch":
                        info["net"].append((ts, "search", str(inp.get("query", ""))))
                    elif name == "WebFetch":
                        info["net"].append((ts, "fetch", str(inp.get("url", ""))))
                    elif name == "Bash":
                        cmd = str(inp.get("command", ""))
                        urls = sorted(set(URL_RE.findall(cmd)))
                        if urls or re.search(r"\b(curl|wget)\b", cmd):
                            info["net"].append((ts, "download", ", ".join(urls) or "(curl/wget without a literal URL)"))
                elif b.get("type") == "tool_result" and b.get("is_error"):
                    if DENY_RE.search(json.dumps(b.get("content"), ensure_ascii=False)[:4000]):
                        info["denied"] += 1
    return info


def sandbox_listing(sandbox: Path) -> str:
    parts = []
    for p in sorted(sandbox.iterdir(), key=lambda x: x.name):
        if p.name.startswith("."):
            continue
        parts.append(f"{p.name}/({sum(1 for _ in p.iterdir())})" if p.is_dir() else p.name)
    return ", ".join(parts)


def cmd_status(sandbox: Path, config_dirs: list[Path], seal_name: str) -> int:
    print(f"sandbox: {sandbox}")
    print(f"files: {sandbox_listing(sandbox)}")
    print(f"DONE marker: {'yes' if (sandbox / 'DONE').exists() else 'no'}")
    transcripts = find_transcripts(sandbox, config_dirs)
    if not transcripts:
        print("no transcript found (looked under: " + ", ".join(str(c / 'projects') for c in config_dirs) + ")")
        return 0
    for i, t in enumerate(transcripts, 1):
        info = parse(t, seal_name)
        print(f"transcript {i}/{len(transcripts)}: {t.name}  lines {info['lines']}  first {info['first']}  last {info['last']}")
        print("  tool calls: " + (", ".join(f"{k} {v}" for k, v in sorted(info["tools"].items())) or "none"))
        print("  stop reasons: " + (", ".join(f"{k} {v}" for k, v in sorted(info["stops"].items())) or "none"))
        print(f"  permission denials: {info['denied']}")
        if info["max_consecutive_thinking_cap"] >= 2:
            print(f"  WARNING output-limit loop: {info['thinking_only_cap']} responses hit the output limit with thinking only "
                  f"({info['max_consecutive_thinking_cap']} in a row). It will not recover: stop it, lower the reasoning effort "
                  "or split the spec, relaunch (output-cap-death-loop.md).")
        elif info["thinking_only_cap"] == 1:
            print("  note: one response hit the output limit with thinking only; check again after the next response.")
        subs = subagent_transcripts(t)
        if subs:
            tools, denied = collections.Counter(), 0
            for s in subs:
                si = parse(s, seal_name)
                tools.update(si["tools"])
                denied += si["denied"]
            print(f"  subagents: {len(subs)} transcripts, tool calls: "
                  + (", ".join(f"{k} {v}" for k, v in sorted(tools.items())) or "none") + f"; permission denials: {denied}")
    return 0


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count_term(term: str, text: str) -> int:
    return len(re.findall(re.escape(term), text, flags=re.I))


def term_contexts(term: str, text: str, k: int, width: int = 70) -> list[str]:
    """The first k places where term occurs, with width characters on each side (newlines and JSON escapes flattened).
    The receipt records why a transcript hit is benign (a model name in the harness prompt, a substring of another word);
    a count alone does not let the requester write that down (measured)."""
    out = []
    for m in re.finditer(re.escape(term), text, flags=re.I):
        snippet = text[max(0, m.start() - width): m.end() + width]
        out.append(re.sub(r"\\[nt]|\s+", " ", snippet).strip())
        if len(out) >= k:
            break
    return out


def cmd_receipt(sandbox: Path, results: Path, config_dirs: list[Path], seal: str, sealed: str, terms: list[str],
                context: int = 2) -> int:
    status = 0
    seal_file, sealed_file = results / seal, results / sealed
    if seal_file.exists() and sealed_file.exists():
        digest = sha256_of(sealed_file)
        ok = digest in seal_file.read_text(encoding="utf-8", errors="replace")
        print(f"seal: sha256({sealed}) {'matches' if ok else 'DOES NOT MATCH'} the value recorded in {seal}  ({digest[:12]}...)")
        status = status if ok else 1
    else:
        print(f"seal: {seal} or {sealed} not found under {results} (single-stage run?)")
    transcripts = find_transcripts(sandbox, config_dirs)
    seal_name = Path(seal).stem
    all_transcripts = []
    for i, t in enumerate(transcripts, 1):
        info = parse(t, seal_name)
        subs = subagent_transcripts(t)
        all_transcripts += [t] + subs
        parts = [info] + [parse(s, seal_name) for s in subs]
        nets = sorted((n for p in parts for n in p["net"]), key=lambda n: n[0] or "")
        seal_ts = min((p["seal_ts"] for p in parts if p["seal_ts"]), default=None)
        first_net = min((n[0] for n in nets if n[0]), default=None)
        label = f"transcript {i}/{len(transcripts)}" + (f" (+ {len(subs)} subagent transcripts)" if subs else "")
        if seal_ts and first_net:
            ok = seal_ts <= first_net
            print(f"{label}: seal written {seal_ts}, first network use {first_net} -> "
                  f"{'seal precedes the literature' if ok else 'NETWORK USE BEFORE THE SEAL'}")
            status = status if ok else 1
        elif seal_ts:
            print(f"{label}: seal written {seal_ts}, no network use")
        elif first_net:
            print(f"{label}: no seal command found, first network use {first_net}")
        else:
            print(f"{label}: no seal command and no network use")
        for ts, kind, value in nets:
            print(f"  {kind:8s} {ts}  {value}")
        print(f"  permission denials: {sum(p['denied'] for p in parts)}; tool calls: {sum(sum(p['tools'].values()) for p in parts)}")
    if terms:
        result_text = []
        for name in RESULT_NAMES:
            p = results / name
            files = [p] if p.is_file() else sorted(q for q in p.rglob("*") if q.is_file()) if p.is_dir() else []
            for f in files:
                try:
                    result_text.append(f.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
        joined = "\n".join(result_text)
        transcript_text = "\n".join(t.read_text(encoding="utf-8", errors="replace") for t in all_transcripts)
        print("contamination terms (case-insensitive): term -> result files / transcript")
        for term in terms:
            r, tr = count_term(term, joined), count_term(term, transcript_text)
            print(f"  {term!r}: {r} / {tr}")
            for where, n, text in (("result", r, joined), ("transcript", tr, transcript_text)):
                if n and context > 0:
                    for snip in term_contexts(term, text, context):
                        print(f"      {where}: …{snip}…")
            if r:
                status = max(status, 2)
    return status


def selftest() -> int:
    def line(obj):
        return json.dumps(obj) + "\n"

    def assistant(ts, blocks, stop="tool_use", usage=None):
        return line({"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": blocks, "stop_reason": stop,
                                                                      "usage": usage or {"output_tokens": 10}}})

    cap = {"output_tokens": 64000, "output_tokens_details": {"thinking_tokens": 64000}}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sandbox = tmp / "box.one" / "run_a"
        (sandbox / "notes").mkdir(parents=True)
        (sandbox / "notes" / "stage1-blind.md").write_text("blind note\n")
        digest = sha256_of(sandbox / "notes" / "stage1-blind.md")
        (sandbox / "notes" / "stage1-seal.txt").write_text(f"{digest}  notes/stage1-blind.md\n")
        (sandbox / "REVIEW-RESULTS.md").write_text("result mentions SecretTitle once\n")
        cfg = tmp / "cfg"
        proj = cfg / "projects" / slug_candidates(sandbox)[0]
        proj.mkdir(parents=True)
        assert writes_seal("Write", {"file_path": "/x/notes/stage1-seal.txt"}, "stage1-seal")
        assert not writes_seal("Write", {"file_path": "/x/notes/stage1-blind.md", "content": "then write stage1-seal.txt"}, "stage1-seal")
        assert not writes_seal("Bash", {"command": "ls notes/stage1-seal.txt"}, "stage1-seal")
        assert writes_seal("Bash", {"command": "shasum -a 256 n.md | tee notes/stage1-seal.txt"}, "stage1-seal")
        good = (assistant("T01", [{"type": "tool_use", "name": "Read", "input": {"file_path": "REVIEW-SPEC.md"}}])
                + assistant("T02", [{"type": "thinking", "thinking": ""}], stop="max_tokens", usage=cap)
                + assistant("T03", [{"type": "thinking", "thinking": ""}], stop="max_tokens", usage=cap)
                + assistant("T04", [{"type": "tool_use", "name": "Bash", "input": {"command": "shasum -a 256 notes/stage1-blind.md > notes/stage1-seal.txt"}}])
                + assistant("T05", [{"type": "tool_use", "name": "WebSearch", "input": {"query": "heat kernel review"}}])
                + assistant("T06", [{"type": "tool_use", "name": "Bash", "input": {"command": "curl -sL https://example.org/paper.pdf -o scratch/p.pdf"}}])
                + line({"type": "user", "timestamp": "T07", "message": {"role": "user", "content": [
                    {"type": "tool_result", "is_error": True, "content": "Permission denied by settings"}]}}))
        (proj / "a.jsonl").write_text(good)
        info = parse(proj / "a.jsonl", "stage1-seal")
        assert info["tools"] == {"Read": 1, "Bash": 2, "WebSearch": 1}, info["tools"]
        assert info["stops"]["max_tokens"] == 2 and info["thinking_only_cap"] == 2 and info["max_consecutive_thinking_cap"] == 2
        assert info["denied"] == 1 and info["seal_ts"] == "T04"
        assert [n[1] for n in info["net"]] == ["search", "download"] and "example.org" in info["net"][1][2]
        assert find_transcripts(sandbox, [cfg]) == [proj / "a.jsonl"]
        assert cmd_status(sandbox, [cfg], "stage1-seal") == 0
        assert cmd_receipt(sandbox, sandbox, [cfg], "notes/stage1-seal.txt", "notes/stage1-blind.md", []) == 0
        assert cmd_receipt(sandbox, sandbox, [cfg], "notes/stage1-seal.txt", "notes/stage1-blind.md", ["secrettitle"]) == 2
        # a transcript hit is shown with its surroundings (the receipt says why it is benign); a result hit too
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc_ctx = cmd_receipt(sandbox, sandbox, [cfg], "notes/stage1-seal.txt", "notes/stage1-blind.md", ["kernel", "SecretTitle"])
        assert rc_ctx == 2 and "transcript: …" in buf.getvalue() and "heat kernel review" in buf.getvalue(), buf.getvalue()
        assert "result: …result mentions SecretTitle once" in buf.getvalue(), buf.getvalue()
        assert term_contexts("a", "xaxbxa", 1) == ["xaxbxa"] and term_contexts("zz", "abc", 2) == []
        # network use before the seal is flagged
        bad = (assistant("T01", [{"type": "tool_use", "name": "WebFetch", "input": {"url": "https://example.org/x"}}])
               + assistant("T02", [{"type": "tool_use", "name": "Write", "input": {"file_path": "notes/stage1-seal.txt", "content": digest}}]))
        (proj / "a.jsonl").write_text(bad)
        assert cmd_receipt(sandbox, sandbox, [cfg], "notes/stage1-seal.txt", "notes/stage1-blind.md", []) == 1
        # a subagent of the launch: its network use enters the seal order, its text the contamination counts
        (proj / "a.jsonl").write_text(good)
        sub = proj / "a" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-x.jsonl").write_text(assistant("T03", [{"type": "tool_use", "name": "WebFetch", "input": {"url": "https://example.org/early"}}])
                                           + assistant("T05", [{"type": "text", "text": "subagent saw HiddenWord"}]))
        assert subagent_transcripts(proj / "a.jsonl") == [sub / "agent-x.jsonl"]
        assert cmd_receipt(sandbox, sandbox, [cfg], "notes/stage1-seal.txt", "notes/stage1-blind.md", []) == 1
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_receipt(sandbox, sandbox, [cfg], "notes/stage1-seal.txt", "notes/stage1-blind.md", ["HiddenWord"])
            cmd_status(sandbox, [cfg], "stage1-seal")
        out = buf.getvalue()
        assert "'HiddenWord': 0 / 1" in out and "(+ 1 subagent transcripts)" in out and "subagents: 1 transcripts" in out, out
        (sub / "agent-x.jsonl").unlink()
        sub.rmdir(); sub.parent.rmdir()
        # a modified sealed note is flagged
        (proj / "a.jsonl").write_text(good)
        (sandbox / "notes" / "stage1-blind.md").write_text("edited after the seal\n")
        assert cmd_receipt(sandbox, sandbox, [cfg], "notes/stage1-seal.txt", "notes/stage1-blind.md", []) == 1
        # a single capped response is a note, not a loop
        (proj / "a.jsonl").write_text(assistant("T02", [{"type": "thinking", "thinking": ""}], stop="max_tokens", usage=cap)
                                      + assistant("T03", [{"type": "text", "text": "ok"}], stop="end_turn"))
        one = parse(proj / "a.jsonl", "stage1-seal")
        assert one["thinking_only_cap"] == 1 and one["max_consecutive_thinking_cap"] == 1
    print("selftest OK")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("status", "receipt"))
    ap.add_argument("sandbox", type=Path)
    ap.add_argument("--config-dir", type=Path, action="append", default=None)
    ap.add_argument("--results", type=Path, default=None, help="directory holding the collected results (default: the sandbox)")
    ap.add_argument("--seal", default="notes/stage1-seal.txt")
    ap.add_argument("--sealed", default="notes/stage1-blind.md")
    ap.add_argument("--term", action="append", default=[])
    ap.add_argument("--terms-file", type=Path, default=None)
    ap.add_argument("--context", type=int, default=2,
                    help="receipt: show the first N places of each hit with surrounding text, so the receipt can say why a hit is benign (0 = counts only)")
    args = ap.parse_args(argv)
    sandbox = args.sandbox.expanduser().resolve()
    if not sandbox.is_dir():
        print(f"not a directory: {sandbox}", file=sys.stderr)
        return 1
    config_dirs = [c.expanduser() for c in args.config_dir] if args.config_dir else default_config_dirs()
    if args.command == "status":
        return cmd_status(sandbox, config_dirs, Path(args.seal).stem)
    terms = list(args.term)
    if args.terms_file:
        terms += [t.strip() for t in args.terms_file.read_text(encoding="utf-8").splitlines() if t.strip() and not t.startswith("#")]
    results = (args.results or sandbox).expanduser().resolve()
    return cmd_receipt(sandbox, results, config_dirs, args.seal, args.sealed, terms, context=args.context)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
