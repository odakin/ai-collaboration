#!/usr/bin/env python3
"""Check the installed owner-asks hook with its default config and a temporary ledger."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


QUESTIONS = {
    "Q1": "資料を日付順に並べるか",
    "Q2": "見出しを短くするか",
    "Q3": "別表を一枚にまとめるか",
}
SESSION = "owner-asks-installed-smoke"
ANSWER = "全部おすすめで"
CONFIRMATION = "yoi"


def append_json(path, record):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def check_hook(hook, directory):
    engine = Path(__file__).resolve().parents[1] / "board" / "board_asks.py"
    ledger, transcript = directory / "ledger.jsonl", directory / "turns.jsonl"
    env = dict(os.environ, BOARD_ASKS_LEDGER=str(ledger), BOARD_ASKS_STATE_DIR=str(directory / "state"),
               PYTHONDONTWRITEBYTECODE="1")
    for name in ("BOARD_ASKS_ENGINE", "BOARD_ASKS_CONFIG", "BOARD_ASKS_VALIDATOR", "BOARD_ASKS_PREFIX"):
        env.pop(name, None)

    def message(role, content):
        append_json(transcript, {"type": role, "message": {"role": role, "content": content}})

    def engine_command(*args):
        return subprocess.check_output(
            [sys.executable, "-B", str(engine), *args, "--session", SESSION],
            env=env, encoding="utf-8", timeout=20,
        ).strip()

    def event(kind, **fields):
        payload = dict(hook_event_name=kind, session_id=SESSION, transcript_path=str(transcript), **fields)
        result = subprocess.run(["bash", str(hook)], env=env, input=json.dumps(payload), encoding="utf-8",
                                capture_output=True, check=True, timeout=20)
        return result.stdout.strip()

    def context(kind, **fields):
        output = event(kind, **fields)
        return json.loads(output)["hookSpecificOutput"] if output else {}

    for label, topic in QUESTIONS.items():
        append_json(ledger, dict(type="ask", label=label, text=topic, recommend="この案で進める",
                                ground="choice", groupable=True, session=SESSION))
    opened = context("SessionStart").get("additionalContext", "")
    assert all(topic in opened for topic in QUESTIONS.values()), "The installed hook did not load the test ledger."
    message("user", "一覧を見せて")
    message("assistant", engine_command("list", "--open", "--block"))
    assert "結び先が決まらない" in context("UserPromptSubmit", prompt=ANSWER).get("additionalContext", "")
    message("user", ANSWER)
    message("assistant", engine_command("group-reading"))
    assert "確かめた読み" in context("UserPromptSubmit", prompt=CONFIRMATION).get("additionalContext", "")
    message("user", CONFIRMATION)

    answers = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    settled = [record for record in answers if record.get("binding") == "confirmed"]
    assert len(settled) == 1 and settled[0]["labels"] == list(QUESTIONS), settled
    assert settled[0]["quote"] == ANSWER and settled[0]["confirm"] == CONFIRMATION, settled
    before = event("PreCompact", trigger="auto")
    assert all(f"{label}: {topic} (answered)" in before for label, topic in QUESTIONS.items()), before
    restored = context("SessionStart", source="compact").get("additionalContext", "")
    for label, topic in QUESTIONS.items():
        expected = f"{topic} ({label}) → 本人「{ANSWER}」 (確かめ「{CONFIRMATION}」)"
        assert expected in restored, restored
    denied = context("PreToolUse", tool_name="mcp__gmail-test__send_email", tool_input={})
    assert denied.get("permissionDecision") == "deny", denied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", type=Path, default=Path.home() / ".claude" / "hooks" / "owner-asks.sh",
                        help="installed owner-asks hook (default: %(default)s)")
    args = parser.parse_args()
    hook = args.hook.expanduser()
    if not hook.is_file():
        parser.error(f"installed hook not found: {hook}")
    with tempfile.TemporaryDirectory(prefix="owner-asks-installed-smoke-") as directory:
        check_hook(hook, Path(directory))
    print("Installed hook: three answers confirmed and recovered; same-turn send denied.")


if __name__ == "__main__":
    main()
