"""Read Git objects; report paths/categories only, never suspected secret values."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private-key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "telegram-token": rb"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b",
    "webhook-key": rb"https://[^\s\x22\x27<>]+/rest/\d+/[A-Za-z0-9]{16,}",
    "credential-dsn": rb"postgres(?:ql)?(?:\+\w+)?://[^\s:@/]+:[^\s@/]+@",
}


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def scan(revision="HEAD", base=None):
    objects = (
        git(
            "rev-list",
            "--objects",
            revision if base is None else base + ".." + revision,
        )
        .decode()
        .splitlines()
    )
    findings = []
    count = 0
    batch = subprocess.check_output(
        ["git", "-C", str(ROOT), "cat-file", "--batch"],
        input=("\n".join(line.split(" ", 1)[0] for line in objects) + "\n").encode(),
    )
    cursor = 0
    for line in objects:
        identifier, _, name = line.partition(" ")
        end = batch.index(b"\n", cursor)
        _, kind, size = batch[cursor:end].split()
        cursor = end + 1
        data = batch[cursor : cursor + int(size)]
        cursor += int(size) + 1
        if kind != b"blob":
            continue
        count += 1
        path = Path(name)
        if path.name == ".env" or path.suffix.lower() in {
            ".db",
            ".sqlite",
            ".sqlite3",
            ".pem",
            ".pfx",
        }:
            findings.append(
                {"path": name, "category": "private-file", "object": identifier}
            )
        for category, pattern in PATTERNS.items():
            matches = list(re.finditer(pattern, data))
            # Explicit artificial DSNs occur in test fixtures and old config examples.
            matches = [
                m
                for m in matches
                if not (
                    category == "credential-dsn"
                    and (
                        b"synthetic" in m.group() or b"lead_app:lead_app@" in m.group()
                    )
                )
            ]
            if matches:
                findings.append(
                    {"path": name, "category": category, "object": identifier}
                )
    return {
        "revision": revision,
        "base": base,
        "blobs_scanned": count,
        "findings": findings,
        "passed": not findings,
        "limits": "Pattern/path scan, not universal DLP; synthetic fixtures explicitly identified. Git author identities and existing protocol bindings retained.",
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--base")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = scan(args.revision, args.base)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)
