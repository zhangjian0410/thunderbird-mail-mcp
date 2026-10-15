"""Build a deterministic XPI and its native-host manifest, without installing."""
import argparse
import json
from pathlib import Path
import zipfile


def build(source, output, install_root):
    source, output, install_root = map(Path, (source, output, install_root))
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((source/'extension/manifest.json').read_text())
    names = ['manifest.json', *manifest['background']['scripts']]
    with zipfile.ZipFile(output/'thunderbird-native-send.xpi', 'w') as archive:
        for name in sorted(names):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 14, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (source/'extension'/name).read_bytes())
    native = {'name':'com.thunderbird_mail_mcp.native_send',
              'description':'Thunderbird MCP private send journal bridge',
              'path':str(install_root/'native-send-launcher'), 'type':'stdio',
              'allowed_extensions':[manifest['browser_specific_settings']['gecko']['id']]}
    (output/'native-host.json').write_text(json.dumps(native, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--install-root', type=Path, required=True)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.output, args.install_root)
