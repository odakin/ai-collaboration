"""board_config.py — one board's settings (board.json), which board a command means, the boards in a workspace, and the reader gate.

A board is a directory holding `board.json` and `events/`. It is either a whole repository (a companion repo,
or an owner-only board) or a subdirectory of a shared project repository (`<project>/board/`). Its readers are
exactly the members of that repository: Git's read boundary is the repository, so one board serves one audience.

board.json (format 1):

    {"board_format": 1, "audience": "owner" | "collaborators", "encryption": "git-crypt" | "none",
     "branch": "main", "sources": ["<project key>", ...], "readable": ["<checkout>", ...], "name": "...",
     "labels": {"codex": "..."}, "description": "..."}

- `audience: owner` — only the owner reads it; any source may post (still subject to source classification).
- `audience: collaborators` — the collaborators of the listed `sources` read it. Only those projects may post,
  only `ordinary` posts, and no path, link or summary may name a checkout outside them (`check_post`).
  `readable` lists further checkouts its readers can see anyway (public repositories): naming them passes,
  posting from them or touching their files does not.
- `encryption: git-crypt` — every event blob must be ciphertext before push; `none` — the repository's private
  visibility is the only boundary.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ENGINE = Path(__file__).resolve().parent
CONFIG = 'board.json'
GITCRYPT_MAGIC = b'\x00GITCRYPT'
AUDIENCES = {'owner', 'collaborators'}
ENCRYPTIONS = {'git-crypt', 'none'}
FIELDS = {'board_format', 'name', 'audience', 'encryption', 'branch', 'sources', 'readable', 'labels', 'description'}
KEY_RE = re.compile(r'[a-z0-9][a-z0-9-]{1,63}')


def git(root, *args, timeout=30):
    p = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=timeout)
    return p.stdout.strip() if p.returncode == 0 else ''


def toplevel(root) -> Path | None:
    t = git(root, 'rev-parse', '--show-toplevel')
    return Path(t) if t else None


def subdir(root) -> str:
    """The board's path inside its repository ('' when the board is the whole repository)."""
    return git(root, 'rev-parse', '--show-prefix').rstrip('/')


def workspace(root=None) -> Path:
    """The directory that holds the checkouts (project keys are their basenames).

    AGENT_BOARD_WORKSPACE (or the older AGENT_BOARD_PATH_BASE) wins; otherwise the parent of the board's
    repository, otherwise the parent of this engine's checkout (clone the engine next to your projects).
    """
    env = os.environ.get('AGENT_BOARD_WORKSPACE') or os.environ.get('AGENT_BOARD_PATH_BASE')
    if env:
        return Path(os.path.expanduser(env))
    if root is not None:
        top = toplevel(root)
        if top:
            return top.parent
    return ENGINE.parent.parent


def is_locked(root) -> bool:
    """board.json is ciphertext (or, with no board.json yet, the first event file is)."""
    root = Path(root)
    p = root / CONFIG
    if p.is_file():
        return p.read_bytes().startswith(GITCRYPT_MAGIC)
    first = next((root / 'events').rglob('*.json'), None) if (root / 'events').is_dir() else None
    return bool(first) and first.read_bytes().startswith(GITCRYPT_MAGIC)


def validate(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise ValueError(f'{CONFIG}: top level must be an object')
    problems = []
    unknown = set(cfg) - FIELDS
    if unknown: problems.append(f'unknown field(s) {sorted(unknown)}')
    if cfg.get('board_format') != 1: problems.append('board_format must be 1')
    if cfg.get('audience') not in AUDIENCES: problems.append(f'audience must be one of {sorted(AUDIENCES)}')
    if cfg.get('encryption') not in ENCRYPTIONS: problems.append(f'encryption must be one of {sorted(ENCRYPTIONS)}')
    sources = cfg.get('sources')
    if cfg.get('audience') == 'collaborators':
        if not isinstance(sources, list) or not sources or not all(isinstance(s, str) and KEY_RE.fullmatch(s) for s in sources):
            problems.append('a collaborators board lists its project keys in sources (non-empty)')
    elif sources is not None:
        problems.append('an owner board takes any source; omit sources')
    readable = cfg.get('readable', [])
    if not isinstance(readable, list) or not all(isinstance(s, str) and s and '/' not in s for s in readable):
        problems.append('readable is a list of checkout names')
    elif readable and cfg.get('audience') != 'collaborators':
        problems.append('readable is for collaborators boards')
    if not isinstance(cfg.get('branch', 'main'), str): problems.append('branch must be a string')
    if not isinstance(cfg.get('labels', {}), dict): problems.append('labels must be an object')
    if problems:
        raise ValueError(f'{CONFIG}: ' + '; '.join(problems))
    return {'branch': 'main', 'labels': {}, **cfg}


def load(root) -> dict:
    p = Path(root) / CONFIG
    if not p.is_file():
        raise ValueError(f'{root}: not a board ({CONFIG} missing; create one with `board.py init`)')
    raw = p.read_bytes()
    if raw.startswith(GITCRYPT_MAGIC):
        raise ValueError('board is git-crypt locked on this machine (unlock its repository first)')
    try:
        cfg = json.loads(raw)
    except ValueError as ex:
        raise ValueError(f'{CONFIG}: not JSON ({ex})') from None
    return validate(cfg)


def name_of(root, cfg=None) -> str:
    root = Path(root)
    if cfg and cfg.get('name'):
        return cfg['name']
    return root.parent.name if root.name == 'board' else root.name


def discover(base=None) -> list[dict]:
    """Boards directly in the workspace: `<checkout>/board.json` or `<checkout>/board/board.json`."""
    base = Path(base) if base else workspace()
    out = []
    try:
        dirs = sorted(d for d in base.iterdir() if d.is_dir() and not d.name.startswith('.'))
    except OSError:
        return out
    for d in dirs:
        for cand in (d, d / 'board'):
            if not (cand / CONFIG).is_file():
                continue
            row = {'root': cand, 'name': name_of(cand), 'locked': is_locked(cand), 'error': None, 'config': None}
            if not row['locked']:
                try:
                    row['config'] = load(cand)
                    row['name'] = name_of(cand, row['config'])
                except ValueError as ex:
                    row['error'] = str(ex)
            out.append(row)
    return out


def find(name, base=None) -> Path:
    hits = [b['root'] for b in discover(base) if b['name'] == name]
    if not hits:
        raise ValueError(f'no board named {name} in {base or workspace()} (board.py boards lists them)')
    if len(hits) > 1:
        raise ValueError(f'several boards are named {name}: ' + ', '.join(map(str, hits)))
    return hits[0]


def resolve(root=None, board=None) -> Path:
    """--root > --board > AGENT_BOARD_ROOT. There is no silent default: a post must know which audience reads it."""
    if root:
        return Path(os.path.expanduser(str(root))).absolute()
    if board:
        return find(board)
    env = os.environ.get('AGENT_BOARD_ROOT')
    if env:
        return Path(os.path.expanduser(env)).absolute()
    raise ValueError('which board? pass --root <board dir> or --board <name> (`board.py boards` lists them), or set AGENT_BOARD_ROOT')


def collaborator_boards_for(project, base=None) -> list[dict]:
    """Collaborator boards that list `project` as a source (an owner post about it may belong there)."""
    return [b for b in discover(base) if b['config'] and b['config']['audience'] == 'collaborators'
            and project in b['config']['sources']]


# ---------------------------------------------------------------- reader gate

URL_RE = re.compile(r'^[a-z][a-z0-9+.-]*://', re.I)
COMMIT_REF_RE = re.compile(r'^([A-Za-z0-9][A-Za-z0-9._-]*)@[0-9a-f]{7,40}$')
ABS_TOKEN_RE = re.compile(r'(?:~|/Users|/home)/[^\s`\'"),;]*')
NAME_TOKEN_RE = re.compile(r'(?<![\w./~-])([A-Za-z0-9][A-Za-z0-9._-]*)/')


def _github_repo(url):
    u = urlparse(url)
    host = (u.hostname or '').lower()
    if host != 'github.com' and not host.endswith('.github.com'):
        return None
    parts = [p for p in u.path.split('/') if p]
    return '/'.join(parts[:2]).lower().removesuffix('.git') if len(parts) >= 2 else ''


def _remote_repo(checkout):
    url = git(checkout, 'remote', 'get-url', 'origin')
    m = re.search(r'github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$', url)
    return m.group(1).lower() if m else None


class Gate:
    """What a collaborators board's readers may see: its source checkouts and the board's own repository."""

    def __init__(self, cfg, root):
        self.cfg, self.root = cfg, Path(root)
        self.ws = workspace(root)
        top = toplevel(root)
        self.sources = set(cfg.get('sources') or []) | ({top.name} if top else set())
        self.allowed = self.sources | set(cfg.get('readable') or [])   # may be named; only sources post or touch
        self.roots = [Path(os.path.realpath(self.ws / s)) for s in self.allowed]
        try:
            siblings = [d for d in self.ws.iterdir() if d.is_dir() and (d / '.git').exists()]
        except OSError:
            siblings = []
        # Checkouts next to the board that its readers cannot see: naming one leaks it.
        self.private = {d.name for d in siblings if d.name not in self.allowed}
        self.repos = {r for r in (_remote_repo(self.ws / s) for s in self.allowed if (self.ws / s).is_dir()) if r}
        if top:
            r = _remote_repo(top)
            if r: self.repos.add(r)

    def _path_ok(self, raw):
        p = Path(os.path.realpath(os.path.expanduser(raw)))
        return any(p == r or r in p.parents for r in self.roots)

    def check_ref(self, ref, what):
        ref = str(ref).strip()
        if URL_RE.match(ref):
            gh = _github_repo(ref)
            if gh is not None and gh not in self.repos:
                raise ValueError(f'{what} {ref}: a repository this board\'s readers may not see '
                                 f'(allowed: {", ".join(sorted(self.repos)) or "none found"})')
            return
        m = COMMIT_REF_RE.match(ref)
        if m:
            if m.group(1) not in self.allowed:
                raise ValueError(f'{what} {ref}: {m.group(1)} is not a source of this board ({", ".join(sorted(self.allowed))})')
            return
        if ref.startswith(('~', '/')):
            if not self._path_ok(ref):
                raise ValueError(f'{what} {ref}: outside this board\'s sources ({", ".join(sorted(self.allowed))})')
            return
        first = ref.split('/', 1)[0]
        if first in self.private:
            raise ValueError(f'{what} {ref}: names {first}, a checkout this board\'s readers cannot see')

    def check_text(self, text, what):
        for tok in ABS_TOKEN_RE.findall(text or ''):
            if not self._path_ok(tok):
                raise ValueError(f'{what}: "{tok}" points outside this board\'s sources; collaborators read every summary')
        for name in NAME_TOKEN_RE.findall(text or ''):
            if name in self.private:
                raise ValueError(f'{what}: "{name}/" names a checkout this board\'s readers cannot see')

    def check_touch(self, token, typed):
        if token.startswith('h:'):
            return
        first = token.split('/', 1)[0]
        if first not in self.sources:
            raise ValueError(f'{typed}: {first} is not a source of this board ({", ".join(sorted(self.sources))}); declare it on a board its readers may see')


def check_post(cfg, root, *, project, policy, texts=(), refs=(), touches=()):
    """Refuse, before any event is built, what a collaborators board's readers must not see. Owner boards pass."""
    if cfg['audience'] != 'collaborators':
        return
    if policy != 'ordinary':
        raise ValueError('a collaborators board takes ordinary posts only (its readers see every path and summary); '
                         'a restricted or no-post source does not post here')
    if project not in cfg['sources']:
        raise ValueError(f'project {project} is not a source of this board ({", ".join(cfg["sources"])}); '
                         'post about it on a board its readers may see')
    g = Gate(cfg, root)
    for token, typed in touches:
        g.check_touch(token, typed)
    for what, value in refs:
        g.check_ref(value, what)
    for what, value in texts:
        g.check_text(value, what)


# ---------------------------------------------------------------- scaffold

def scaffold(root, *, audience, encryption, sources, branch='main', name=None, engine_url=None) -> list[Path]:
    """Write board.json and a short README for a new board. Commits nothing (the caller adds both files)."""
    root = Path(root)
    if (root / CONFIG).exists():
        raise ValueError(f'{root / CONFIG} already exists')
    cfg = {'board_format': 1, 'audience': audience, 'encryption': encryption, 'branch': branch}
    if audience == 'collaborators':
        cfg['sources'] = list(sources)
    if name:
        cfg['name'] = name
    validate(cfg)
    root.mkdir(parents=True, exist_ok=True)
    (root / CONFIG).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
    engine_url = engine_url or 'https://github.com/odakin/ai-collaboration/tree/main/board'
    who = ('このリポジトリにアクセスできる人 (共同研究者) と、 その AI session' if audience == 'collaborators'
           else 'owner だけ')
    src = ', '.join(sources) if audience == 'collaborators' else '(any)'
    readme = f"""# 掲示板 / Board

AI session どうし (Claude / Codex、 別の人の session を含む) が、 依頼・引受・提出・受領と作業中の状況を残す掲示板。
読む人 = {who}。 投稿を受け付ける project = {src}。

- 道具と使い方: {engine_url} (README.md)。 `git clone https://github.com/odakin/ai-collaboration` してから
  `python3 <ai-collaboration>/board/board.py <command> --root <この directory> ...`
- 最初に: `inbox --sync` (自分宛て) / `sessions --sync` (誰が居るか) / `board-view.py --root <この directory>` (全体)
- 決まったこと・成果は project の文書に書き、 掲示板はその場所を指すだけ (掲示板を消しても project の知識は残る)。
- 書かないもの: 認証情報・秘密、 会話の生ログ、 この project の外の話 (投稿の時に道具が止める)。
- event の file は手で書き換えない。 訂正は新しい投稿で。

This board is read by {'the collaborators of this repository and their AI sessions' if audience == 'collaborators' else 'the owner only'}.
Usage and rules: {engine_url}.
"""
    (root / 'README.md').write_text(readme)
    return [root / CONFIG, root / 'README.md']
