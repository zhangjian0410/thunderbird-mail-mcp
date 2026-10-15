"""Redacted history and tracked-file scans; never walk a user's home or venv."""
import argparse
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PINNED_VERSION = '8.30.1'
HOME_PATH = re.compile(r'/(?:Users|home)/[A-Za-z0-9._-]+(?:/|\b)')
EMAIL = re.compile(r'[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}', re.I)


def forbidden_path(name):
    path = PurePosixPath(name)
    local_names = {'native-host.json', 'com.thunderbird_mail_mcp.native_send.json',
                   'rollback.json', 'profiles.ini', 'prefs.js', 'logins.json', 'key4.db'}
    if path.name in local_names or any(part in ('deployment-backups', '.venv', '__pycache__') for part in path.parts):
        return True
    if path.name == '.env' or (path.name.startswith('.env.') and path.name not in ('.env.example', '.env.sample')):
        return True
    if path.suffix.lower() in ('.xpi', '.mbox', '.sqlite3', '.db', '.msf'):
        return True
    return path.name in ('Inbox', 'Sent', 'Drafts') or bool(re.search(r'\.(?:sqlite3|db)(?:-.*)?$', path.name))


def private_content(name, raw):
    """Report the rule and relative location, never the matched private value."""
    for number, line in enumerate(raw.decode('utf-8', errors='replace').splitlines(), 1):
        if HOME_PATH.search(line):
            raise ValueError(f'Private home directory in tracked content: {name}:{number}')
        for match in EMAIL.finditer(line):
            address = match.group().lower()
            domain = address.rsplit('@', 1)[1]
            reserved = (domain in ('example.com', 'example.net', 'example.org')
                        or domain.endswith(('.test', '.invalid', '.example', '.example.com', '.example.net', '.example.org')))
            if not (reserved or address == 'native-send@thunderbird-mail-mcp.local'
                    or domain == 'users.noreply.github.com'):
                raise ValueError(f'Non-example mailbox in tracked content: {name}:{number}')


def private_history(repository):
    """Inspect unique historical blobs as well as paths removed from HEAD."""
    names = subprocess.check_output(['git', '-C', str(repository), 'log', '--all', '--full-history', '-m',
                                     '--format=', '--name-only', '-z'])
    for encoded in names.split(b'\0'):
        name = os.fsdecode(encoded).strip('\n')
        if name and forbidden_path(name):
            raise ValueError(f'Local/generated configuration exists in Git history: {name}')
    objects = subprocess.check_output(['git', '-C', str(repository), 'rev-list', '--objects', '--all']).splitlines()
    entries = [line.split(b' ', 1) for line in objects if b' ' in line]
    metadata = subprocess.check_output(
        ['git', '-C', str(repository), 'cat-file', '--batch-check=%(objecttype)'],
        input=b'\n'.join(entry[0] for entry in entries) + b'\n').splitlines()
    if len(metadata) != len(entries) or any(kind not in (b'blob', b'tree', b'commit', b'tag') for kind in metadata):
        raise ValueError('Git history object inventory is incomplete')
    for (oid, encoded_name), kind in zip(entries, metadata):
        if kind == b'blob':
            raw = subprocess.check_output(['git', '-C', str(repository), 'cat-file', 'blob', oid.decode('ascii')])
            private_content(os.fsdecode(encoded_name), raw)


def tracked_snapshot(repository, destination):
    names = subprocess.check_output(['git', '-C', str(repository), 'ls-files', '-z']).split(b'\0')
    for encoded in filter(None, names):
        name = os.fsdecode(encoded)
        source = repository / name
        if forbidden_path(name):
            raise ValueError(f'Local/generated configuration is tracked: {name}')
        if source.is_symlink() or not source.resolve().is_relative_to(repository):
            raise ValueError(f'Tracked symlink or escaping path is not supported: {name}')
        if not source.is_file():
            raise ValueError(f'Tracked file is missing: {name}')
        private_content(name, source.read_bytes())
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=ROOT)
    parser.add_argument('--mode', choices=('all', 'history', 'snapshot'), default='all')
    args = parser.parse_args(argv)
    repository = args.repository.resolve()
    binary = os.environ.get('GITLEAKS_BIN') or shutil.which('gitleaks')
    if not binary:
        parser.error(f'Gitleaks {PINNED_VERSION} is required; see README')
    version = subprocess.check_output([binary, 'version'], text=True).strip().removeprefix('v')
    if version != PINNED_VERSION:
        parser.error(f'Gitleaks {PINNED_VERSION} is required')
    with TemporaryDirectory(prefix='mail-mcp-secret-scan-') as directory:
        temporary = Path(directory)
        ignore = temporary / 'empty-ignore'
        ignore.write_text('')
        common = ['--config', str(ROOT / '.gitleaks.toml'), '--redact=100', '--no-banner',
                  '--no-color', '--ignore-gitleaks-allow', '--gitleaks-ignore-path', str(ignore)]
        if args.mode in ('all', 'history'):
            private_history(repository)
            subprocess.run([binary, 'git', str(repository), '--log-opts=--all --full-history -m', *common], check=True)
        if args.mode in ('all', 'snapshot'):
            snapshot = temporary / 'tracked'
            snapshot.mkdir()
            tracked_snapshot(repository, snapshot)
            subprocess.run([binary, 'dir', str(snapshot), *common], check=True)
    print(f'Secrets scan passed ({args.mode})')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
