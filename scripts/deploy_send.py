"""Deploy reviewed files and register native host; never enable an add-on or send."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
FILES = ['mail_sender.py', 'native_host.py', 'server.py', 'pyproject.toml', 'README.md',
         'extension/manifest.json', 'extension/sender.js', 'extension/background.js',
         'tests/test_mail_sender.py', 'tests/test_native_host.py', 'tests/test_server.py',
         'tests/test_package_send.py', 'tests/sender.test.cjs', 'tests/bridge_roundtrip.test.cjs',
         'scripts/package_send.py', 'scripts/deploy_send.py', 'docs/superpowers/plans/2026-09-14-native-send.md']
FILES += ['tests/test_attachments.py', 'tests/attachments.test.cjs']
FILES += ['mail_reader.py', 'tests/test_mail_reader_deleted.py']
FILES += ['mail_store.py']
FILES += ['tests/test_deployment.py']


def prepare(target, output, native_dir):
    baseline_file = SOURCE/'baseline-hashes.json'
    baseline = json.loads(baseline_file.read_text()) if baseline_file.exists() else {}
    changes = {}
    for name in FILES:
        dest = target/name
        data = (SOURCE/name).read_bytes()
        if dest.exists():
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            if digest not in (baseline.get(name), hashlib.sha256(data).hexdigest()):
                raise ValueError(f'Concurrent change detected: {dest}')
        changes[dest] = (data, 0o644)
    python = target/'.venv/bin/python'
    if not python.is_file():
        raise ValueError('Existing MCP Python runtime missing')
    launcher = (f'#!{python}\n'
                'import sys\n'
                f'sys.path.insert(0, {str(target)!r})\n'
                'from native_host import serve\n'
                'from mail_sender import SendJournal\n'
                'serve(sys.stdin.buffer, sys.stdout.buffer, SendJournal())\n')
    changes[target/'native-send-launcher'] = (launcher.encode(), 0o700)
    changes[native_dir/'com.thunderbird_mail_mcp.native_send.json'] = ((output/'native-host.json').read_bytes(), 0o600)
    return changes


def install(changes, backup):
    backup.mkdir(parents=True, exist_ok=False)
    records = []
    try:
        for number, (dest, (data, mode)) in enumerate(changes.items()):
            if dest.is_symlink():
                raise ValueError(f'Refuse symlink target: {dest}')
            saved = backup/str(number)
            old_mode = None
            if dest.exists():
                old_mode = dest.stat().st_mode & 0o777
                shutil.copy2(dest, saved)
            records.append({'target':str(dest), 'backup':str(saved) if old_mode is not None else None, 'mode':old_mode})
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix='.native-send-', dir=dest.parent)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temp, mode)
                os.replace(temp, dest)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        (backup/'rollback.json').write_text(json.dumps(records, indent=2)+'\n')
    except BaseException:
        for record in reversed(records):
            dest = Path(record['target'])
            if record['backup']:
                shutil.copy2(record['backup'],dest)
            elif dest.exists():
                dest.unlink()
        raise
    for dest,(data,_mode) in changes.items():
        if dest.read_bytes() != data:
            raise RuntimeError(f'Deployment verification failed: {dest}')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--native-dir',type=Path,required=True)
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    changes=prepare(args.target,args.output,args.native_dir)
    if args.check:
        print(json.dumps({'ready':True,'files':len(changes),'enables_extension':False,'sends_mail':False}))
    else:
        if args.backup is None:
            parser.error('--backup is required for deployment')
        install(changes,args.backup)
        print(json.dumps({'deployed':True,'files':len(changes),'backup':str(args.backup),'extension_activation':'required'}))
