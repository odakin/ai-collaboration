#!/usr/bin/env python3
"""board-session-start.py — SessionStart hook: workspace の掲示板で要注意の thread を新しい session の冒頭に出す (無ければ沈黙、 封じた review sandbox の中では沈黙、 fail-open).

配線は owner の private layer に置く (hook の配線は instance = kernel-up / instance-down):

    ~/.claude/settings.json
    "SessionStart": [{"matcher": "startup|resume|clear", "hooks": [{"type": "command",
        "command": "python3 <ai-collaboration>/board/board-session-start.py", "timeout": 30}]}]

`board-view.py --all-boards --sync --surface` を workspace (AGENT_BOARD_WORKSPACE、 無ければこの engine の checkout
の親) に対して走らせ、 Claude Code の hook JSON を出す: 人に見せる 1 行 (`systemMessage`) と、 model に渡す
要注意 thread の一覧 (`additionalContext`)。 要注意の thread が無ければ何も出さない。

意図して黙る場合:
- AGENT_BOARD_SESSION_START=0 (1 回の起動、 または 1 台の machine で止める)。
- session の cwd が封じた review sandbox の中 (`# Isolated review sandbox` で始まる CLAUDE.md が cwd かその祖先に
  ある = scripts/make-review-sandbox.py が書くもの)。 掲示板の要約は conventions/cold-eyes-isolation.md の
  汚染経路 (b) になる。

Usage:
  board-session-start.py [--workspace DIR] [--no-sync] [--timeout SEC]   # hook payload を stdin から読む
  board-session-start.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
SANDBOX_HEAD = "# Isolated review sandbox"   # scripts/make-review-sandbox.py の CLAUDE_MD の 1 行目 (selftest が照合)
THREAD_RE = re.compile(r"\b[\w.-]+/\d{4}-\d{2}-\d{2}-[\w.-]+")   # <project>/<yyyy-mm-dd>-<slug>


def in_sealed_sandbox(cwd) -> bool:
    """cwd かその祖先に、 make-review-sandbox.py が書いた CLAUDE.md があるか。"""
    if not cwd:
        return False
    p = Path(cwd).expanduser()
    for d in (p, *p.parents):
        try:
            head = (d / "CLAUDE.md").read_text(encoding="utf-8", errors="replace").lstrip()
        except OSError:
            continue
        if head.startswith(SANDBOX_HEAD):
            return True
    return False


def count_threads(text: str) -> int:
    """surface の text に出た thread の数 (1 thread に複数行 = 依頼行と claim 行、 があっても 1 と数える)。"""
    tops = [l for l in text.splitlines() if l.strip() and not l.startswith((" ", "📋"))]
    return len({m for l in tops for m in THREAD_RE.findall(l)}) or len(tops)


def hook_output(text: str | None, error: str | None) -> dict | None:
    if error is not None:
        return {"systemMessage": "掲示板: 確認に失敗",
                "hookSpecificOutput": {"hookEventName": "SessionStart",
                                       "additionalContext": f"[掲示板] session 開始時の確認に失敗した: {error}"}}
    text = (text or "").strip()
    if not text:
        return None
    return {"systemMessage": f"掲示板: 要注意 {count_threads(text)} thread",
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": (
                "[掲示板] session 開始時に確認した要注意 thread (board-view.py --all-boards --surface):\n"
                f"{text}\n"
                "最初の返答の冒頭で、 誰の番で何が動いているかを 1 行で人に伝える。 "
                "掲示板の読み書きが要るときは、 人に command を渡さず board.py で代わりに行う。")}}


def run_view(workspace, sync: bool, timeout: float) -> str:
    cmd = [sys.executable, str(ENGINE / "board-view.py"), "--all-boards", "--surface"]
    if sync:
        cmd.append("--sync")
    if workspace:
        cmd += ["--workspace", str(workspace)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()
        raise RuntimeError(tail[-1] if tail else f"board-view.py exit {p.returncode}")
    return p.stdout


def read_payload(stream) -> dict:
    try:
        if stream.isatty():
            return {}
        data = json.loads(stream.read() or "{}")
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _selftest() -> int:
    # 1. sandbox の見分け: 目印は make-review-sandbox.py の CLAUDE_MD と同じ文字列 (片方だけ変わると黙らなくなる)
    src = (ENGINE.parent / "scripts" / "make-review-sandbox.py").read_text(encoding="utf-8")
    assert f'CLAUDE_MD = """{SANDBOX_HEAD}' in src, "SANDBOX_HEAD drifted from make-review-sandbox.py"
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        sb, plain, other = t / "sb", t / "plain", t / "other"
        (sb / "scratch" / "deep").mkdir(parents=True)
        plain.mkdir()
        other.mkdir()
        (sb / "CLAUDE.md").write_text(SANDBOX_HEAD + "\n\nThis directory is a sealed sandbox.\n")
        (other / "CLAUDE.md").write_text("# An ordinary project\n")
        assert in_sealed_sandbox(sb) and in_sealed_sandbox(sb / "scratch" / "deep")
        assert not in_sealed_sandbox(plain) and not in_sealed_sandbox(other) and not in_sealed_sandbox(None)

    # 2. 数え方: 1 thread の 2 行は 1、 別 thread は別
    sample = ("📋 demo — 要注意 thread:\n"
              "📨 codex / role-demo-x 対応待ち [作業中] demo/2026-01-02-alpha — 成果物を作り、提出する\n"
              "    詳細\n"
              "🟢 claim  demo/2026-01-02-alpha — codex@host lease→2026-01-03T00:00:00Z\n"
              "🟢 claim  demo/2026-01-05-beta.v2 — claude@host lease→2026-01-06T00:00:00Z\n")
    assert count_threads(sample) == 2, count_threads(sample)
    assert count_threads("🔴 demo: unreadable\n") == 1

    # 3. 出力の形: 空は沈黙、 失敗は fail-open で 1 行、 thread ありは SessionStart の context
    assert hook_output("", None) is None and hook_output(None, None) is None
    bad = hook_output(None, "timeout")
    assert bad["systemMessage"] == "掲示板: 確認に失敗" and "timeout" in bad["hookSpecificOutput"]["additionalContext"]
    ok = hook_output(sample, None)
    assert ok["systemMessage"] == "掲示板: 要注意 2 thread"
    assert ok["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "demo/2026-01-05-beta.v2" in ok["hookSpecificOutput"]["additionalContext"]

    # 4. 本物の engine を通す: 空の掲示板は沈黙、 claim を 1 件置くと 1 thread
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        root = ws / "demo" / "board"
        root.mkdir(parents=True)
        (root / "board.json").write_text(json.dumps({"board_format": 1, "audience": "owner", "encryption": "none"}))
        subprocess.run(["git", "init", "-q", "-b", "main", str(ws / "demo")], check=True)
        env = {k: v for k, v in os.environ.items() if k not in ("AGENT_BOARD_WORKSPACE", "AGENT_BOARD_PATH_BASE")}
        old = os.environ.copy()
        os.environ.clear()
        os.environ.update(env)
        try:
            assert hook_output(run_view(ws, False, 60), None) is None
            subprocess.run([sys.executable, str(ENGINE / "board-view.py"), "--root", str(root), "--template", "claim",
                            "--thread", "2026-01-02-alpha", "--project", "demo", "--task", "selftest", "--write"],
                           check=True, capture_output=True)
            out = hook_output(run_view(ws, False, 60), None)
        finally:
            os.environ.clear()
            os.environ.update(old)
        assert out and out["systemMessage"] == "掲示板: 要注意 1 thread", out
        assert "demo/2026-01-02-alpha" in out["hookSpecificOutput"]["additionalContext"]
    print("board-session-start selftest: ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", type=Path, help="checkout を並べた directory (既定: AGENT_BOARD_WORKSPACE、 無ければ engine の親)")
    ap.add_argument("--no-sync", action="store_true", help="remote でなく手元の checkout を読む")
    ap.add_argument("--timeout", type=float, default=25.0, help="board-view.py の上限秒 (hook の timeout より短く)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if os.environ.get("AGENT_BOARD_SESSION_START", "1") == "0":
        return 0
    payload = read_payload(sys.stdin)
    if in_sealed_sandbox(payload.get("cwd") or os.getcwd()):
        return 0
    try:
        text, error = run_view(a.workspace, not a.no_sync, a.timeout), None
    except (OSError, subprocess.SubprocessError, RuntimeError) as ex:
        text, error = None, str(ex)
    out = hook_output(text, error)
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
