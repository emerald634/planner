import json
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from deploy.package_release import ROOT, package
from planner.frontend import validate_static


class FrontendReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dist = self.root / "miniapp/dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text('<script src="/assets/index-abc.js"></script><link rel="stylesheet" href="/assets/index-abc.css">', encoding="utf-8")
        (self.dist / "assets/index-abc.js").write_text('console.log("production");', encoding="utf-8")
        (self.dist / "assets/index-abc.css").write_text('body{color:black}', encoding="utf-8")

    def test_manifest_detects_tampering(self):
        manifest = self.root / "frontend-build.json"
        manifest.write_text(json.dumps({"schema": 1, "assets": validate_static(self.dist)}), encoding="utf-8")
        validate_static(self.dist, manifest)
        (self.dist / "assets/index-abc.js").write_text('changed', encoding="utf-8")
        with self.assertRaises(ValueError):
            validate_static(self.dist, manifest)

    def test_rejects_demo_maps_missing_and_secrets(self):
        asset = self.dist / "assets/index-abc.js"
        for text in ('preview.html?role=supervisor', 'BOT_TOKEN', '123456:abcdefghijklmnopqrstuvw'):
            asset.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_static(self.dist)
        asset.write_text('production', encoding="utf-8")
        extra = self.dist / "assets/index-abc.js.map"
        extra.write_text('{}', encoding="utf-8")
        with self.assertRaises(ValueError):
            validate_static(self.dist)
        extra.unlink()
        asset.unlink()
        with self.assertRaises(ValueError):
            validate_static(self.dist)

    def test_build_failure_creates_no_archive(self):
        target = self.root / "failed.tar.gz"
        with patch("deploy.package_release.build_frontend", side_effect=ValueError("build failed")):
            with self.assertRaises(ValueError):
                package(ROOT, target)
        self.assertFalse(target.exists())

    def test_release_manifest_matches_packaged_assets(self):
        target = self.root / "release.tar.gz"
        with patch("deploy.package_release.build_frontend"):
            package(ROOT, target)
        extracted = self.root / "extracted"
        with tarfile.open(target) as archive:
            archive.extractall(extracted, filter="data")
        validate_static(extracted / "miniapp/dist", extracted / "frontend-build.json")
