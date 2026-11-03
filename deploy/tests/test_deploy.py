"""Check fail-closed SSH parsing without connecting to a real server."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ENTRY = Path(__file__).resolve().parents[1] / 'ssh-entry.sh'
DEPLOY = ENTRY.with_name('deploy.sh')


class DeploymentTests(unittest.TestCase):
    def test_ssh_rejects_shell_commands_and_untrusted_refs(self):
        for command in ('', 'bash', 'deploy main', 'deploy ' + 'a'*39,
                        'deploy ' + 'a'*40 + '; id', 'deploy ' + 'a'*40 + '\nwhoami',
                        'deploy ' + 'a'*40 + ' extra'):
            result = subprocess.run(['bash', str(ENTRY)], env=os.environ | {'SSH_ORIGINAL_COMMAND': command}, capture_output=True)
            self.assertEqual(result.returncode, 64, command)

    def test_exact_sha_is_forwarded_as_a_single_argument(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / 'entry.sh'
            fake.write_text(ENTRY.read_text().replace('exec sudo -n -u petrmath /usr/local/libexec/petrmath-deploy', 'exec /usr/bin/printf "%s\\n"'))
            sha = 'a'*40
            result = subprocess.run(['bash', str(fake)], env=os.environ | {'SSH_ORIGINAL_COMMAND': 'deploy ' + sha}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), sha)

    def test_worker_rejects_invalid_sha_before_mutation(self):
        for args in ([], ['main'], ['a'*40, 'extra'], ['../main']):
            result = subprocess.run(['bash', str(DEPLOY), *args], capture_output=True)
            self.assertEqual(result.returncode, 64)


class WorkerIntegrationTests(unittest.TestCase):
    """Run real Git checkouts against temp repos; mock OS services and pip only."""
    def setUp(self):
        import shutil
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'; self.bin.mkdir()
        self.app = self.root / 'app'
        self.remote = self.root / 'remote'
        self.venvs = self.root / 'venvs'
        self.acks = self.root / 'acks'; self.acks.mkdir()
        self.real_git = shutil.which('git')
        self.git('init', '-b', 'main', str(self.remote))
        self.git('-C', str(self.remote), 'config', 'user.email', 'test@example.org')
        self.git('-C', str(self.remote), 'config', 'user.name', 'Test')
        (self.remote / '.gitignore').write_text('.env\ndata/\n.venv\n.venv-before-auto-deploy/\n')
        (self.remote / 'requirements.txt').write_text('')
        (self.remote / 'version.txt').write_text('old')
        self.git('-C', str(self.remote), 'add', '.')
        self.git('-C', str(self.remote), 'commit', '-m', 'old')
        self.old = self.git('-C', str(self.remote), 'rev-parse', 'HEAD')
        self.git('clone', str(self.remote), str(self.app))
        (self.app / '.env').write_text('test-private-value')
        (self.app / 'data').mkdir(); (self.app / 'data' / 'file.txt').write_text('material')
        (self.app / '.venv' / 'bin').mkdir(parents=True)
        self.fake_python = '''#!/usr/bin/env python3
import pathlib,sys
if len(sys.argv)>2 and sys.argv[1:3]==['-m','venv']:
    folder=pathlib.Path(sys.argv[3])/'bin';folder.mkdir(parents=True)
    target=folder/'python';target.write_text(pathlib.Path(__file__).read_text());target.chmod(0o755)
elif '-m' not in sys.argv:
    source=sys.stdin.read()
    if 'GOOGLE_DRIVE_PRIVATE_DIR' in source: print(CLEANUP_PATH)
'''.replace('CLEANUP_PATH', repr(str(self.root / 'cleanup')))
        self.executable(self.app / '.venv' / 'bin' / 'python', self.fake_python)
        # Keep the real Python available for the fake interpreter itself.
        import sys
        self.executable(self.bin / 'python3', f'#!/bin/bash\nexec "{sys.executable}" "$@"\n')
        self.executable(self.bin / 'prepare-venv', self.fake_python)
        self.executable(self.bin / 'git', f'''#!/bin/bash
if [[ "$*" == "remote get-url origin" ]]; then
 echo https://github.com/bondarenko-petr/petrmath.git
else
 exec "{self.real_git}" "$@"
fi
''')
        for name in ('flock', 'sleep', 'sudo'):
            self.executable(self.bin / name, '#!/bin/bash\nexit 0\n')
        # Simulate minimal Debian: unprivileged systemctl cannot reach the bus.
        self.executable(self.bin / 'systemctl', '#!/bin/bash\necho bus-unavailable >&2\nexit 77\n')
        self.executable(self.bin / 'curl', f'''#!/bin/bash
if [[ -e "{self.root}/fail-new" && $(readlink "{self.app}/.venv") == "{self.venvs}/"* ]]; then exit 22; fi
exit 0
''')
        worker = DEPLOY.read_text().replace('export PATH=/usr/sbin:/usr/bin:/sbin:/bin', f'export PATH="{self.bin}:/usr/bin:/bin"')
        worker = worker.replace('APP=/srv/petrmath/app', f'APP="{self.app}"').replace('VENVS=/srv/petrmath/venvs', f'VENVS="{self.venvs}"').replace('ACKS=/etc/petrmath-deploy/migrations', f'ACKS="{self.acks}"')
        worker = worker.replace('$(id -un)', 'petrmath').replace('/srv/petrmath/deploy.lock', str(self.root / 'deploy.lock')).replace('/srv/petrmath/deploy-requirements.', str(self.root / 'requirements.'))
        worker = worker.replace('python3 -m venv', 'prepare-venv -m venv').replace('/usr/bin/systemctl', 'systemctl')
        self.worker = self.root / 'worker.sh'; self.worker.write_text(worker)

    def executable(self, path, content):
        path.write_text(content); path.chmod(0o755)

    def git(self, *args):
        return subprocess.check_output([self.real_git, *args], stderr=subprocess.DEVNULL, text=True).strip()

    def target(self, sql=False):
        (self.remote / 'version.txt').write_text('new')
        if sql:
            (self.remote / 'sql').mkdir(); (self.remote / 'sql' / 'new.sql').write_text('SELECT 1;')
        self.git('-C', str(self.remote), 'add', '.')
        self.git('-C', str(self.remote), 'commit', '-m', 'new')
        return self.git('-C', str(self.remote), 'rev-parse', 'HEAD')

    def run_worker(self, sha):
        return subprocess.run(['bash', str(self.worker), sha], capture_output=True, text=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_success_preserves_private_state_and_old_environment(self):
        sha = self.target()
        result = self.run_worker(sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('-C', str(self.app), 'rev-parse', 'HEAD'), sha)
        self.assertEqual((self.app / '.env').read_text(), 'test-private-value')
        self.assertEqual((self.app / 'data' / 'file.txt').read_text(), 'material')
        self.assertTrue((self.app / '.venv-before-auto-deploy' / 'bin' / 'python').exists())
        self.assertEqual(self.run_worker(sha).returncode, 0)

    def test_failed_health_restores_code_and_previous_environment(self):
        sha = self.target(); (self.root / 'fail-new').touch()
        result = self.run_worker(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('-C', str(self.app), 'rev-parse', 'HEAD'), self.old)
        self.assertEqual((self.app / '.venv').resolve(), (self.app / '.venv-before-auto-deploy').resolve())
        self.assertEqual((self.app / 'data' / 'file.txt').read_text(), 'material')

    def test_sql_requires_explicit_acknowledgment(self):
        sha = self.target(sql=True)
        result = self.run_worker(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SQL changed', result.stderr)
        self.assertEqual(self.git('-C', str(self.app), 'rev-parse', 'HEAD'), self.old)
        (self.acks / sha).write_text(sha)
        result = self.run_worker(sha)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dirty_and_outdated_commits_are_refused(self):
        sha = self.target()
        result = self.run_worker('a'*40)
        self.assertNotEqual(result.returncode, 0)
        (self.app / 'version.txt').write_text('local change')
        result = self.run_worker(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.app / 'version.txt').read_text(), 'local change')
