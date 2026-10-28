"""No implicit env lookup; validate explicitly configured service secret files."""

import os
from pathlib import Path


def secret_file(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Absolute regular secret file required")
    info = path.stat()
    if not path.is_file() or info.st_size > 1024 or info.st_nlink != 1:
        raise ValueError("Invalid secret file")
    if os.name != "nt" and info.st_mode & 0o077:
        raise ValueError("Secret file must be owner-only")
    value = path.read_text(encoding="ascii").strip()
    if len(value) < 43 or not all(c.isalnum() or c in "-_" for c in value):
        raise ValueError("Service secret must have >=43 URL-safe characters; generate randomly")
    return value
