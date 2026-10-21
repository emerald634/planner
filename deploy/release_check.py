"""Read-only release verification. Never loads .env or migrates a database."""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from planner.frontend import validate_static


def check(root):
    root = Path(root)
    if root.is_symlink() or (root / 'release-files.json').is_symlink():
        raise ValueError('Symlink in release')
    manifest = json.loads((root / 'release-files.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), dict):
        raise ValueError('Invalid release manifest')
    if manifest.get('planner_schema') != 4 or manifest.get('queue_schema') != 1:
        raise ValueError('Unexpected database schema versions')
    bridge = manifest.get('profile') == 'schema5-bridge'
    if bridge and manifest.get('component') != 'planner':
        raise ValueError('Invalid bridge component')
    if manifest.get('component') == 'planner':
        pattern = r'planner-schema5-bridge-[a-z0-9][a-z0-9.-]{0,60}' if bridge else r'planner-2\.1\.1-[a-z0-9][a-z0-9.-]{0,60}'
        if bridge:
            from planner.schema5_compatibility import BRIDGE_VERSION, MANIFEST_CHECKSUM
            if (manifest.get('version') != BRIDGE_VERSION or manifest.get('supported_planner_schemas') != [4, 5]
                    or manifest.get('web_auth_enabled') is not False
                    or manifest.get('schema5_manifest_sha256') != MANIFEST_CHECKSUM):
                raise ValueError('Invalid bridge capability manifest')
        elif manifest.get('version') != '2.1.1' or 'profile' in manifest:
            raise ValueError('Unknown planner release profile')
        if (manifest.get('schema') != 1
                or not re.fullmatch(pattern, str(manifest.get('release', '')))
                or not re.fullmatch(r'[0-9a-f]{40}', str(manifest.get('git_commit', '')))):
            raise ValueError('Invalid planner release identity')
    elif manifest.get('release') != 'stage2-1-production-v1' or 'component' in manifest:
        raise ValueError('Unknown release profile')
    files = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink in release')
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if name == 'release-files.json':
            continue
        capability = name == 'planner/schema5_compatibility.py' or name.startswith('planner/web_auth/')
        if capability and not bridge:
            raise ValueError('Bridge capability in legacy release')
        if name.startswith('planner/web_auth/') and name not in {
                'planner/web_auth/__init__.py', 'planner/web_auth/schema.py', 'planner/web_auth/validation.py'}:
            raise ValueError('Active auth or migration module in bridge release')
        parts = path.relative_to(root).parts
        if (any(p in {'.env', 'node_modules', '__pycache__', '.git', 'desktop', 'distribution-queue', 'backups'} for p in parts)
                or re.search(r'\.(?:db|sqlite3?)(?:-(?:journal|wal|shm))?$', name)
                or path.suffix in {'.map', '.pyc', '.zip', '.gz', '.log', '.key', '.pem'}
                or (path.name.startswith('.env') and path.name != '.env.example')
                or (path.name.endswith('.env') or path.name.startswith('demo.'))):
            raise ValueError('Forbidden release file')
        if manifest.get('component') == 'planner' and (name in {'bot.py', 'bitrix.py', 'config.py', 'distribution.py', 'keyboards.py', 'reminders.py', 'compose.bot.release.yaml'} or 'Bot.Dockerfile' in name):
            raise ValueError('Bot files in planner-only release')
        raw = path.read_bytes()
        if re.search(rb'\d{5,}:[A-Za-z0-9_-]{20,}|https?://[^\s"\x27]+/rest/\d+/[A-Za-z0-9_-]+/', raw):
            raise ValueError('Credential-like literal in release')
        files[name] = hashlib.sha256(raw).hexdigest()
    if manifest['files'] != files:
        raise ValueError('Release checksum mismatch')
    if bridge:
        required = {'access.py', 'requirements-planner.txt', 'requirements-planner.lock.txt',
            'compose.planner.yaml', 'deploy/Planner.Dockerfile', 'deploy/release_check.py',
            'planner/schema5_compatibility.py', 'planner/web_auth/__init__.py',
            'planner/web_auth/schema.py', 'planner/web_auth/validation.py'}
        required.update('planner/' + name + '.py' for name in (
            '__init__', 'api', 'auth', 'backup', 'distribution_import', 'distribution_queue',
            'frontend', 'integrations', 'models', 'ops', 'settings', 'store', 'sync'))
        if not required <= files.keys():
            raise ValueError('Incomplete bridge runtime')
    validate_static(root / 'miniapp/dist', root / 'frontend-build.json')
    frontend = json.loads((root / 'frontend-build.json').read_text(encoding='utf-8'))
    if frontend.get('lockfile_sha256') != hashlib.sha256((root / 'miniapp/pnpm-lock.yaml').read_bytes()).hexdigest():
        raise ValueError('Frontend lockfile checksum mismatch')
    if manifest.get('component') == 'planner' and any(frontend.get(key) != manifest[key] for key in ('release', 'git_commit')):
        raise ValueError('Frontend and release identity mismatch')
    if manifest.get('component') == 'planner':
        example = (root / 'deploy/planner.env.example').read_text(encoding='utf-8')
        if ('PLANNER_IMAGE=bitrix-workday-planner:' + manifest['release']) not in example.splitlines() or re.search(r'^BOT_RELEASE_IMAGE=', example, re.M):
            raise ValueError('Planner image tag mismatch')
    return len(files)


if __name__ == '__main__':
    print('Release integrity OK:', check(ROOT), 'files; business migration schema 4, queue schema 1; capabilities in release-files.json')
