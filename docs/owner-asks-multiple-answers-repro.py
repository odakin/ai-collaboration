#!/usr/bin/env python3
"""Reproduce the owner-asks baseline with synthetic questions and a temporary ledger."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import tempfile


QUESTIONS = {
    "Q1": "資料の並びを日付順にする",
    "Q2": "見出しを短くする",
    "Q3": "別表を一枚にまとめる",
}
SESSION = "synthetic-owner-asks"


def append_json(path, row):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def reproduce(engine, directory):
    ledger = directory / "asks.jsonl"
    transcript = directory / "conversation.jsonl"
    os.environ["BOARD_ASKS_STATE_DIR"] = str(directory / "state")
    for label, question in QUESTIONS.items():
        append_json(ledger, {"type": "ask", "label": label, "text": question,
                             "session": SESSION, "ground": "choice"})
    data = {"session_id": SESSION, "transcript_path": str(transcript)}

    def message(kind, words):
        append_json(transcript, {"type": kind, "message": {"content": words}})

    message("user", "一覧を見せて")
    message("assistant", "\n\n".join(f"{question}？ 〔問 {label}〕" for label, question in QUESTIONS.items()))
    reading = "、".join(f"{question} ({label})" for label, question in QUESTIONS.items())
    reading += "への答えと読みました。よいですか"
    labels = list(QUESTIONS)
    short_group = "全部おすすめでいい"
    cases = [
        ("それで", True, "それで"),
        (short_group, False, short_group),
        ("全部おすすめどおりで進めていい", False, short_group),
        ("はい。お願いします。", True, short_group),
        ("yoi", False, short_group),
    ]
    for index, (words, confirms, pending_words) in enumerate(cases):
        if index:
            message("assistant", reading)
        engine.hook_prompt(directory, dict(data, prompt=words), path=ledger)
        assert engine.is_confirm(words) == confirms, words
        records = engine.load(ledger)
        guess = engine.pending_guess(records, SESSION)
        assert guess and guess["quote"] == pending_words and guess["candidates"] == labels, words
        assert all(ask["status"] == "open" for ask in engine.state(records).values()), words
        deny = engine.hook_pretool(directory, dict(data, tool_name="SendMessage", tool_input={}), path=ledger)
        assert deny, words
        print(f"{words!r}: confirmation={confirms}, pending={pending_words!r}, open={len(labels)}, stopped=True")
        message("user", words)

    unrecognized = engine.bind("全部おすすめどおりで進めていい", labels, [], labels)
    assert unrecognized["binding"] == "none", unrecognized
    direct = engine.bind("全部おすすめで", labels, [], labels)
    assert direct["binding"] == "order" and direct["labels"] == labels, direct
    print("Without a pending guess, the displayed list binds directly:", direct["labels"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_engine = Path(__file__).resolve().parents[1] / "board" / "board_asks.py"
    parser.add_argument("--engine", type=Path, default=default_engine, help="path to the baseline board_asks.py")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("board_asks_baseline", args.engine.resolve())
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    with tempfile.TemporaryDirectory(prefix="owner-asks-repro-") as directory:
        reproduce(engine, Path(directory))


if __name__ == "__main__":
    main()
