#!/usr/bin/env python3
"""Capture and check immutable review inputs while listing newly added artifacts.

Usage: capture ROOT --out BASELINE.json; check ROOT --baseline BASELINE.json.
The baseline stays outside ROOT; capture refuses to replace it. Check reads only,
returns 1 for changed/deleted baseline files, and lists additions separately.
It does not approve additions, collect files, assess science, or scan secrets.
Both modes reject symlinks and special files. Excluded directory names (.git,
.venv, venv, __pycache__) and .pyc files are recorded in the baseline. Stdlib only.
Only run on an authorized tree: the manifest reveals relative names and hashes.
Do not run while another process is writing; this is not an atomic filesystem snapshot.
--selftest exercises preservation, changes, additions, path safety and CLI exits.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile

EXCLUDED_DIRS = ['.git', '.venv', '__pycache__', 'venv']
EXCLUDED_SUFFIXES = ['.pyc']


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def inventory(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('ROOT must be an existing directory, not a symlink')
    files = {}
    def unreadable(error):
        raise error
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=unreadable):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS)
        for name in dirs + sorted(names):
            p = base / name
            mode = p.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError('symlink or special file: ' + str(p.relative_to(root)))
            if stat.S_ISREG(mode) and p.suffix not in EXCLUDED_SUFFIXES:
                files[p.relative_to(root).as_posix()] = digest(p)
    return dict(sorted(files.items()))


def validate(data):
    if (not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1
            or data.get('excluded_dirs') != EXCLUDED_DIRS
            or data.get('excluded_suffixes') != EXCLUDED_SUFFIXES
            or not isinstance(data.get('files'), dict)):
        raise ValueError('invalid baseline schema or exclusions')
    for name, row in data['files'].items():
        p = PurePosixPath(name)
        if (not name or '\\' in name or ':' in name or p.is_absolute()
                or any(x in ('', '.', '..') for x in name.split('/'))):
            raise ValueError('unsafe baseline path')
        if (not isinstance(row, dict) or type(row.get('bytes')) is not int
                or row['bytes'] < 0 or not isinstance(row.get('sha256'), str)
                or re.fullmatch('[0-9a-f]{64}', row['sha256']) is None):
            raise ValueError('invalid baseline file record')
    return data


def external(root, path):
    if path.resolve().is_relative_to(root.resolve()):
        raise ValueError('baseline must be outside ROOT')


def capture(root, out):
    external(root, out)
    data = dict(version=1, excluded_dirs=EXCLUDED_DIRS,
                excluded_suffixes=EXCLUDED_SUFFIXES, files=inventory(root))
    with out.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    return {'recorded': len(data['files']), 'baseline': str(out)}


def check(root, baseline):
    external(root, baseline)
    old = validate(json.loads(baseline.read_text(encoding='utf-8')))['files']
    current = inventory(root)
    missing = sorted(set(old) - set(current))
    changed = sorted(n for n in old.keys() & current.keys() if old[n] != current[n])
    return {'preserved': not missing and not changed, 'baseline_files': len(old),
            'missing': missing, 'changed': changed,
            'added': sorted(set(current) - set(old))}


def selftest():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td); root = base / 'tree'; root.mkdir()
        (root / '入力.bin').write_bytes(b'\x00\xffinitial')
        (root / '__pycache__').mkdir()
        (root / '__pycache__' / 'ignored').write_text('cache')
        snap = base / 'baseline.json'
        assert capture(root, snap)['recorded'] == 1
        assert check(root, snap)['preserved']
        (root / 'new.txt').write_text('new')
        assert check(root, snap)['added'] == ['new.txt']
        assert check(root, snap)['preserved']
        (root / '入力.bin').write_bytes(b'\x00\xffchanged')
        assert check(root, snap)['changed'] == ['入力.bin']
        (root / '入力.bin').unlink()
        assert check(root, snap)['missing'] == ['入力.bin']
        for action in [lambda: capture(root, snap), lambda: capture(root, root/'bad.json')]:
            try: action()
            except (ValueError, FileExistsError): pass
            else: raise AssertionError('unsafe capture succeeded')
        data = json.loads(snap.read_text())
        row = next(iter(data['files'].values()))
        for name in ['../escape', '/absolute', 'a/../b', 'a\\b', 'C:/file', '', './file']:
            bad = dict(data, files={name: row})
            try: validate(bad)
            except ValueError: pass
            else: raise AssertionError('unsafe path accepted')
        if hasattr(os, 'symlink'):
            try: (root/'link').symlink_to(snap)
            except OSError: print('SKIP symlink test: OS did not permit creation', file=sys.stderr)
            else:
                try: inventory(root)
                except ValueError: pass
                else: raise AssertionError('symlink accepted')
                (root/'link').unlink()
        args = [sys.executable, str(Path(__file__).resolve()), 'check', str(root), '--baseline', str(snap)]
        p = subprocess.run(args, capture_output=True, text=True)
        assert p.returncode == 1 and json.loads(p.stdout)['missing'] == ['入力.bin']
        (root/'入力.bin').write_bytes(b'\x00\xffinitial')
        p = subprocess.run(args, capture_output=True, text=True)
        assert p.returncode == 0 and json.loads(p.stdout)['added'] == ['new.txt']
        p = subprocess.run(args[:-1]+[str(base/'absent.json')], capture_output=True, text=True)
        assert p.returncode == 2
    print('selftest OK: preservation, binary/unicode, exclusions, additions, changes, deletion, safety, CLI exits')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selftest', action='store_true')
    sub = parser.add_subparsers(dest='mode')
    for name, flag in [('capture', '--out'), ('check', '--baseline')]:
        p = sub.add_parser(name); p.add_argument('root', type=Path); p.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.selftest:
            selftest(); return 0
        if args.mode == 'capture': result = capture(args.root, args.out)
        elif args.mode == 'check': result = check(args.root, args.baseline)
        else: parser.error('choose capture/check or --selftest')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('preserved', True) else 1
    except (OSError, ValueError, TypeError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
