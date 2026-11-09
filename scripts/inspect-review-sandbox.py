#!/usr/bin/env python3
"""Content-free progress check and receipt checks for a reviewer run in a sealed sandbox, from a Claude transcript or a Codex app rollout: tool-call and stop-reason counts, output-limit loop detection, seal before the literature (network and Stage-2 documents), web lookups, outside paths, contamination-term counts, Codex app state and effort records; --selftest.

Why: a reviewer launched headless in a sealed sandbox (make-review-sandbox.py) prints nothing until it ends, and the
requester should not read its messages while it runs.  Two things were being done by hand with throw-away snippets:

  status   Is it alive or dead?  Reads only metadata of the session transcript (tool names, stop reasons, token
           counts, timestamps), never message text.  Flags the output-limit loop: consecutive responses that end with
           stop_reason "max_tokens" and consist of thinking only (output-cap-death-loop.md).  Such a run does not
           recover; stop it and relaunch with a lower reasoning effort or a split spec.
  receipt  After the run:
           (1) the sha256 in the Stage-1 seal file equals the sha256 of the sealed note, and the note's file mode
               (read-only or not);
           (2) order: the seal was written before the first network use (search / fetch / download / network-like
               tokens in a command) and before any tool call that names a Stage-2 document (--stage2 NAME,
               --stage2-file FILE; the documents handed over in the sandbox cannot be seen as network use), i.e. the
               blind stage really preceded the literature.  The seal-writing call is found by the write itself: a
               Write / Edit of the seal file, a shell redirect or tee into it, Python write_text / write_bytes /
               open(..., "w") on it (also through a variable).  A later call that only reads or quotes the seal does
               not move it (measured: a seal check that wrote the results mentioned the seal file and a hash), and
               the latest write counts (a seal rewritten after a lookup is not a seal);
           (3) the list of web searches and URLs (check that the reviewer did not look up the requester or the
               manuscript);
           (4) tool calls that name a path outside the sandbox (under a home directory, or a sibling sandbox):
               listed with the path cut to two levels, the exit status is not changed (a benign mention is possible;
               the receipt says why);
           (5) counts of contamination terms (cold-eyes-isolation.md#post-check) in three columns: result files
               (REVIEW-RESULTS.md, STAGE*-RESULTS.md, ledger.yaml, HANDOFF.md, notes/, checks/) / other files the
               reviewer wrote (scratch/, outside-rules/ and anything else that is not an input: the split of
               make-review-sandbox.py collect, its ledger or file times telling inputs apart) / transcript or
               rollout.  Each hit with its first places and the text around them (--context N, default 2), so the
               receipt can say why a hit is benign.  Ciphertext fields (encrypted reasoning, thinking signatures)
               are not searched: a short term matches base64 by chance.
           Prints lines ready to paste into a receipt; save the output next to the receipt.

The transcript is found from the sandbox path: <config dir>/projects/<sandbox path with non-alphanumerics -> "-">/*.jsonl,
over $CLAUDE_CONFIG_DIR, ~/.claude and every ~/.claude-* (or --config-dir).  Several transcripts in that directory are
several launches (attempts); each is reported.  The transcripts of the subagents a launch started
(<session id>/subagents/*.jsonl) belong to that launch: status adds their tool counts, and receipt takes their calls
into the seal order and the web list and their text into the contamination counts.

A Codex app run (--codex-rollout THREAD_ID or PATH, repeatable; or the thread id from --codex-launch): the rollout is
<$CODEX_HOME or ~/.codex>/sessions/<date>/rollout-*-<thread id>.jsonl (archived_sessions/*.jsonl.zst too, read when
Python has compression.zstd), and the Claude transcripts are not read.  Checks (1)-(5) run on its tool calls
(custom_tool_call / function_call / local_shell_call / web_search_call), and two more come from records only the app
writes (cold-eyes-isolation.md#codex-rollout-receipt (b), (c)):
           (6) app state on the turn (world_state and additional_tools records): per record the counts (approved
               command prefixes, skill entries, tools, distinct directories outside the sandbox) and, per
               contamination term, the hits with the key path where they sit (a key that is itself data, such as a
               file path, is shown as <key>).  Titles and paths are never printed, and a rollout
               hit inside these records is shown by its key path, not by its text (measured: world_state carried the
               command prefixes approved earlier on the machine, with paths of other repositories);
           (7) reasoning effort from three records side by side: the launch (--codex-launch FILE = the --json output
               of codex-app-launch.py), every thread_settings_applied, and the turn_context of every turn; a line
               says where they differ, and none is called the effective effort (measured: the thread settings took
               the machine's default a few seconds after the only turn had started).
           status --codex-rollout prints the rollout's record and tool counts, turn events and last token totals.

Usage
  inspect-review-sandbox.py status  SANDBOX_DIR [--config-dir DIR ...] [--codex-rollout ID|PATH ...] [--codex-launch FILE]
  inspect-review-sandbox.py receipt SANDBOX_DIR [--results DIR] [--term T ...] [--terms-file FILE] [--context N]
                                    [--stage2 NAME ...] [--stage2-file FILE]
                                    [--seal notes/stage1-seal.txt] [--sealed notes/stage1-blind.md] [--config-dir DIR ...]
                                    [--codex-rollout ID|PATH ...] [--codex-launch FILE] [--codex-home DIR]
  inspect-review-sandbox.py --selftest

Exit status of receipt: 0 = all checks hold, 1 = seal mismatch, or network use or a Stage-2 document named before the
seal, 2 = a contamination term occurs in the result files (hits in other written files and in the transcript are
reported but do not change the exit status: downloaded literature, paths and tool descriptions produce benign hits).
Standard library only (make-review-sandbox.py, next to this file, tells inputs from the reviewer's files).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

NETWORK_TOOLS = ("WebSearch", "WebFetch")
URL_RE = re.compile(r"https?://[^\s\"'\\)>;,]+")
# a command that may reach the network.  The Python routes are named by the call that fetches: urllib.parse (string
# handling) is not one (measured: a bare "urllib" counted a link-fixing script three times)
NET_TOKEN_RE = re.compile(r"\b(?:curl|wget|urllib\.request|urlopen|urllib3|httpx)\b|\brequests\.(?:get|post|head|Session)\b"
                          r"|https?://", re.I)
DENY_RE = re.compile(r"permission|denied|requires approval|haven't granted", re.I)
RESULT_ROOT_NAMES = ("REVIEW-RESULTS.md", "ledger.yaml", "HANDOFF.md")
RESULT_DIRS = ("notes", "checks")
CIPHER_KEYS = {"encrypted_content", "signature"}
CODEX_CALL_TYPES = ("custom_tool_call", "function_call", "local_shell_call", "web_search_call")


def _sibling(name: str):
    """Load a sibling script whose file name has dashes (make-review-sandbox.py)."""
    import importlib.util
    path = Path(__file__).resolve().parent / name
    spec_ = importlib.util.spec_from_file_location(name.replace("-", "_").removesuffix(".py"), path)
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


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


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def find_codex_rollouts(token: str, codex_home: Path) -> list[Path]:
    """A rollout path as given, or the rollouts whose file name ends with the thread id (live and archived)."""
    p = Path(token).expanduser()
    if p.is_file():
        return [p]
    tid = token.strip()
    if not re.fullmatch(r"[0-9A-Za-z-]{8,}", tid):
        return []
    found = list(codex_home.glob(f"sessions/*/*/*/rollout-*-{tid}*.jsonl"))
    found += list(codex_home.glob(f"archived_sessions/rollout-*-{tid}*.jsonl*"))
    return sorted(set(found))


def open_text(path: Path):
    if path.suffix == ".zst":
        try:
            from compression import zstd      # Python 3.14+
        except ImportError:
            raise SystemExit(f"{path}: an archived (zstd) rollout; decompress it first (zstd -d) or use Python 3.14+")
        return zstd.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open(encoding="utf-8", errors="replace")


def scrub(obj):
    """The record without ciphertext fields (their base64 matches short terms by chance)."""
    if isinstance(obj, dict):
        return {k: ("" if k in CIPHER_KEYS else scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def record_text(obj) -> str:
    return json.dumps(scrub(obj), ensure_ascii=False)


# --- the seal-writing call -------------------------------------------------------------------------------------

def _quoted_seal(seal: str) -> str:
    """A quoted string literal that contains the seal name (quotes may be escaped inside a JSON / JS command)."""
    return r"\\?[\"'][^\"'\n]*" + re.escape(seal) + r"[^\"'\n]*\\?[\"']"


def command_writes_seal(text: str, seal_name: str) -> bool:
    """True if this command text writes the seal file: a redirect or tee into it, Python write_text / write_bytes /
    open(..., w|a|x) on a literal naming it, or on a variable assigned such a literal.  Naming the seal in another
    file's content, reading it, or hashing it do not count."""
    if seal_name not in text:
        return False
    # a command quoted inside JSON / JS (a Codex exec input) carries its line breaks as the two characters \n
    text = text.replace("\\n", "\n").replace("\\t", "\t")
    s = re.escape(seal_name)
    q = _quoted_seal(seal_name)
    if re.search(r"(?:>>?|\btee\b(?:\s+-a)?)\s*\\?[\"']?[^\s\"'\\|;&<>()]*" + s, text):
        return True
    if re.search(q + r"\s*\)\s*\.write_(?:text|bytes)\(", text):
        return True
    if re.search(r"\bopen\(\s*" + q + r"\s*,\s*(?:mode\s*=\s*)?\\?[\"'][wax]", text):
        return True
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*=\s*(?:Path\(|pathlib\.Path\()?[^=\n]{0,80}?" + q, text):
        v = re.escape(m.group(1))
        if re.search(r"\b" + v + r"\s*\.write_(?:text|bytes)\(|\bopen\(\s*" + v + r"\s*,\s*(?:mode\s*=\s*)?\\?[\"'][wax]",
                     text[m.end():]):
            return True
    return False


def writes_seal(tool: str, inp, seal_name: str) -> bool:
    """True if this tool call writes the seal file (a mere mention of its name in another file does not count)."""
    if tool in ("Write", "Edit", "MultiEdit"):
        return seal_name in Path(str((inp or {}).get("file_path", ""))).name
    if isinstance(inp, dict):
        cmd = str(inp.get("command", "")) if tool == "Bash" else ""
    else:
        cmd = str(inp)
    return bool(cmd) and command_writes_seal(cmd, seal_name)


# --- reading a Claude transcript -------------------------------------------------------------------------------

def _new_info() -> dict:
    return {"lines": 0, "first": None, "last": None, "tools": collections.Counter(), "stops": collections.Counter(),
            "cap_hits": 0, "thinking_only_cap": 0, "max_consecutive_thinking_cap": 0,
            "denied": 0, "seal_ts": None, "net": [], "calls": [], "records": []}


def parse(transcript: Path, seal_name: str) -> dict:
    """Metadata of one transcript.  Only counts, names, timestamps and lookups are printed; the tool inputs and the
    records are kept for the order, outside-path and contamination checks."""
    info = _new_info()
    run = 0
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            info["lines"] += 1
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            info["records"].append(obj)
            ts = obj.get("timestamp")
            if ts:
                info["first"] = info["first"] or ts
                info["last"] = ts
            msg = obj.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
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
                    seal = writes_seal(name, inp, seal_name)
                    if seal:
                        info["seal_ts"] = ts            # the latest write counts: a seal rewritten after a lookup is not a seal
                    info["calls"].append({"ts": ts, "name": name, "text": json.dumps(inp, ensure_ascii=False), "seal": seal})
                    if name == "WebSearch":
                        info["net"].append((ts, "search", str(inp.get("query", ""))))
                    elif name == "WebFetch":
                        info["net"].append((ts, "fetch", str(inp.get("url", ""))))
                    elif name == "Bash":
                        cmd = str(inp.get("command", ""))
                        urls = sorted(set(URL_RE.findall(cmd)))
                        toks = sorted({m.group(0).lower() for m in NET_TOKEN_RE.finditer(cmd)} - {"http://", "https://"})
                        if urls or toks:
                            info["net"].append((ts, "download", ", ".join(urls) or f"({', '.join(toks)} without a literal URL)"))
                elif b.get("type") == "tool_result" and b.get("is_error"):
                    if DENY_RE.search(json.dumps(b.get("content"), ensure_ascii=False)[:4000]):
                        info["denied"] += 1
    return info


# --- reading a Codex rollout -----------------------------------------------------------------------------------

def is_state_record(obj: dict) -> str | None:
    """'world_state' / 'additional_tools' for the records that carry the app's state on the turn, else None."""
    p = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    if obj.get("type") == "world_state":
        return "world_state"
    if p.get("type") == "additional_tools":
        return "additional_tools"
    return None


def parse_codex(rollout: Path, seal_name: str) -> dict:
    """Metadata, tool calls, state records and effort records of one Codex rollout."""
    info = _new_info()
    info.update({"denied": None, "types": collections.Counter(), "events": collections.Counter(), "state": [],
                 "settings": [], "turns": [], "starts": [], "completes": [], "tokens": None, "cwd": None})
    with open_text(rollout) as fh:
        for line in fh:
            if not line.strip():
                continue
            info["lines"] += 1
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            info["records"].append(obj)
            ts = obj.get("timestamp")
            if ts:
                info["first"] = info["first"] or ts
                info["last"] = ts
            t = obj.get("type")
            p = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            pt = p.get("type")
            info["types"][f"{t}/{pt}" if pt else str(t)] += 1
            kind = is_state_record(obj)
            if kind:
                info["state"].append((len(info["records"]), ts, kind, obj))
            if t == "session_meta":
                info["cwd"] = p.get("cwd")
            elif t == "turn_context":
                info["turns"].append((ts, str(p.get("turn_id") or ""), p.get("model"), p.get("effort") or p.get("reasoning_effort")))
            elif t == "event_msg":
                info["events"][pt] += 1
                if pt == "thread_settings_applied":
                    s = p.get("thread_settings") or {}
                    info["settings"].append((ts, s.get("model"), s.get("reasoning_effort") or s.get("effort")))
                elif pt == "task_started":
                    info["starts"].append((ts, str(p.get("turn_id") or "")))
                elif pt == "task_complete":
                    info["completes"].append((ts, str(p.get("turn_id") or "")))
                elif pt == "token_count":
                    info["tokens"] = (p.get("info") or {}).get("total_token_usage") or info["tokens"]
            if pt in CODEX_CALL_TYPES:
                name = p.get("name") or pt
                info["tools"][name] += 1
                if pt == "web_search_call":
                    act = p.get("action") or {}
                    text = json.dumps(act, ensure_ascii=False)
                    info["net"].append((ts, "search", str(act.get("query") or act.get("url") or text)[:300]))
                else:
                    raw = p.get("input") if p.get("input") is not None else p.get("arguments")
                    if raw is None:
                        raw = p.get("action") or ""
                    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
                    toks = sorted({m.group(0).lower() for m in NET_TOKEN_RE.finditer(text)})
                    if toks:
                        urls = sorted(set(URL_RE.findall(text)))[:3]
                        info["net"].append((ts, "network-like", ", ".join(toks) + (f"  {', '.join(urls)}" if urls else "")))
                seal = command_writes_seal(text, seal_name)
                if seal:
                    info["seal_ts"] = ts
                info["calls"].append({"ts": ts, "name": name, "text": text, "seal": seal})
    return info


# --- checks shared by both kinds of run ------------------------------------------------------------------------

def _path_re(home: str, parent: str) -> re.Pattern:
    roots = [r"\$\{HOME\}", r"\$HOME", r"~(?=/)", r"/Users/[^/\s\"'\\]+", r"/home/[^/\s\"'\\]+", re.escape(home), re.escape(parent)]
    return re.compile(r"(?:" + "|".join(roots) + r")(?:/[^\s\"'\\`<>|;&,(){}\[\]*]*)?")


def _short(p: str, home: str) -> str:
    if p == home or p.startswith(home + "/"):
        parts = [x for x in p[len(home):].split("/") if x]
        return "~/" + "/".join(parts[:2]) if parts else "~"
    parts = [x for x in p.split("/") if x]
    return "/" + "/".join(parts[:3])


def outside_paths(text: str, sandbox: Path, home: str | None = None) -> list[str]:
    """Paths in text that lie under a home directory or next to the sandbox but not inside it, cut to two levels
    below the home (three from the root otherwise)."""
    home = (home or str(Path.home())).rstrip("/")
    sb, parent = str(sandbox).rstrip("/"), str(sandbox.parent).rstrip("/")
    out = []
    for m in _path_re(home, parent).finditer(text):
        p = m.group(0)
        for pre in ("${HOME}", "$HOME", "~"):
            if p.startswith(pre):
                p = home + p[len(pre):]
                break
        p = p.rstrip(".:")
        if p == sb or p.startswith(sb + "/"):
            continue
        if p == home or p.startswith(home + "/") or re.match(r"/(?:Users|home)/[^/]+", p) or p.startswith(parent + "/"):
            out.append(_short(p, home))
    return out


def merged_calls(parts: list[dict]) -> list[dict]:
    calls = sorted((c for p in parts for c in p["calls"]), key=lambda c: c["ts"] or "")
    for i, c in enumerate(calls, 1):
        c["n"] = i
    return calls


def report_calls(label: str, parts: list[dict], sandbox: Path, stage2: list[str], home: str | None) -> int:
    """Seal order (network and Stage-2 documents), web list, outside paths for one launch.  Returns 0 or 1."""
    status = 0
    calls = merged_calls(parts)
    nets = sorted((n for p in parts for n in p["net"]), key=lambda n: n[0] or "")
    seals = [c for c in calls if c["seal"]]
    seal = seals[-1] if seals else None
    seal_ts = seal["ts"] if seal else None
    first_net = min((n[0] for n in nets if n[0]), default=None)
    where = f" (call {seal['n']} of {len(calls)})" if seal else ""
    if seal_ts and first_net:
        ok = seal_ts <= first_net
        print(f"{label}: seal written {seal_ts}{where}, first network use {first_net} -> "
              f"{'seal precedes the literature' if ok else 'NETWORK USE BEFORE THE SEAL'}")
        status = status if ok else 1
    elif seal_ts:
        print(f"{label}: seal written {seal_ts}{where}, no network use")
    elif first_net:
        print(f"{label}: no seal command found, first network use {first_net}")
    else:
        print(f"{label}: no seal command and no network use")
    if len(seals) > 1:
        print(f"  the seal file was written by {len(seals)} calls ({', '.join(str(c['n']) for c in seals)}); the latest counts")
    if stage2:
        named = [(c, [d for d in stage2 if d in c["text"]]) for c in calls]
        named = [(c, ds) for c, ds in named if ds]
        if seal:
            before = [(c, ds) for c, ds in named if c["n"] < seal["n"]]
            same = [ds for c, ds in named if c["n"] == seal["n"]]
            after = [(c, ds) for c, ds in named if c["n"] > seal["n"]]
            print(f"  calls before the seal naming a Stage-2 document: {len(before)}"
                  + ("" if before else (f"; first after the seal = call {after[0][0]['n']} at {after[0][0]['ts']}" if after else
                                        "; none after it either")))
            for c, ds in before:
                print(f"    STAGE-2 DOCUMENT NAMED BEFORE THE SEAL: call {c['n']} {c['ts']} names {ds}")
            if same:
                print(f"  note: the seal-writing call itself names {same[0]} (read its order in the call)")
            status = 1 if before else status
        else:
            print(f"  no seal command: {len(named)} calls name a Stage-2 document"
                  + (f" (first = call {named[0][0]['n']} at {named[0][0]['ts']})" if named else ""))
    else:
        print("  Stage-2 documents: not given (--stage2 NAME / --stage2-file FILE), the order of the handed-over literature was not checked")
    for ts, kind, value in nets:
        print(f"  {kind:12s} {ts}  {value}")
    outs = [(c, sorted(set(outside_paths(c["text"], sandbox, home)))) for c in calls]
    outs = [(c, ps) for c, ps in outs if ps]
    print(f"  calls naming a path outside the sandbox: {len(outs)}")
    for c, ps in outs[:20]:
        print(f"    call {c['n']} {c['ts']} {c['name']}: {', '.join(ps)}")
    if len(outs) > 20:
        print(f"    … {len(outs) - 20} more")
    denied = [p["denied"] for p in parts if p["denied"] is not None]
    print(f"  permission denials: {sum(denied) if denied else 'n/a'}; tool calls: {len(calls)}")
    return status


def _parse_ts(s: str | None):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def report_effort(info: dict, launch: dict | None) -> None:
    """The three effort records side by side; where they differ, say so without naming one as the effective effort."""
    print("  reasoning effort, three records (none of them alone is the effort the run used; cold-eyes-isolation.md#codex-rollout-receipt (c)):")
    if launch:
        print(f"    launch: model {launch.get('model')} effort {launch.get('effort')} ({launch.get('launched_at') or '?'})")
    else:
        print("    launch: not given (--codex-launch FILE = codex-app-launch.py --json output)")
    print("    thread settings: " + ("; ".join(f"{ts} {e} ({m})" for ts, m, e in info["settings"]) or "none"))
    print("    turn context: " + ("; ".join(f"{ts} turn {tid[:8]} {e} ({m})" for ts, tid, m, e in info["turns"]) or "none"))
    print("    turns started: " + (", ".join(f"{ts} ({tid[:8]})" for ts, tid in info["starts"]) or "none")
          + "; completed: " + (", ".join(f"{ts} ({tid[:8]})" for ts, tid in info["completes"]) or "none"))
    values = {("launch", (launch or {}).get("effort"))} if launch else set()
    values |= {("thread settings", e) for _ts, _m, e in info["settings"]}
    values |= {("turn context", e) for _ts, _tid, _m, e in info["turns"]}
    efforts = {e for _k, e in values if e}
    if len(efforts) <= 1:
        print(f"    the records agree: {next(iter(efforts)) if efforts else 'no effort recorded'}")
        return
    by = collections.defaultdict(list)
    for k, e in sorted(values, key=lambda x: (x[0], str(x[1]))):
        by[k].append(str(e))
    print("    THE RECORDS DIFFER: " + " / ".join(f"{k} {'+'.join(v)}" for k, v in by.items()))
    last_start = _parse_ts(info["starts"][-1][0]) if info["starts"] else None
    last_turn_ctx = _parse_ts(info["turns"][-1][0]) if info["turns"] else None
    for ts, _m, e in info["settings"]:
        t = _parse_ts(ts)
        if last_start and t and t > last_start and not (last_turn_ctx and last_turn_ctx > t):
            ctx = f" and {(t - last_turn_ctx).total_seconds():.0f} s after its turn context" if last_turn_ctx and last_turn_ctx <= t else ""
            print(f"    thread settings {e} at {ts} came {(t - last_start).total_seconds():.0f} s after the last turn started"
                  f" (task_started){ctx}; no turn context follows it: the record does not say whether the running turn used it")


def _key_paths(obj, term: str) -> collections.Counter:
    rx = re.compile(re.escape(term), re.I)
    out = collections.Counter()

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in CIPHER_KEYS:
                    continue
                # a key that is itself data (a skill list keyed by file path) is shown as <key>: paths are not copied
                seg = str(k) if re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", str(k)) else "<key>"
                sub = f"{path}.{seg}" if path else seg
                n = len(rx.findall(str(k)))
                if n:
                    out[sub + " (key)"] += n
                walk(v, sub)
        elif isinstance(o, list):
            for v in o:
                walk(v, path + "[]")
        elif isinstance(o, str):
            n = len(rx.findall(o))
            if n:
                out[path] += n
    walk(obj, "")
    return out


def _len(o) -> int | None:
    return len(o) if isinstance(o, (list, dict)) else None


def report_state(info: dict, terms: list[str], sandbox: Path, home: str | None) -> None:
    """world_state / additional_tools: counts and per-term key paths, never titles or paths."""
    if not info["state"]:
        print("  app state on the turn: no world_state / additional_tools records")
        return
    print(f"  app state on the turn ({len(info['state'])} records; counts and key paths only, cold-eyes-isolation.md#codex-rollout-receipt (b)):")
    for idx, ts, kind, obj in info["state"]:
        p = obj.get("payload") or {}
        counts = []
        if kind == "world_state":
            st = p.get("state") or {}
            prefixes = _len(((st.get("permissions") or {}).get("approved_command_prefixes")))
            if prefixes is not None:
                counts.append(f"approved command prefixes {prefixes}")
            skills = sum(_len((st.get(k) or {}).get("entries")) or 0 for k in ("host_skills", "skills", "cloud_skills")
                         if isinstance(st.get(k), dict))
            if any(isinstance((st.get(k) or {}).get("entries"), dict) for k in ("host_skills", "skills", "cloud_skills")
                   if isinstance(st.get(k), dict)):
                counts.append(f"skill entries {skills}")
            for k in ("tools", "top_level_tools"):
                if _len(st.get(k)) is not None:
                    counts.append(f"{k} {_len(st.get(k))}")
            if isinstance(st.get("agents_md"), dict):
                counts.append("agents_md present")
            label = f"world_state ({'full' if p.get('full') else 'delta'})"
        else:
            counts.append(f"tools {_len(p.get('tools')) or 0}")
            label = "additional_tools"
        paths = set(outside_paths(record_text(obj), sandbox, home))
        counts.append(f"distinct directories outside the sandbox {len(paths)}")
        print(f"    record {idx} {ts} {label}: " + ", ".join(counts))
        for term in terms:
            kp = _key_paths(obj, term)
            if kp:
                print(f"      {term!r}: {sum(kp.values())} in " + ", ".join(f"{k} ×{v}" for k, v in sorted(kp.items())))
    if terms and not any(_key_paths(o, t) for _i, _ts, _k, o in info["state"] for t in terms):
        print("    no contamination term in these records")


def written_files(sandbox: Path, results: Path) -> tuple[list[tuple[str, Path]], list[tuple[str, Path]]]:
    """(result files, other files the reviewer wrote) as (relative path, path).

    In the sandbox itself the split is make-review-sandbox.py's inventory (its ledger, or file times for a sandbox made
    before the ledger, tells inputs from the reviewer's files); in a collected directory every file is the reviewer's."""
    def is_result(rel: str) -> bool:
        parts = rel.split("/")
        return (len(parts) == 1 and (parts[0] in RESULT_ROOT_NAMES or (parts[0].startswith("STAGE") and parts[0].endswith("-RESULTS.md")))
                or parts[0] in RESULT_DIRS)
    msb = _sibling("make-review-sandbox.py")
    if results == sandbox:
        inv = msb.inventory(sandbox, msb.read_ledger(sandbox.parent, sandbox.name))
        rels = inv["results"] + inv["rules"] + inv["outside"] + inv["literature"]
    else:
        rels = []
        for dirpath, dirnames, filenames in os.walk(results):
            d = Path(dirpath)
            # third-party / generated trees are not the reviewer's text (the same names collect skips)
            dirnames[:] = sorted(n for n in dirnames if not msb._is_tree(n) and not (d / n / "pyvenv.cfg").is_file())
            rels += [(d / n).relative_to(results).as_posix() for n in sorted(filenames)]
    res = [(r, results / r) for r in rels if is_result(r)]
    other = [(r, results / r) for r in rels if not is_result(r)]
    return res, other


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


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _status_codex(sandbox: Path, rollouts: list[Path], seal_name: str) -> None:
    for i, r in enumerate(rollouts, 1):
        info = parse_codex(r, seal_name)
        print(f"rollout {i}/{len(rollouts)}: {r.name}  records {info['lines']}  first {info['first']}  last {info['last']}")
        if info["cwd"] is not None:
            print(f"  started in the sandbox: {'yes' if str(info['cwd']).rstrip('/') == str(sandbox) else 'NO'}")
        print("  tool calls: " + (", ".join(f"{k} {v}" for k, v in sorted(info["tools"].items())) or "none"))
        ev = {k: v for k, v in info["events"].items() if k in ("task_started", "task_complete", "turn_aborted", "thread_settings_applied")}
        print("  turn events: " + (", ".join(f"{k} {v}" for k, v in sorted(ev.items())) or "none"))
        tok = info["tokens"] or {}
        if tok:
            print("  tokens so far: " + ", ".join(f"{k} {tok[k]}" for k in ("input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens") if k in tok))


def cmd_status(sandbox: Path, config_dirs: list[Path], seal_name: str, rollouts: list[Path] | None = None) -> int:
    print(f"sandbox: {sandbox}")
    print(f"files: {sandbox_listing(sandbox)}")
    print(f"DONE marker: {'yes' if (sandbox / 'DONE').exists() else 'no'}")
    if rollouts is not None:
        if not rollouts:
            print("no Codex rollout found")
        _status_codex(sandbox, rollouts, seal_name)
        return 0
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


def sandbox_listing(sandbox: Path) -> str:
    parts = []
    for p in sorted(sandbox.iterdir(), key=lambda x: x.name):
        if p.name.startswith("."):
            continue
        parts.append(f"{p.name}/({sum(1 for _ in p.iterdir())})" if p.is_dir() else p.name)
    return ", ".join(parts)


def cmd_receipt(sandbox: Path, results: Path, config_dirs: list[Path], seal: str, sealed: str, terms: list[str],
                context: int = 2, stage2: list[str] | None = None, rollouts: list[Path] | None = None,
                launch: dict | None = None, home: str | None = None) -> int:
    status = 0
    stage2 = list(stage2 or [])
    seal_file, sealed_file = results / seal, results / sealed
    if seal_file.exists() and sealed_file.exists():
        digest = sha256_of(sealed_file)
        ok = digest in seal_file.read_text(encoding="utf-8", errors="replace")
        print(f"seal: sha256({sealed}) {'matches' if ok else 'DOES NOT MATCH'} the value recorded in {seal}  ({digest[:12]}...)")
        status = status if ok else 1
    else:
        print(f"seal: {seal} or {sealed} not found under {results} (single-stage run?)")
    note = sandbox / sealed if (sandbox / sealed).exists() else sealed_file
    if note.exists():
        mode = stat.S_IMODE(note.stat().st_mode)
        print(f"sealed note mode {oct(mode)} in {'the sandbox' if note.parent == (sandbox / sealed).parent else 'the results'}: "
              + ("read-only" if not mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) else "WRITABLE (not made read-only)"))
    seal_name = Path(seal).stem
    texts = []          # (where, [records]) for the contamination counts
    infos = []
    if rollouts is not None:
        if not rollouts:
            print("no Codex rollout found")
        for i, r in enumerate(rollouts, 1):
            info = parse_codex(r, seal_name)
            infos.append(info)
            texts.append(("rollout", info["records"]))
            label = f"rollout {i}/{len(rollouts)} ({r.name})"
            if info["cwd"] is not None and str(info["cwd"]).rstrip("/") != str(sandbox):
                print(f"{label}: NOT STARTED IN THIS SANDBOX (session cwd differs)")
            status = max(status, report_calls(label, [info], sandbox, stage2, home))
            report_state(info, terms, sandbox, home)
            report_effort(info, launch)
    else:
        transcripts = find_transcripts(sandbox, config_dirs)
        for i, t in enumerate(transcripts, 1):
            info = parse(t, seal_name)
            subs = subagent_transcripts(t)
            parts = [info] + [parse(s, seal_name) for s in subs]
            infos += parts
            texts += [("transcript", p["records"]) for p in parts]
            label = f"transcript {i}/{len(transcripts)}" + (f" (+ {len(subs)} subagent transcripts)" if subs else "")
            status = max(status, report_calls(label, parts, sandbox, stage2, home))
    if terms:
        res, other = written_files(sandbox, results)
        res_t = [(r, _read(p)) for r, p in res]
        oth_t = [(r, _read(p)) for r, p in other]
        where = "rollout" if rollouts is not None else "transcript"
        print(f"contamination terms (case-insensitive): term -> result files ({len(res_t)}) / other files the reviewer wrote "
              f"({len(oth_t)}) / {where}")
        for term in terms:
            r_n = sum(count_term(term, t) for _r, t in res_t)
            o_n = sum(count_term(term, t) for _r, t in oth_t)
            tr_n = sum(count_term(term, record_text(o)) for _w, recs in texts for o in recs)
            print(f"  {term!r}: {r_n} / {o_n} / {tr_n}")
            if context > 0:
                for col, files, n in (("result", res_t, r_n), ("other", oth_t, o_n)):
                    shown = 0
                    for rel, text in files:
                        if not n or shown >= context:
                            break
                        for snip in term_contexts(term, text, context - shown):
                            print(f"      {col}[{rel}]: …{snip}…")
                            shown += 1
                shown = 0
                for w, recs in texts:
                    for o in recs:
                        if shown >= context or not tr_n:
                            break
                        kind = is_state_record(o) if w == "rollout" else None
                        txt = record_text(o)
                        if not count_term(term, txt):
                            continue
                        if kind:   # titles and paths of the app state are not copied (counts and key paths only)
                            kp = _key_paths(o, term)
                            print(f"      {w}: (in a {kind} record: " + ", ".join(f"{k} ×{v}" for k, v in sorted(kp.items())) + ")")
                            shown += 1
                            continue
                        for snip in term_contexts(term, txt, context - shown):
                            print(f"      {w}: …{snip}…")
                            shown += 1
            if r_n:
                status = max(status, 2)
    return status


def selftest() -> int:
    import contextlib
    import io

    def line(obj):
        return json.dumps(obj) + "\n"

    def assistant(ts, blocks, stop="tool_use", usage=None):
        return line({"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": blocks, "stop_reason": stop,
                                                                      "usage": usage or {"output_tokens": 10}}})

    def run(fn, *a, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fn(*a, **kw)
        return rc, buf.getvalue()

    cap = {"output_tokens": 64000, "output_tokens_details": {"thinking_tokens": 64000}}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp).resolve()
        home = str(tmp / "home" / "someone")
        sandbox = tmp / "box.one" / "run_a"
        (sandbox / "notes").mkdir(parents=True)
        (sandbox / "notes" / "stage1-blind.md").write_text("blind note\n")
        digest = sha256_of(sandbox / "notes" / "stage1-blind.md")
        (sandbox / "notes" / "stage1-seal.txt").write_text(f"{digest}  notes/stage1-blind.md\n")
        (sandbox / "REVIEW-RESULTS.md").write_text("result mentions SecretTitle once\n")
        cfg = tmp / "cfg"
        proj = cfg / "projects" / slug_candidates(sandbox)[0]
        proj.mkdir(parents=True)
        # --- the seal-writing call is found by the write, not by a mention ---
        assert writes_seal("Write", {"file_path": "/x/notes/stage1-seal.txt"}, "stage1-seal")
        assert not writes_seal("Write", {"file_path": "/x/notes/stage1-blind.md", "content": "then write stage1-seal.txt"}, "stage1-seal")
        assert not writes_seal("Bash", {"command": "ls notes/stage1-seal.txt"}, "stage1-seal")
        assert writes_seal("Bash", {"command": "shasum -a 256 n.md | tee notes/stage1-seal.txt"}, "stage1-seal")
        assert writes_seal("Bash", {"command": "shasum -a 256 n.md > notes/stage1-seal.txt"}, "stage1-seal")
        py_write = "python3 - <<'PY'\\nfrom pathlib import Path\\nimport hashlib\\nh=hashlib.sha256(b'x').hexdigest()\\nPath('notes/stage1-seal.txt').write_text(h)\\nPY"
        assert command_writes_seal(py_write, "stage1-seal")
        assert command_writes_seal('text(await tools.exec_command({cmd:"python3 -c \\"open(\'notes/stage1-seal.txt\', \'w\').write(h)\\""}))', "stage1-seal")
        assert command_writes_seal("p = Path('notes/stage1-seal.txt')\\np.write_text(h)", "stage1-seal")
        assert command_writes_seal("s = sb / 'notes' / 'stage1-seal.txt'\\nwith open(s, mode='w') as f: f.write(h)", "stage1-seal")
        # a later call that only reads or quotes the seal, next to a hash and a heredoc into another file, is not a write
        assert not command_writes_seal("check('seal', EXPECTED in Path('notes/stage1-seal.txt').read_text())\\nh=hashlib.sha256(b).hexdigest()", "stage1-seal")
        assert not command_writes_seal("cat > notes/later.md <<'EOF'\\nThe hash is recorded in `notes/stage1-seal.txt`. sha256 above.\\nEOF", "stage1-seal")
        assert not command_writes_seal("s = Path('notes/stage1-seal.txt').read_text()\\nout.write_text(s)", "stage1-seal")
        # --- outside paths ---
        assert outside_paths(f"cat {sandbox}/notes/a.md ~/work/repo-x/file.md", sandbox, home) == ["~/work/repo-x"]
        assert outside_paths(f"ls {tmp}/box.one/run_b/notes {sandbox}", sandbox, home) == [f"/{'/'.join(Path(tmp, 'box.one', 'run_b').parts[1:4])}"]
        assert outside_paths("echo $HOME/.agentrc and ${HOME}/b/c/d and /usr/bin/python3 and ~0.3", sandbox, home) == ["~/.agentrc", "~/b/c"]
        assert outside_paths("python3 checks/a.py notes/b.md", sandbox, home) == []
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
        assert run(cmd_status, sandbox, [cfg], "stage1-seal")[0] == 0
        args = (sandbox, sandbox, [cfg], "notes/stage1-seal.txt", "notes/stage1-blind.md")
        assert run(cmd_receipt, *args, [], home=home)[0] == 0
        assert run(cmd_receipt, *args, ["secrettitle"], home=home)[0] == 2
        # a transcript hit is shown with its surroundings (the receipt says why it is benign); a result hit too
        rc_ctx, out = run(cmd_receipt, *args, ["kernel", "SecretTitle"], home=home)
        assert rc_ctx == 2 and "transcript: …" in out and "heat kernel review" in out, out
        assert "result[REVIEW-RESULTS.md]: …result mentions SecretTitle once" in out, out
        assert "sealed note mode" in out and "Stage-2 documents: not given" in out and "outside the sandbox: 0" in out, out
        assert term_contexts("a", "xaxbxa", 1) == ["xaxbxa"] and term_contexts("zz", "abc", 2) == []
        # Stage-2 documents: named after the seal = quiet, before it = exit 1 (the Claude run gets the same check)
        rc, out = run(cmd_receipt, *args, [], stage2=["lit2.pdf"], home=home)
        assert rc == 0 and "calls before the seal naming a Stage-2 document: 0; none after it either" in out, out
        early = assistant("T03", [{"type": "tool_use", "name": "Read", "input": {"file_path": f"{sandbox}/lit2.pdf"}}])
        (proj / "a.jsonl").write_text(good.replace(assistant("T03", [{"type": "thinking", "thinking": ""}], stop="max_tokens", usage=cap), early))
        rc, out = run(cmd_receipt, *args, [], stage2=["lit2.pdf"], home=home)
        assert rc == 1 and "STAGE-2 DOCUMENT NAMED BEFORE THE SEAL: call 2 T03" in out, out
        # an outside path is listed, the exit status is not changed
        (proj / "a.jsonl").write_text(good + assistant("T08", [{"type": "tool_use", "name": "Read", "input": {"file_path": f"{home}/work/repo-x/notes.md"}}]))
        rc, out = run(cmd_receipt, *args, [], home=home)
        assert rc == 0 and "outside the sandbox: 1" in out and "~/work/repo-x" in out, out
        # network use before the seal is flagged
        bad = (assistant("T01", [{"type": "tool_use", "name": "WebFetch", "input": {"url": "https://example.org/x"}}])
               + assistant("T02", [{"type": "tool_use", "name": "Write", "input": {"file_path": "notes/stage1-seal.txt", "content": digest}}]))
        (proj / "a.jsonl").write_text(bad)
        assert run(cmd_receipt, *args, [], home=home)[0] == 1
        # a subagent of the launch: its network use enters the seal order, its text the contamination counts
        (proj / "a.jsonl").write_text(good)
        sub = proj / "a" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-x.jsonl").write_text(assistant("T03", [{"type": "tool_use", "name": "WebFetch", "input": {"url": "https://example.org/early"}}])
                                           + assistant("T05", [{"type": "text", "text": "subagent saw HiddenWord"}]))
        assert subagent_transcripts(proj / "a.jsonl") == [sub / "agent-x.jsonl"]
        assert run(cmd_receipt, *args, [], home=home)[0] == 1
        _rc, out = run(cmd_receipt, *args, ["HiddenWord"], home=home)
        _rc2, out2 = run(cmd_status, sandbox, [cfg], "stage1-seal")
        assert "'HiddenWord': 0 / 0 / 1" in out and "(+ 1 subagent transcripts)" in out and "subagents: 1 transcripts" in out2, out
        (sub / "agent-x.jsonl").unlink()
        sub.rmdir(); sub.parent.rmdir()
        # ciphertext fields are not searched
        (proj / "a.jsonl").write_text(good + assistant("T09", [{"type": "thinking", "thinking": "", "signature": "xxHiddenWordxx"}], stop="end_turn"))
        _rc, out = run(cmd_receipt, *args, ["HiddenWord"], home=home)
        assert "'HiddenWord': 0 / 0 / 0" in out, out
        # files: STAGE*-RESULTS.md is a result file (exit 2), scratch/ and other written files are their own column
        (proj / "a.jsonl").write_text(good)
        (sandbox / "scratch").mkdir()
        (sandbox / "scratch" / "extract.txt").write_text("downloaded text by OtherAuthor\n")
        rc, out = run(cmd_receipt, *args, ["OtherAuthor"], home=home)
        assert rc == 0 and "'OtherAuthor': 0 / 1 / 0" in out and "other[scratch/extract.txt]: …downloaded text by OtherAuthor" in out, out
        (sandbox / "STAGE2-RESULTS.md").write_text("stage two cites OtherAuthor\n")
        rc, out = run(cmd_receipt, *args, ["OtherAuthor"], home=home)
        assert rc == 2 and "'OtherAuthor': 1 / 1 / 0" in out, out
        collected = tmp / "collected"
        (collected / "outside-rules").mkdir(parents=True)
        (collected / "REVIEW-RESULTS.md").write_text("clean\n")
        (collected / "outside-rules" / "x.md").write_text("OtherAuthor again\n")
        (collected / "__pycache__").mkdir()
        (collected / "__pycache__" / "y.pyc").write_text("OtherAuthor")
        res, oth = written_files(sandbox, collected)
        assert [r for r, _p in res] == ["REVIEW-RESULTS.md"] and [r for r, _p in oth] == ["outside-rules/x.md"], (res, oth)
        (sandbox / "STAGE2-RESULTS.md").unlink()
        (sandbox / "scratch" / "extract.txt").unlink()
        (sandbox / "scratch").rmdir()
        # a modified sealed note is flagged; a writable note is said to be writable
        (sandbox / "notes" / "stage1-blind.md").write_text("edited after the seal\n")
        rc, out = run(cmd_receipt, *args, [], home=home)
        assert rc == 1 and "WRITABLE" in out, out
        (sandbox / "notes" / "stage1-blind.md").write_text("blind note\n")
        os.chmod(sandbox / "notes" / "stage1-blind.md", 0o444)
        rc, out = run(cmd_receipt, *args, [], home=home)
        assert rc == 0 and "mode 0o444 in the sandbox: read-only" in out, out
        # a single capped response is a note, not a loop
        (proj / "a.jsonl").write_text(assistant("T02", [{"type": "thinking", "thinking": ""}], stop="max_tokens", usage=cap)
                                      + assistant("T03", [{"type": "text", "text": "ok"}], stop="end_turn"))
        one = parse(proj / "a.jsonl", "stage1-seal")
        assert one["thinking_only_cap"] == 1 and one["max_consecutive_thinking_cap"] == 1

        # --- a Codex app rollout (synthetic: every name, path and word below is made up) ---
        def rec(ts, typ, payload):
            return line({"timestamp": ts, "type": typ, "payload": payload})

        def call(ts, cmd):
            return rec(ts, "response_item", {"type": "custom_tool_call", "name": "exec", "call_id": "c",
                                             "input": "text(await tools.exec_command(" + json.dumps({"cmd": cmd}) + "));\n"})

        tid = "0abc1234-5678-90de-f123-456789abcdef"
        codex_home = tmp / "codexhome"
        day = codex_home / "sessions" / "2030" / "01" / "02"
        day.mkdir(parents=True)
        rollout = day / f"rollout-2030-01-02T03-04-05-{tid}.jsonl"
        seal_cmd = ("python3 - <<'PY'\nfrom pathlib import Path\nimport hashlib\np=Path('notes/stage1-blind.md')\n"
                    "h=hashlib.sha256(p.read_bytes()).hexdigest()\nPath('notes/stage1-seal.txt').write_text(h)\nPY")
        world = {"full": True, "state": {"agents_md": {"directory": f"{home}/elsewhere", "text": "rules naming PrivateRepoWord"},
                                         "permissions": {"approved_command_prefixes": [[f"{home}/work/repo-y/tool.py"], ["git", "status"]]},
                                         "host_skills": {"entries": {"a": {}, f'["host","{home}/work/repo-w/skill/SKILL.md"]': {}}},
                                         "top_level_tools": {"functions.exec": "h"}}}
        rows = [rec("2030-01-02T00:00:00.000Z", "session_meta", {"cwd": str(sandbox), "id": tid}),
                rec("2030-01-02T00:00:00.100Z", "world_state", world),
                rec("2030-01-02T00:00:00.200Z", "response_item", {"type": "additional_tools", "tools": [{"name": "t1"}, {"name": "t2"}]}),
                rec("2030-01-02T00:00:00.300Z", "turn_context", {"turn_id": "turn-aaaa1111", "model": "model-x", "effort": "high"}),
                rec("2030-01-02T00:00:00.400Z", "event_msg", {"type": "thread_settings_applied", "thread_settings": {"model": "model-x", "reasoning_effort": "high"}}),
                rec("2030-01-02T00:00:03.000Z", "event_msg", {"type": "task_started", "turn_id": "turn-aaaa1111"}),
                rec("2030-01-02T00:00:07.000Z", "event_msg", {"type": "thread_settings_applied", "thread_settings": {"model": "model-x", "reasoning_effort": "xhigh"}}),
                call("2030-01-02T00:00:10.000Z", "pwd && cat AGENTS.md"),
                rec("2030-01-02T00:00:11.000Z", "response_item", {"type": "reasoning", "encrypted_content": "zzHiddenWordzz", "summary": []}),
                call("2030-01-02T00:01:00.000Z", seal_cmd),
                call("2030-01-02T00:01:20.000Z", "pdftotext lit2.pdf scratch/lit2.txt"),
                call("2030-01-02T00:01:30.000Z", f"head ~/work/repo-z/README.md; curl -s https://example.org/x"),
                call("2030-01-02T00:02:00.000Z", "python3 - <<'PY'\nfrom pathlib import Path\nassert H in Path('notes/stage1-seal.txt').read_text()\nimport hashlib\nPY"),
                rec("2030-01-02T00:02:10.000Z", "response_item", {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "done, HiddenWord once"}]}),
                rec("2030-01-02T00:02:20.000Z", "event_msg", {"type": "task_complete", "turn_id": "turn-aaaa1111"}),
                rec("2030-01-02T00:02:21.000Z", "event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12}}})]
        rollout.write_text("".join(rows))
        assert find_codex_rollouts(tid, codex_home) == [rollout] and find_codex_rollouts(str(rollout), codex_home) == [rollout]
        assert find_codex_rollouts("nothing-like-this", codex_home) == []
        ci = parse_codex(rollout, "stage1-seal")
        assert ci["tools"] == {"exec": 5} and ci["seal_ts"] == "2030-01-02T00:01:00.000Z", (ci["tools"], ci["seal_ts"])
        assert [c["seal"] for c in ci["calls"]] == [False, True, False, False, False]
        launch = {"thread_id": tid, "model": "model-x", "effort": "high", "launched_at": "2030-01-02T00:00:00Z"}
        cx = (sandbox, sandbox, [cfg], "notes/stage1-seal.txt", "notes/stage1-blind.md")
        rc, out = run(cmd_receipt, *cx, ["PrivateRepoWord", "HiddenWord", "repo-y"], stage2=["lit2.pdf"], rollouts=[rollout], launch=launch, home=home)
        assert rc == 0, out
        assert "seal written 2030-01-02T00:01:00.000Z (call 2 of 5)" in out and "NETWORK USE BEFORE" not in out, out
        assert "calls before the seal naming a Stage-2 document: 0; first after the seal = call 3" in out, out
        assert "network-like" in out and "example.org" in out, out
        assert "outside the sandbox: 1" in out and "call 4 2030-01-02T00:01:30.000Z exec: ~/work/repo-z" in out, out
        assert "approved command prefixes 2" in out and "skill entries 2" in out and "tools 2" in out, out
        assert "'PrivateRepoWord': 1 in payload.state.agents_md.text ×1" in out, out
        assert "'repo-y': 1 in payload.state.permissions.approved_command_prefixes[][] ×1" in out, out
        # the app state's paths and text are never printed, also not as the context of a rollout hit
        assert "repo-y/tool.py" not in out and "rules naming" not in out and "elsewhere" not in out, out
        _rc, out_w = run(cmd_receipt, *cx, ["repo-w"], rollouts=[rollout], home=home)
        assert "'repo-w': 1 in payload.state.host_skills.entries.<key> (key) ×1" in out_w and "SKILL.md" not in out_w, out_w
        assert "rollout: (in a world_state record: payload.state.agents_md.text ×1)" in out, out
        assert "'HiddenWord': 0 / 0 / 1" in out and "rollout: …" in out, out          # the encrypted reasoning is not counted
        assert "launch: model model-x effort high" in out and "THE RECORDS DIFFER" in out, out
        assert ("thread settings xhigh at 2030-01-02T00:00:07.000Z came 4 s after the last turn started (task_started)"
                " and 7 s after its turn context; no turn context follows it") in out, out
        assert "the effort the run used" in out and "effective effort is" not in out, out
        # records that agree say so
        agree = rollout.read_text().replace('"reasoning_effort": "xhigh"', '"reasoning_effort": "high"')
        rollout.write_text(agree)
        rc, out = run(cmd_receipt, *cx, [], rollouts=[rollout], launch=launch, home=home)
        assert "the records agree: high" in out and "DIFFER" not in out, out
        # a Stage-2 document named before the seal (in a Codex run) is exit 1
        rollout.write_text("".join(rows[:8] + [call("2030-01-02T00:00:20.000Z", "pdftotext lit2.pdf /dev/stdout | head")] + rows[8:]))
        rc, out = run(cmd_receipt, *cx, [], stage2=["lit2.pdf"], rollouts=[rollout], home=home)
        assert rc == 1 and "STAGE-2 DOCUMENT NAMED BEFORE THE SEAL: call 2 2030-01-02T00:00:20.000Z names ['lit2.pdf']" in out, out
        # network-like tokens before the seal are exit 1; a rollout started elsewhere is said to be
        rollout.write_text("".join(rows[:8] + [call("2030-01-02T00:00:20.000Z", "python3 -c 'import urllib.request'")] + rows[8:]))
        assert run(cmd_receipt, *cx, [], rollouts=[rollout], home=home)[0] == 1
        rollout.write_text("".join(rows[:8] + [call("2030-01-02T00:00:20.000Z", "python3 -c 'from urllib.parse import unquote'")] + rows[8:]))
        assert run(cmd_receipt, *cx, [], rollouts=[rollout], home=home)[0] == 0      # string handling is not network use
        rollout.write_text("".join([rec("2030-01-02T00:00:00.000Z", "session_meta", {"cwd": str(tmp / "other"), "id": tid})] + rows[1:]))
        _rc, out = run(cmd_receipt, *cx, [], rollouts=[rollout], home=home)
        assert "NOT STARTED IN THIS SANDBOX" in out, out
        rc, out = run(cmd_status, sandbox, [cfg], "stage1-seal", rollouts=[rollout])
        assert rc == 0 and "tool calls: exec 5" in out and "task_complete 1" in out and "total_tokens 12" in out, out
        assert "started in the sandbox: NO" in out and seal_cmd[:20] not in out, out
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
    ap.add_argument("--terms-file", type=Path, action="append", default=[], help="one term per line (# comments), repeatable")
    ap.add_argument("--stage2", action="append", default=[],
                    help="receipt: a Stage-2 document's file name; a call naming it before the seal fails the order check (repeatable)")
    ap.add_argument("--stage2-file", type=Path, default=None, help="receipt: Stage-2 document names, one per line (# comments)")
    ap.add_argument("--codex-rollout", action="append", default=None,
                    help="read a Codex app rollout (thread id or path, repeatable) instead of the Claude transcripts")
    ap.add_argument("--codex-launch", type=Path, default=None,
                    help="codex-app-launch.py --json output: the launch's model and effort, and the thread id when --codex-rollout is not given")
    ap.add_argument("--codex-home", type=Path, default=None, help="default: $CODEX_HOME or ~/.codex")
    ap.add_argument("--context", type=int, default=2,
                    help="receipt: show the first N places of each hit with surrounding text, so the receipt can say why a hit is benign (0 = counts only)")
    args = ap.parse_args(argv)
    sandbox = args.sandbox.expanduser().resolve()
    if not sandbox.is_dir():
        print(f"not a directory: {sandbox}", file=sys.stderr)
        return 1
    config_dirs = [c.expanduser() for c in args.config_dir] if args.config_dir else default_config_dirs()
    launch = json.loads(args.codex_launch.read_text(encoding="utf-8")) if args.codex_launch else None
    rollouts = None
    tokens = list(args.codex_rollout or []) or ([launch["thread_id"]] if launch and launch.get("thread_id") else [])
    if tokens:
        codex_home = (args.codex_home or default_codex_home()).expanduser()
        rollouts = []
        for tok in tokens:
            found = find_codex_rollouts(tok, codex_home)
            if not found:
                print(f"no Codex rollout for {tok!r} under {codex_home} (sessions/, archived_sessions/)", file=sys.stderr)
                return 1
            rollouts += found
        rollouts = list(dict.fromkeys(rollouts))
    if args.command == "status":
        return cmd_status(sandbox, config_dirs, Path(args.seal).stem, rollouts=rollouts)
    terms = list(args.term)
    for tf in args.terms_file:
        terms += [t.strip() for t in tf.read_text(encoding="utf-8").splitlines() if t.strip() and not t.startswith("#")]
    stage2 = list(args.stage2)
    if args.stage2_file:
        stage2 += [t.strip() for t in args.stage2_file.read_text(encoding="utf-8").splitlines() if t.strip() and not t.startswith("#")]
    results = (args.results or sandbox).expanduser().resolve()
    return cmd_receipt(sandbox, results, config_dirs, args.seal, args.sealed, terms, context=args.context,
                       stage2=stage2, rollouts=rollouts, launch=launch)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
