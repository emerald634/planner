"""Build React locally, then package a strictly allowlisted API release."""
import argparse
import os
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from planner.frontend import validate_static
FILES = (
    "access.py", "requirements-planner.txt", "requirements-planner.lock.txt", "compose.planner.yaml", "PLANNER.md", "PLANNER_DEPLOY.md",
    "miniapp/package.json", "miniapp/pnpm-lock.yaml", "miniapp/pnpm-workspace.yaml",
    "deploy/Planner.Dockerfile", "deploy/Planner.Dockerfile.dockerignore", "deploy/planner.env.example",
    "deploy/planner.nginx.example", "deploy/planner.nginx.http.example", "deploy/planner-compose.sh",
)


def build_frontend(root: Path, pnpm: str | None = None):
    executable = pnpm or os.getenv("PNPM_EXECUTABLE") or shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm")
    if not executable:
        raise ValueError("pnpm не найден. Добавьте его в PATH или укажите --pnpm полный_путь.")
    lock = root / "miniapp/pnpm-lock.yaml"
    before = lock.read_bytes()
    environment = dict(os.environ, NODE_ENV="production")
    for args in (("install", "--offline", "--frozen-lockfile"), ("run", "build")):
        try:
            subprocess.run([executable, *args], cwd=root / "miniapp", env=environment, check=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("Production-сборка не завершена. Выполните локально pnpm install --frozen-lockfile, проверьте ошибку выше и повторите упаковку. Архив не создан.") from error
    if lock.read_bytes() != before:
        raise ValueError("Lockfile изменился во время сборки; архив не создан.")


def package(root: Path, target: Path, pnpm: str | None = None, stage2: bool = False):
    if target.exists():
        raise FileExistsError("Архив уже существует; выберите новое имя.")
    files = list(FILES)
    if stage2:
        files += ["bot.py", "bitrix.py", "config.py", "distribution.py", "keyboards.py", "reminders.py", "requirements.txt", "compose.bot.release.yaml", "deploy/Bot.Dockerfile", "deploy/Bot.Dockerfile.dockerignore", "deploy/bot-release-compose.sh", "STAGE2_1_RELEASE.md", "deploy/release_check.py", "deploy/sqlite_mount_check.py", "deploy/test_release_chain.py"]
        files += ['STAGE2_1_FINAL_CHECKS.md']
    files += [p.relative_to(root).as_posix() for p in sorted((root / "planner").glob("*.py"))]
    for name in files:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Отсутствует необходимый исходный файл или найден symlink.")
    build_frontend(root, pnpm)
    assets = validate_static(root / "miniapp/dist")
    files += ["miniapp/dist/" + name for name in assets]
    manifest = json.dumps({"schema": 1, "assets": assets,
        "lockfile_sha256": hashlib.sha256((root / "miniapp/pnpm-lock.yaml").read_bytes()).hexdigest(),
        "built_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name in sorted(files):
                path = root / name
                info = archive.gettarinfo(str(path), arcname=name)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with path.open("rb") as source:
                    archive.addfile(info, source)
            info = tarfile.TarInfo("frontend-build.json")
            info.size = len(manifest)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(manifest))
            if stage2:
                checksums = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(files)}
                checksums['frontend-build.json'] = hashlib.sha256(manifest).hexdigest()
                content = json.dumps({'release': 'stage2-1-production-v1', 'planner_schema': 4, 'queue_schema': 1, 'files': checksums}, ensure_ascii=False, indent=2).encode('utf-8')
                info = tarfile.TarInfo('release-files.json')
                info.size = len(content)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(content))


def main():
    parser = argparse.ArgumentParser(description="Упаковка исходников Mini App без секретов и рабочих файлов бота")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pnpm", help="Путь к локальному pnpm, если его нет в PATH")
    parser.add_argument("--stage2", action="store_true", help="Include both components for stage 2.1")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = args.output or ROOT / "deployment-artifacts" / f"planner-stage1-{stamp}.tar.gz"
    try:
        package(ROOT, target, args.pnpm, args.stage2)
        print("Архив Mini App создан:", target)
    except (OSError, ValueError, tarfile.TarError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
