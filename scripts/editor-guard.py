#!/usr/bin/env python3
"""著者が editor で同じ原稿を開いている日の書き込みと commit の保護: 未 commit 変更を exit code で止め (check)、自分が書いた直後の内容を記録し (mark)、commit の直前にその後の保存を検出し (verify)、読んだ差分と同じ hash のときだけ著者の変更を commit する (carrier)。

edit-intent-record.md §7 の規則 7 (carrier は確認した差分と hash で照合) と 規則 9 (書き込みと commit を、それぞれ
exit code の検査と同じ command 行に置く) を 1 本にした道具。

Usage:
  editor-guard.py check   <file> [--repo DIR]            # exit 0 = 未 commit 変更なし (書いてよい)
                                                         # exit 3 = 変更あり: 差分を表示し、その hash を保存して止まる
  editor-guard.py mark    <file> [--repo DIR]            # 自分が書いた直後の内容を記録する (exit 0)
  editor-guard.py verify  <file> [--repo DIR]            # exit 0 = mark のあと誰も保存していない (commit してよい)
                                                         # exit 4 = mark のあとに着地した差分を表示して止まる
                                                         # exit 5 = mark がない
  editor-guard.py carrier <file> -m MSG [--repo DIR] [--push]
                                                         # check で表示した差分と今の差分の hash が同じときだけ
                                                         # `git commit -m MSG -- <file>` (と push)。違えば exit 4、
                                                         # check を経ていなければ exit 5 で、何も commit しない
  editor-guard.py --selftest

使い方の型 (書き込みと commit を、それぞれ検査と同じ command 行に置く):
  1. `editor-guard.py check paper.tex && <自分の書き込み> && editor-guard.py mark paper.tex`
     exit 3 なら鎖が止まって何も書かない。表示された差分を読み、著者の編集として妥当なら 4 へ。
  2. 組版・記録など、paper.tex に触らない作業。
  3. `editor-guard.py verify paper.tex && git commit -m MSG -- paper.tex`
     mark のあとに誰かが保存していれば exit 4 で鎖が止まり、あとから着地した差分を表示する。
     そのとき file には自分の編集とその差分が両方入っている。誰の変更かを記録してから、両方を
     その帰属つきで commit するか、あとの差分を分けて carrier する (道具は自動で分けない)。
  4. (1 が exit 3 のとき) `editor-guard.py carrier paper.tex -m "Author's hand edits (...)" --push`
     → 読んだ差分と同じなら commit。読んだ後にさらに編集が着地していれば exit 4 で止まるので、1 からやり直す。

破られ方 (2026-09-13 実測、3 回):
  - `git status --short <file> && 編集 && commit` は変更があっても exit 0 なので止まらず、著者の編集が自分の
    commit message の commit に入った (2 回)。gate は表示ではなく exit code で判定する。
  - `check` を編集と別の tool 呼び出しにした版では、check (exit 0) と次の呼び出しの書き込みの間に著者が保存し、
    同じことが起きた (1 回)。検査と書き込みの間に時間を空けない。書き込みから commit までの組版・記録の時間も
    同じ窓なので、commit の直前に verify を置く。
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def _state_path(repo: Path, rel: str) -> Path:
    git_dir = Path(_git(repo, "rev-parse", "--absolute-git-dir").stdout.strip())
    slug = rel.replace(os.sep, "__").replace("/", "__")
    return git_dir / "editor-guard" / f"{slug}.sha256"


def _mark_paths(repo: Path, rel: str) -> tuple[Path, Path]:
    base = _state_path(repo, rel)
    return base.with_suffix(".written"), base.with_suffix(".written-sha256")


def _diff(repo: Path, rel: str) -> str:
    return _git(repo, "diff", "--no-color", "--", rel).stdout


def _rel(repo: Path, file: str) -> str:
    p = Path(file)
    if p.is_absolute():
        return str(p.resolve().relative_to(repo.resolve()))
    cand = (Path.cwd() / p).resolve()
    try:
        return str(cand.relative_to(repo.resolve()))
    except ValueError:
        return file


def _tracked(repo: Path, rel: str) -> bool:
    if _git(repo, "ls-files", "--error-unmatch", "--", rel, check=False).returncode == 0:
        return True
    print(f"✗ [editor-guard] not a tracked file in {repo}: {rel}", file=sys.stderr)
    return False


def cmd_check(repo: Path, file: str) -> int:
    rel = _rel(repo, file)
    if not _tracked(repo, rel):
        return 2
    diff = _diff(repo, rel)
    state = _state_path(repo, rel)
    if not diff:
        for p in (state, *_mark_paths(repo, rel)):
            if p.exists():
                p.unlink()
        print(f"✓ [editor-guard] {rel}: no uncommitted change")
        return 0
    state.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    state.write_text(digest + "\n", encoding="utf-8")
    print(diff, end="" if diff.endswith("\n") else "\n")
    print(f"✗ [editor-guard] {rel}: uncommitted change present (diff sha256 {digest[:12]}). "
          f"Read the diff above; if it is the author's edit, run `carrier` with the same file. Do not edit yet.")
    return 3


def cmd_mark(repo: Path, file: str) -> int:
    rel = _rel(repo, file)
    if not _tracked(repo, rel):
        return 2
    copy, sha = _mark_paths(repo, rel)
    data = (repo / rel).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(data)
    sha.write_text(digest + "\n", encoding="utf-8")
    print(f"✓ [editor-guard] {rel}: marked as written (sha256 {digest[:12]}); "
          f"commit with `verify && git commit` on one command line")
    return 0


def cmd_verify(repo: Path, file: str) -> int:
    rel = _rel(repo, file)
    if not _tracked(repo, rel):
        return 2
    copy, sha = _mark_paths(repo, rel)
    if not (copy.exists() and sha.exists()):
        print(f"✗ [editor-guard] {rel}: no mark; run `mark` right after your write, on the same command line.",
              file=sys.stderr)
        return 5
    marked = sha.read_text(encoding="utf-8").strip()
    data = (repo / rel).read_bytes()
    now = hashlib.sha256(data).hexdigest()
    if now == marked:
        print(f"✓ [editor-guard] {rel}: unchanged since mark ({now[:12]})")
        return 0
    old = copy.read_bytes().decode("utf-8", "replace").splitlines(keepends=True)
    new = data.decode("utf-8", "replace").splitlines(keepends=True)
    sys.stdout.writelines(difflib.unified_diff(old, new, f"{rel} (marked)", f"{rel} (now)"))
    print(f"\n✗ [editor-guard] {rel}: changed after mark ({marked[:12]} -> {now[:12]}). The lines above landed "
          f"after your write. Nothing verified: the file holds your edit and this later change. Record whose change "
          f"it is before any commit.", file=sys.stderr)
    return 4


def cmd_carrier(repo: Path, file: str, message: str, push: bool) -> int:
    rel = _rel(repo, file)
    state = _state_path(repo, rel)
    if not state.exists():
        print(f"✗ [editor-guard] {rel}: no diff has been shown by `check`; run `check` first and read the diff.",
              file=sys.stderr)
        return 5
    shown = state.read_text(encoding="utf-8").strip()
    diff = _diff(repo, rel)
    now = hashlib.sha256(diff.encode("utf-8")).hexdigest() if diff else ""
    if not diff:
        state.unlink()
        print(f"✗ [editor-guard] {rel}: nothing to carry (the change was committed or reverted meanwhile).",
              file=sys.stderr)
        return 4
    if now != shown:
        print(diff, end="" if diff.endswith("\n") else "\n")
        print(f"✗ [editor-guard] {rel}: the diff changed after it was shown ({shown[:12]} -> {now[:12]}). "
              f"Nothing committed. Read the diff above and run `check` again.", file=sys.stderr)
        return 4
    res = _git(repo, "commit", "-q", "-m", message, "--", rel, check=False)
    if res.returncode != 0:
        print(res.stdout + res.stderr, file=sys.stderr)
        return res.returncode
    state.unlink()
    head = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    print(f"✓ [editor-guard] carried {rel} as {head}")
    if push:
        pr = _git(repo, "push", "-q", check=False)
        if pr.returncode != 0:
            print(pr.stdout + pr.stderr, file=sys.stderr)
            return pr.returncode
        print("✓ [editor-guard] pushed")
    return 0


def selftest() -> int:
    ok = True

    def expect(name: str, cond: bool) -> None:
        nonlocal ok
        print(("[PASS] " if cond else "[FAIL] ") + name)
        ok &= cond

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        _git(repo, "config", "user.name", "t")
        _git(repo, "config", "user.email", "t@t")
        (repo / "paper.tex").write_text("line one\nline two\n", encoding="utf-8")
        (repo / "other.tex").write_text("x\n", encoding="utf-8")
        _git(repo, "add", "paper.tex", "other.tex")
        _git(repo, "commit", "-q", "-m", "init")
        f = str(repo / "paper.tex")
        count = lambda: int(_git(repo, "rev-list", "--count", "HEAD").stdout.strip())

        expect("clean file: check exits 0", cmd_check(repo, f) == 0)
        expect("carrier without a shown diff exits 5", cmd_carrier(repo, f, "x", False) == 5)
        (repo / "paper.tex").write_text("line one\nline two, edited by the author\n", encoding="utf-8")
        expect("author edit: check exits 3", cmd_check(repo, f) == 3)
        (repo / "paper.tex").write_text("line one, landed later\nline two, edited by the author\n", encoding="utf-8")
        before = count()
        expect("diff changed after it was shown: carrier exits 4", cmd_carrier(repo, f, "x", False) == 4)
        expect("... and nothing was committed", count() == before)
        expect("re-check after the later edit exits 3", cmd_check(repo, f) == 3)
        expect("carrier of the shown diff exits 0", cmd_carrier(repo, f, "Author's hand edits", False) == 0)
        expect("... and made exactly one commit", count() == before + 1)
        expect("... whose message is the carrier message",
               _git(repo, "log", "-1", "--format=%s").stdout.strip() == "Author's hand edits")
        expect("tree is clean again: check exits 0", cmd_check(repo, f) == 0)
        expect("untracked file: check exits 2", cmd_check(repo, str(repo / "nope.tex")) == 2)

        # mark / verify: the window between one's own write and the commit
        expect("verify without a mark exits 5", cmd_verify(repo, f) == 5)
        (repo / "paper.tex").write_text("line one, landed later\nline two, my edit\n", encoding="utf-8")
        expect("mark right after my write exits 0", cmd_mark(repo, f) == 0)
        expect("nobody saved since: verify exits 0", cmd_verify(repo, f) == 0)
        (repo / "paper.tex").write_text("line one, saved by the author during the build\nline two, my edit\n",
                                        encoding="utf-8")
        expect("a save after the mark: verify exits 4", cmd_verify(repo, f) == 4)
        expect("a mark is per file: verify on another file exits 5", cmd_verify(repo, str(repo / "other.tex")) == 5)
        (repo / "paper.tex").write_text("line one, landed later\nline two, my edit\n", encoding="utf-8")
        expect("the later save reverted: verify exits 0 again", cmd_verify(repo, f) == 0)
        _git(repo, "commit", "-q", "-m", "my edit", "--", "paper.tex")
        expect("after the commit, check exits 0 and clears the mark",
               cmd_check(repo, f) == 0 and cmd_verify(repo, f) == 5)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "mark", "verify"):
        c = sub.add_parser(name)
        c.add_argument("file")
        c.add_argument("--repo", default=".")
    k = sub.add_parser("carrier"); k.add_argument("file"); k.add_argument("-m", "--message", required=True)
    k.add_argument("--repo", default="."); k.add_argument("--push", action="store_true")
    a = ap.parse_args()
    repo = Path(a.repo).resolve()
    if a.cmd == "check":
        return cmd_check(repo, a.file)
    if a.cmd == "mark":
        return cmd_mark(repo, a.file)
    if a.cmd == "verify":
        return cmd_verify(repo, a.file)
    return cmd_carrier(repo, a.file, a.message, a.push)


if __name__ == "__main__":
    sys.exit(main())
