"""Docker smoke check using an isolated /queue directory only, no production DB."""
import argparse
import os
import sqlite3
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=('init', 'writer', 'reader'))
args = parser.parse_args()
path = Path('/queue/mount-test.db')
assert os.getuid() == 10001 and os.getgid() == 10001
if args.mode == 'init':
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE ticks(id INTEGER PRIMARY KEY)')
elif args.mode == 'writer':
    for _ in range(100):
        with sqlite3.connect(path, timeout=3) as db:
            db.execute('INSERT INTO ticks DEFAULT VALUES')
        time.sleep(0.1)
else:
    assert path.stat().st_uid == 10001 and path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3) as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
        first = db.execute('SELECT count(*) FROM ticks').fetchone()[0]
        time.sleep(0.3)
        assert db.execute('SELECT count(*) FROM ticks').fetchone()[0] > first
    try:
        with sqlite3.connect(path) as db:
            db.execute('INSERT INTO ticks DEFAULT VALUES')
    except sqlite3.OperationalError:
        print('PASS: UID/GID, live writer, read-only mount, DELETE journal')
    else:
        raise RuntimeError('Queue mount is writable!')
