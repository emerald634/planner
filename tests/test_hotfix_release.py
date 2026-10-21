import hashlib
import json
import shutil
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from deploy.package_release import FILES, ROOT, package, build_frontend
from deploy.release_check import check


class HotfixReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'source'
        for name in (*FILES, 'deploy/release_check.py', 'HOTFIX_2_1_1_RELEASE.md'):
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        shutil.copytree(ROOT / 'planner', self.root / 'planner', ignore=shutil.ignore_patterns('__pycache__'))
        dist = self.root / 'miniapp/dist'
        (dist / 'assets').mkdir(parents=True)
        (dist / 'index.html').write_text('<script src="/assets/index-test.js"></script><link rel="stylesheet" href="/assets/index-test.css">')
        (dist / 'assets/index-test.js').write_text('console.log("production")')
        (dist / 'assets/index-test.css').write_text('body{color:black}')
        self.target = Path(self.temp.name) / 'planner-2.1.1-test.tar.gz'

    def pack(self, release_id='planner-2.1.1-test', **kwargs):
        tracked = '\n'.join(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())
        with patch('deploy.package_release.build_frontend'), patch('deploy.package_release.subprocess.check_output', side_effect=['a' * 40, tracked, '']):
            package(self.root, self.target, planner_only=True, release_id=release_id, **kwargs)

    def extract(self):
        result = Path(self.temp.name) / 'extracted'
        with tarfile.open(self.target) as archive:
            archive.extractall(result, filter='data')
        return result

    def test_planner_release_identity_sidecars_and_no_bot_or_web(self):
        (self.root / '.env').write_text('DO_NOT_PACKAGE')
        (self.root / 'access.db').write_bytes(b'SQLite format 3\0')
        (self.root / 'miniapp/desktop').mkdir()
        (self.root / 'miniapp/desktop/demo.html').write_text('DO_NOT_PACKAGE')
        self.pack()
        extracted = self.extract()
        self.assertGreater(check(extracted), 20)
        manifest = json.loads((extracted / 'release-files.json').read_text())
        self.assertEqual((manifest['release'], manifest['version'], manifest['component']), ('planner-2.1.1-test', '2.1.1', 'planner'))
        self.assertEqual(manifest['git_commit'], 'a' * 40)
        example = (extracted / 'deploy/planner.env.example').read_text()
        self.assertIn('PLANNER_IMAGE=bitrix-workday-planner:planner-2.1.1-test', example)
        self.assertNotIn('BOT_RELEASE_IMAGE=', example)
        for name in ('bot.py', 'compose.bot.release.yaml', '.env', 'access.db', 'miniapp/desktop/demo.html'):
            self.assertNotIn(name, manifest['files'])
        sidecar = Path(str(self.target) + '.sha256').read_text()
        self.assertEqual(sidecar.split()[0], hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(set(Path(str(self.target) + '.files.txt').read_text().splitlines()), set(manifest['files']) | {'release-files.json'})

    def test_requires_identity_and_disjoint_profiles(self):
        for kwargs in ({}, {'release_id': '../escape'}, {'release_id': 'stage2-1-production-v1'}, {'release_id': 'planner-2.1.1-test', 'stage2': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                package(self.root, self.target, planner_only=True, **kwargs)
        self.assertFalse(self.target.exists())

    def test_build_keeps_locked_dev_tools_without_disabling_security(self):
        with patch('deploy.package_release.subprocess.run') as run:
            build_frontend(self.root, 'pnpm')
        install = run.call_args_list[0].args[0]
        self.assertEqual(install, ['pnpm', 'install', '--offline', '--frozen-lockfile', '--prod=false'])
        self.assertEqual(run.call_args_list[1].args[0], ['pnpm', 'run', 'build'])

    def test_requires_committed_sources(self):
        with patch('deploy.package_release.subprocess.check_output', side_effect=['a' * 40, '', ' M access.py']):
            with self.assertRaisesRegex(ValueError, 'Git-коммите'):
                package(self.root, self.target, planner_only=True, release_id='planner-2.1.1-test')
        self.assertFalse(self.target.exists())

    def test_existing_artifacts_are_not_overwritten(self):
        self.pack()
        original = self.target.read_bytes()
        with self.assertRaises(FileExistsError):
            self.pack()
        self.assertEqual(self.target.read_bytes(), original)

    def test_two_release_ids_remain_independent(self):
        self.pack()
        original = self.target.read_bytes()
        first = self.target
        self.target = first.with_name('second.tar.gz')
        self.pack(release_id='planner-2.1.1-second')
        with tarfile.open(self.target) as archive:
            manifest = json.load(archive.extractfile('release-files.json'))
        self.assertEqual(manifest['release'], 'planner-2.1.1-second')
        self.assertEqual(first.read_bytes(), original)

    def test_invalid_build_never_publishes_artifact(self):
        (self.root / 'miniapp/dist/assets/index-test.js').write_text('preview.html')
        with self.assertRaises(ValueError):
            self.pack()
        self.assertFalse(self.target.exists())
        self.assertFalse(Path(str(self.target) + '.sha256').exists())

    def test_rehashed_manifest_cannot_mix_frontend_identity(self):
        self.pack()
        extracted = self.extract()
        manifest_path = extracted / 'release-files.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['git_commit'] = 'b' * 40
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            check(extracted)

    def test_unknown_profiles_and_journals_rejected(self):
        self.pack()
        extracted = self.extract()
        manifest_path = extracted / 'release-files.json'
        manifest = json.loads(manifest_path.read_text())
        (extracted / 'planner.db-wal').write_text('not even a real database')
        manifest['files']['planner.db-wal'] = hashlib.sha256((extracted / 'planner.db-wal').read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Forbidden'):
            check(extracted)

    def test_lockfile_hash_checked_even_if_outer_manifest_updated(self):
        self.pack()
        extracted = self.extract()
        lock = extracted / 'miniapp/pnpm-lock.yaml'
        lock.write_text('changed')
        manifest_path = extracted / 'release-files.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files']['miniapp/pnpm-lock.yaml'] = hashlib.sha256(lock.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'lockfile checksum'):
            check(extracted)
