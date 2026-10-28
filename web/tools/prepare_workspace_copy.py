"""Explicit reviewed-copy preparation; never a working database migration command."""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument(
        "--planner-source", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args()
    if args.planner_source.resolve(strict=True) != Path(__file__).resolve().parents[2]:
        raise ValueError("Only this checkout Planner core is allowed")
    sys.path.insert(0, str(args.planner_source.resolve(strict=True)))
    from planner.migration_copy import prepare_copy

    print(json.dumps(prepare_copy(args.source, args.destination), ensure_ascii=True))


if __name__ == "__main__":
    main()
