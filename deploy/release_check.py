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
    files = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink in release')
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if name == 'release-files.json':
            continue
        if any(p in {'.env', 'node_modules', '__pycache__'} for p in path.relative_to(root).parts) or path.suffix in {'.db', '.sqlite', '.map', '.pyc'}:
            raise ValueError('Forbidden release file')
        raw = path.read_bytes()
        if re.search(rb'\d{5,}:[A-Za-z0-9_-]{20,}|https?://[^\s"\x27]+/rest/\d+/[A-Za-z0-9_-]+/', raw):
            raise ValueError('Credential-like literal in release')
        files[name] = hashlib.sha256(raw).hexdigest()
    manifest = json.loads((root / 'release-files.json').read_text(encoding='utf-8'))
    if manifest['files'] != files:
        raise ValueError('Release checksum mismatch')
    validate_static(root / 'miniapp/dist', root / 'frontend-build.json')
    return len(files)


if __name__ == '__main__':
    print('Release integrity OK:', check(ROOT), 'files; planner schema 4, queue schema 1')
