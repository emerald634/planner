"""Build React locally, then package a strictly allowlisted API release."""
import argparse
import os
import hashlib
import io
import json
import shutil
import subprocess
import re
import tempfile
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
    for args in (("install", "--offline", "--frozen-lockfile", "--prod=false"), ("run", "build")):
        try:
            subprocess.run([executable, *args], cwd=root / "miniapp", env=environment, check=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("Production-сборка не завершена. Выполните локально pnpm install --frozen-lockfile, проверьте ошибку выше и повторите упаковку. Архив не создан.") from error
    if lock.read_bytes() != before:
        raise ValueError("Lockfile изменился во время сборки; архив не создан.")


def package(root: Path, target: Path, pnpm: str | None = None, stage2: bool = False,
            *, planner_only: bool = False, release_id: str | None = None):
    if planner_only and stage2:
        raise ValueError("Выберите planner-only или stage2, не оба режима.")
    if planner_only and (not release_id or not re.fullmatch(r"planner-2\.1\.1-[a-z0-9][a-z0-9.-]{0,60}", release_id)):
        raise ValueError("Для planner-only нужен уникальный --release-id вида planner-2.1.1-rc1-20261021.")
    if release_id and not planner_only:
        raise ValueError("--release-id поддерживается только вместе с --planner-only.")
    if target.exists():
        raise FileExistsError("Архив уже существует; выберите новое имя.")
    sidecars = [Path(str(target) + suffix) for suffix in ('.sha256', '.files.txt')]
    if planner_only and any(path.exists() for path in sidecars):
        raise FileExistsError("Контрольные файлы уже существуют; выберите новое имя.")
    files = list(FILES)
    if stage2:
        files += ["bot.py", "bitrix.py", "config.py", "distribution.py", "keyboards.py", "reminders.py", "requirements.txt", "compose.bot.release.yaml", "deploy/Bot.Dockerfile", "deploy/Bot.Dockerfile.dockerignore", "deploy/bot-release-compose.sh", "STAGE2_1_RELEASE.md", "deploy/release_check.py", "deploy/sqlite_mount_check.py", "deploy/test_release_chain.py"]
        files += ['STAGE2_1_FINAL_CHECKS.md']
    elif planner_only:
        files += ['deploy/release_check.py', 'HOTFIX_2_1_1_RELEASE.md']
    files += [p.relative_to(root).as_posix() for p in sorted((root / "planner").glob("*.py"))]
    for name in files:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Отсутствует необходимый исходный файл или найден symlink.")
    commit = None
    if planner_only:
        try:
            commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
            tracked = set(subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines())
            dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True)
            if not re.fullmatch(r'[0-9a-f]{40}', commit) or not set(files) <= tracked or dirty:
                raise ValueError("Исходники релиза должны быть сохранены в чистом Git-коммите.")
        except subprocess.CalledProcessError:
            raise ValueError("Не удалось проверить Git-коммит релиза.") from None
        source_hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in tracked}
    build_frontend(root, pnpm)
    if planner_only and any(hashlib.sha256((root / name).read_bytes()).hexdigest() != digest for name, digest in source_hashes.items()):
        raise ValueError("Исходники изменились во время сборки; архив не создан.")
    assets = validate_static(root / "miniapp/dist")
    files += ["miniapp/dist/" + name for name in assets]
    provenance = {'release': release_id, 'git_commit': commit} if planner_only else {}
    manifest = json.dumps({"schema": 1, "assets": assets, **provenance,
        "lockfile_sha256": hashlib.sha256((root / "miniapp/pnpm-lock.yaml").read_bytes()).hexdigest(),
        "built_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    overrides = {}
    if planner_only:
        example = (root / 'deploy/planner.env.example').read_text(encoding='utf-8')
        example, count = re.subn(r'^PLANNER_IMAGE=.*$', 'PLANNER_IMAGE=bitrix-workday-planner:' + release_id, example, flags=re.M)
        if count != 1:
            raise ValueError('Не найден единственный PLANNER_IMAGE в шаблоне.')
        example = re.sub(r'^BOT_RELEASE_IMAGE=.*\n?', '', example, flags=re.M)
        overrides['deploy/planner.env.example'] = example.encode('utf-8')
    # Assemble and validate away from the checkout before publishing any artifact.
    # Exclusive final creation preserves all older releases, including on failure.
    with tempfile.TemporaryDirectory(prefix='planner-package-') as directory:
        candidate = Path(directory) / 'candidate.tar.gz'
        _write_archive(root, candidate, files, manifest, stage2, planner_only, release_id, commit, overrides)
        if stage2 or planner_only:
            extracted = Path(directory) / 'release'
            with tarfile.open(candidate) as archive:
                archive.extractall(extracted, filter='data')
            from deploy.release_check import check
            check(extracted)
        created = []
        try:
            with target.open('xb') as destination:
                created.append(target)
                with candidate.open('rb') as source:
                    shutil.copyfileobj(source, destination)
            if planner_only:
                content = [hashlib.sha256(target.read_bytes()).hexdigest() + '  ' + target.name + '\n',
                           '\n'.join(sorted(files + ['frontend-build.json', 'release-files.json'])) + '\n']
                for path, value in zip(sidecars, content):
                    with path.open('x', encoding='utf-8', newline='\n') as stream:
                        created.append(path)
                        stream.write(value)
        except BaseException:
            for path in reversed(created):
                path.unlink()
            raise


def _write_archive(root, target, files, manifest, stage2, planner_only, release_id, commit, overrides):
    with target.open("xb") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name in sorted(files):
                path = root / name
                info = archive.gettarinfo(str(path), arcname=name)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                raw = overrides.get(name, path.read_bytes())
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            info = tarfile.TarInfo("frontend-build.json")
            info.size = len(manifest)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(manifest))
            if stage2 or planner_only:
                checksums = {name: hashlib.sha256(overrides.get(name, (root / name).read_bytes())).hexdigest() for name in sorted(files)}
                checksums['frontend-build.json'] = hashlib.sha256(manifest).hexdigest()
                metadata = {'schema': 1, 'component': 'planner', 'version': '2.1.1', 'git_commit': commit} if planner_only else {}
                content = json.dumps({'release': release_id if planner_only else 'stage2-1-production-v1',
                                      'planner_schema': 4, 'queue_schema': 1, 'files': checksums, **metadata}, ensure_ascii=False, indent=2).encode('utf-8')
                info = tarfile.TarInfo('release-files.json')
                info.size = len(content)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(content))


def main():
    parser = argparse.ArgumentParser(description="Упаковка исходников Mini App без секретов и рабочих файлов бота")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pnpm", help="Путь к локальному pnpm, если его нет в PATH")
    parser.add_argument("--stage2", action="store_true", help="Include both components for stage 2.1")
    parser.add_argument("--planner-only", action="store_true", help="Prepare planner-only hotfix 2.1.1")
    parser.add_argument("--release-id", help="Unique planner-2.1.1-... identifier; required with --planner-only")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = args.output or ROOT / "deployment-artifacts" / (f"{args.release_id}.tar.gz" if args.planner_only and args.release_id else f"planner-stage1-{stamp}.tar.gz")
    try:
        package(ROOT, target, args.pnpm, args.stage2, planner_only=args.planner_only, release_id=args.release_id)
        print("Архив Mini App создан:", target)
    except (OSError, ValueError, tarfile.TarError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
