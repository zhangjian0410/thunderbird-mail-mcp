"""Exercise the real pinned scanner using only disposable synthetic repositories."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ScannerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repository = Path(self.tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Fixture')
        self.git('config', 'user.email', 'fixture@example.test')
        (self.repository / 'README.md').write_text('Safe example: person@example.test\n')
        self.git('add', 'README.md')
        self.git('commit', '-qm', 'Clean synthetic fixture')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repository), *args], check=True, capture_output=True)

    def scan(self, mode='all'):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/check_secrets.py'),
                               '--repository', str(self.repository), '--mode', mode],
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, 'GITLEAKS_BIN': os.environ['GITLEAKS_BIN']})

    def add_fixture(self, name, content):
        path = self.repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self.git('add', name)

    def test_reserved_examples_pass_and_untracked_local_files_are_not_read(self):
        self.git('tag', '-a', 'fixture-tag', '-m', 'Synthetic annotated tag')
        self.add_fixture('examples.txt', 'user@example.com\nuser@sample.invalid\n'
                         'native-send@thunderbird-mail-mcp.local\n')
        self.add_fixture('.env.example', 'PASSWORD=<replace-me>\n')
        (self.repository / 'untracked-local.txt').write_text('/' + 'Users/' + 'fixture-person/private')
        result = self.scan()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_tracked_private_home_directory_is_rejected(self):
        for parent in ('Users', 'home'):
            with self.subTest(parent=parent):
                self.add_fixture('config.txt', '/' + parent + '/' + 'fixtureperson/Library/Thunderbird/Inbox')
                result = self.scan('snapshot')
                self.assertEqual(result.returncode, 1)

    def test_tracked_non_example_mailbox_is_rejected(self):
        self.add_fixture('config.txt', 'person@' + 'synthetic-company.' + 'com')
        result = self.scan('snapshot')
        self.assertEqual(result.returncode, 1)

    def test_inline_allow_comment_cannot_hide_a_synthetic_token(self):
        token = 'ghp_' + 'AbC123dEf456GhI789jKl012MnO345pQr678s'
        self.add_fixture('credential.txt', token + ' # gitleaks:allow\n')
        result = self.scan('snapshot')
        self.assertEqual(result.returncode, 1)
        self.assertTrue(token not in result.stdout + result.stderr, 'Scanner output must redact the synthetic token')

    def test_deleted_historical_token_is_still_rejected(self):
        token = 'ghp_' + 'AbC123dEf456GhI789jKl012MnO345pQr678s'
        self.add_fixture('credential.txt', token)
        self.git('commit', '-qm', 'Synthetic historical credential fixture')
        self.git('rm', '-q', 'credential.txt')
        self.git('commit', '-qm', 'Remove fixture from HEAD')
        result = self.scan('history')
        self.assertEqual(result.returncode, 1)
        self.assertTrue(token not in result.stdout + result.stderr, 'History findings must remain redacted')

    def test_force_added_generated_configuration_is_rejected(self):
        self.add_fixture('native-host.json', '{}')
        result = self.scan('snapshot')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Local/generated configuration is tracked', result.stderr)

    def test_tokens_in_lockfiles_and_tests_are_not_excluded(self):
        token = 'ghp_' + 'AbC123dEf456GhI789jKl012MnO345pQr678s'
        for name in ('uv.lock', 'tests/test_fixture.py'):
            with self.subTest(name=name):
                self.add_fixture(name, token)
                result = self.scan('snapshot')
                self.assertEqual(result.returncode, 1)
                self.git('reset', '-q', 'HEAD', '--', name)
                (self.repository / name).unlink()

    def test_deleted_historical_private_path_is_still_rejected(self):
        self.add_fixture('config.txt', '/' + 'home/' + 'fixtureperson/private')
        self.git('commit', '-qm', 'Synthetic private-path fixture')
        self.git('rm', '-q', 'config.txt')
        self.git('commit', '-qm', 'Remove private path from HEAD')
        result = self.scan('history')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Private home directory', result.stderr)

    def test_token_introduced_by_merge_and_then_deleted_is_rejected(self):
        branch = self.git('branch', '--show-current').stdout.decode().strip()
        self.git('checkout', '-qb', 'fixture-side')
        self.add_fixture('side.txt', 'Side branch fixture')
        self.git('commit', '-qm', 'Synthetic side branch')
        self.git('checkout', '-q', branch)
        self.add_fixture('main.txt', 'Main branch fixture')
        self.git('commit', '-qm', 'Synthetic main branch')
        self.git('merge', '--no-commit', '--no-ff', 'fixture-side')
        token = 'ghp_' + 'AbC123dEf456GhI789jKl012MnO345pQr678s'
        self.add_fixture('credential.txt', token)
        self.git('commit', '-qm', 'Synthetic merge-only credential')
        self.git('rm', '-q', 'credential.txt')
        self.git('commit', '-qm', 'Remove merge fixture')
        result = self.scan('history')
        self.assertEqual(result.returncode, 1)
        self.assertTrue(token not in result.stdout + result.stderr, 'Merge-history findings must remain redacted')

    def test_configuration_added_and_deleted_only_by_merges_is_rejected(self):
        branch = self.git('branch', '--show-current').stdout.decode().strip()
        for number in (1, 2):
            side = f'fixture-side-{number}'
            self.git('checkout', '-qb', side)
            self.add_fixture(f'side-{number}.txt', 'Side branch fixture')
            self.git('commit', '-qm', 'Synthetic side branch')
            self.git('checkout', '-q', branch)
            self.add_fixture(f'main-{number}.txt', 'Main branch fixture')
            self.git('commit', '-qm', 'Synthetic main branch')
            self.git('merge', '--no-commit', '--no-ff', side)
            if number == 1:
                self.add_fixture('native-host.json', '{}')
            else:
                self.git('rm', '-q', 'native-host.json')
            self.git('commit', '-qm', 'Synthetic merge-only configuration')
        self.assertFalse((self.repository / 'native-host.json').exists())
        result = self.scan()
        self.assertEqual(result.returncode, 1)
        self.assertIn('Local/generated configuration exists in Git history', result.stderr)


if __name__ == '__main__':
    if not os.environ.get('GITLEAKS_BIN'):
        raise SystemExit('Set GITLEAKS_BIN to the pinned scanner executable')
    unittest.main(verbosity=2)
