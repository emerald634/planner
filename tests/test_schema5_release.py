import hashlib
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.package_release import package
from deploy.release_check import check
from planner.web_auth.migration import migrate_synthetic
from tests import test_hotfix_release as hotfix
from tests.web_auth_fixtures import connect, create_schema4


class BridgeReleaseTests(unittest.TestCase):
    def setUp(self):
        hotfix.HotfixReleaseTests.setUp(self)
        shutil.copyfile(hotfix.ROOT/'SCHEMA5_BRIDGE_RELEASE.md',self.root/'SCHEMA5_BRIDGE_RELEASE.md')
        self.target = self.target.with_name('planner-schema5-bridge-test.tar.gz')
    extract = hotfix.HotfixReleaseTests.extract

    def pack(self, release_id='planner-schema5-bridge-test'):
        tracked='\n'.join(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())
        with patch('deploy.package_release.build_frontend'), patch('deploy.package_release.subprocess.check_output',side_effect=['a'*40,tracked,'']):
            package(self.root,self.target,bridge=True,release_id=release_id)

    def test_bridge_metadata_complete_runtime_no_active_auth_and_no_overwrite(self):
        self.pack()
        root=self.extract()
        self.assertGreater(check(root),20)
        meta=json.loads((root/'release-files.json').read_text())
        self.assertEqual(meta['version'],'schema5-compat-v1')
        self.assertEqual(meta['supported_planner_schemas'],[4,5])
        self.assertEqual(meta['planner_schema'],4)  # migration target, not installed DB
        self.assertFalse(meta['web_auth_enabled'])
        for name in ('planner/schema5_compatibility.py','planner/web_auth/schema.py','planner/web_auth/validation.py'):
            self.assertIn(name,meta['files'])
        for name in ('bot.py','.env','planner.db','planner/web_auth/migration.py','planner/web_auth/policy.py','planner/web_auth/models.py'):
            self.assertNotIn(name,meta['files'])
        old=self.target.read_bytes()
        with self.assertRaises(FileExistsError): self.pack()
        self.assertEqual(old,self.target.read_bytes())
        self.assertEqual(Path(str(self.target)+'.sha256').read_text().split()[0],hashlib.sha256(old).hexdigest())

    def test_rehashed_missing_capability_and_wrong_identity_are_refused(self):
        self.pack();root=self.extract();meta_path=root/'release-files.json'
        meta=json.loads(meta_path.read_text())
        name='planner/web_auth/validation.py'
        (root/name).unlink();meta['files'].pop(name);meta_path.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError,'Incomplete bridge'): check(root)
        meta['release']='planner-2.1.1-not-a-bridge';meta_path.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError,'identity'): check(root)

    def test_disjoint_profile_and_release_ids(self):
        for kwargs in ({'bridge':True,'planner_only':True,'release_id':'planner-2.1.1-test'},
                       {'bridge':True,'stage2':True,'release_id':'planner-schema5-bridge-test'},
                       {'bridge':True,'release_id':'planner-2.1.1-test'}):
            with self.assertRaises(ValueError): package(self.root,self.target,**kwargs)

    def test_legacy_profile_omits_bridge_and_rejects_schema5_in_extracted_runtime(self):
        tracked='\n'.join(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())
        with patch('deploy.package_release.build_frontend'), patch('deploy.package_release.subprocess.check_output',side_effect=['a'*40,tracked,'']):
            package(self.root,self.target,planner_only=True,release_id='planner-2.1.1-test')
        root=self.extract();check(root)
        self.assertFalse((root/'planner/schema5_compatibility.py').exists())
        self.assertFalse((root/'planner/web_auth').exists())
        db_path=Path(self.temp.name)/'synthetic.db';create_schema4(db_path)
        db=connect(db_path)
        try: migrate_synthetic(db,applied_at=1)
        finally: db.close()
        code="""
import sys
from pathlib import Path
from planner.store import Store
try: Store(Path(sys.argv[1])).initialize()
except RuntimeError: print('legacy-refused')
else: raise AssertionError('legacy must refuse schema5')
"""
        result=subprocess.run([sys.executable,'-B','-c',code,str(db_path)],cwd=root,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'legacy-refused')

    def test_extracted_bridge_import_startup_backup_without_migration_module(self):
        self.pack();root=self.extract()
        code="""
import sys
from pathlib import Path
from planner.store import Store
from planner.backup import create_backup,verify_backup
path=Path(sys.argv[1]);Store(path).initialize()
assert 'planner.web_auth.migration' not in sys.modules
copy=create_backup(path,Path(sys.argv[2]));verify_backup(copy)
import planner.api
assert 'planner.web_auth.policy' not in sys.modules
print('bridge-smoke-ok')
"""
        for version in (4,5):
            path=Path(self.temp.name)/f'synthetic-{version}.db';create_schema4(path)
            if version==5:
                db=connect(path)
                try: migrate_synthetic(db,applied_at=1)
                finally: db.close()
            result=subprocess.run([sys.executable,'-B','-c',code,str(path),self.temp.name],cwd=root,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),'bridge-smoke-ok')
