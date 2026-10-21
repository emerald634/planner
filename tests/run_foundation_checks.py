"""Safe local unittest runner: temporary SQLite only, no external sockets/secrets.

Run from the repository root: python -B -m tests.run_foundation_checks
The optional --new flag selects the three foundation suites only.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from urllib.parse import urlsplit
from urllib.request import url2pathname


def main():
    root = Path(__file__).resolve().parents[1]
    scratch = root / "test-artifacts" / "foundation-temp"
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(scratch)
    tempfile.tempdir = str(scratch)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    for key in tuple(os.environ):
        if any(part in key.upper() for part in ("TOKEN", "PASSWORD", "SECRET", "WEBHOOK")):
            os.environ.pop(key, None)

    def under_scratch(path):
        try:
            if isinstance(path, str) and path.startswith("file:"):
                uri = urlsplit(path)
                if uri.netloc not in ("", "localhost"):
                    return False
                path = url2pathname(uri.path)
            Path(path).resolve().relative_to(scratch.resolve())
            return True
        except (ValueError, TypeError):
            return False

    def safety(event, args):
        if event == "sqlite3.connect":
            if args[0] != ":memory:" and not under_scratch(args[0]):
                raise PermissionError("Test SQLite must be inside the synthetic scratch directory")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            name = Path(os.fsdecode(args[0])).name.lower()
            if (name == ".env" or name.endswith(".env")) and not under_scratch(args[0]):
                raise PermissionError("Working secrets cannot be read by tests")
        if event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
                raise PermissionError("External test networking is disabled")
        if event == "socket.getaddrinfo" and args[0] not in (None, "localhost", "127.0.0.1", "::1"):
            raise PermissionError("External test DNS is disabled")

    sys.addaudithook(safety)
    if "--new" in sys.argv:
        suite = unittest.defaultTestLoader.loadTestsFromNames([
            "tests.test_web_auth_foundation", "tests.test_web_auth_schema", "tests.test_web_auth_migration"])
        label = "new"
    else:
        suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
        label = "full"

    class Recorded(unittest.TextTestResult):
        def startTest(self, test):
            self.test_ids.append(test.id())
            super().startTest(test)

        test_ids = []

    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=1, resultclass=Recorded).run(suite)
    report = {"suite": label, "tests": result.test_ids, "count": result.testsRun,
              "seconds": round(time.monotonic() - started, 3), "successful": result.wasSuccessful(),
              "failures": [test.id() for test, _ in result.failures],
              "errors": [test.id() for test, _ in result.errors], "skipped": len(result.skipped)}
    (root / "test-artifacts" / f"foundation-{label}-results.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
