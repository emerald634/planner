"""Build both ordinary frontends, then create a new allowlisted review bundle."""

import argparse
import hashlib
import json
import re
import shutil
import sys
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True)


def build():
    node = shutil.which("node")
    if not node:
        raise ValueError("Node22+ and installed frozen dependencies required")
    for folder, type_args in (
        (ROOT / "web/frontend", ["-b"]),
        (ROOT / "miniapp", ["--noEmit"]),
    ):
        run([node, "node_modules/typescript/bin/tsc", *type_args], folder)
        run([node, "node_modules/vite/bin/vite.js", "build"], folder)


def package(target):
    if target.exists():
        raise FileExistsError("Choose a NEW release archive")
    build()  # No stale-dist-only bypass. No dependency installation here.
    sys.path.insert(0, str(ROOT))
    from planner.frontend import validate_static

    mini_assets = validate_static(ROOT / "miniapp/dist")
    manifest = {
        "schema": 1,
        "assets": mini_assets,
        "lock_sha256": hashlib.sha256(
            (ROOT / "miniapp/pnpm-lock.yaml").read_bytes()
        ).hexdigest(),
    }
    files = {"frontend-build.json": json.dumps(manifest).encode()}
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    for name in tracked:
        if not name:
            continue
        path = Path(name)
        if path.suffix.lower() in {
            ".py",
            ".toml",
            ".ini",
            ".mako",
            ".yaml",
            ".yml",
            ".txt",
            ".md",
            ".json",
            ".lock",
            ".ts",
            ".tsx",
            ".css",
            ".html",
            ".svg",
            ".js",
            ".cjs", ".patch", ".example",
        } or path.name.endswith(("Dockerfile", ".dockerignore")):
            if (
                name.startswith(".github/")
                or (path.name.startswith(".env") and path.name != ".env.example")
                or path.suffix in {".map"}
            ):
                continue
            files[name] = (ROOT / path).read_bytes()
    for folder in ("web/frontend/dist", "miniapp/dist"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file():
                assert not path.is_symlink() and path.suffix in {
                    ".js",
                    ".css",
                    ".html",
                    ".svg",
                    ".png",
                    ".ico",
                    ".woff",
                    ".woff2",
                }
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for name, value in files.items():
        assert not any(
            p in Path(name).parts
            for p in ("node_modules", ".git", ".workbench", "dist-mvp")
        ), name
        assert Path(name).suffix not in {".db", ".sqlite", ".map", ".key", ".pem"}, name
        assert not re.search(
            rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b\d{8,12}:[A-Za-z0-9_-]{30,}\b",
            value,
        ), name
    release = {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
        .decode()
        .strip(),
        "upstream_leadflow": "0fa3719e8aede5f81e250be42c5d3a009ea78d96",
        "upstream_planner": "01cf5ae9d10e22b0b1557e79e22cc84e9f781273",
        "schemas": {
            "planner": 4,
            "queue": 1,
            "daily_extension": 1,
            "crm_observations": 1,
            "auth": "0005_workspace_links",
        },
        "production_verified": False,
        "files": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(files.items())},
    }
    files["workspace-release.json"] = json.dumps(release, indent=2).encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for name, digest in release["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
    target.with_suffix(target.suffix + ".sha256").write_text(
        hashlib.sha256(target.read_bytes()).hexdigest() + "  " + target.name + "\n"
    )
    target.with_suffix(target.suffix + ".manifest.json").write_text(
        json.dumps(release, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {"archive": str(target), "files": len(files), "production_verified": False}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    package(args.output.resolve())
