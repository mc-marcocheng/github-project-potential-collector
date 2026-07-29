from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from collector.archive import download_archive_hour, inspect_archive
from collector.config import Config
from collector.pipeline import run_with_git_storage
from collector.storage import initialize_local_data_repo
from collector.util import parse_utc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collector",
        description="Prospective GitHub repository launch collector",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "run",
        help="Run discovery, snapshots, observations, and health reporting",
    )

    inspect_parser = subparsers.add_parser(
        "inspect-archive",
        help="Inspect one GH Archive hour without making GitHub API requests",
    )
    inspect_parser.add_argument(
        "--hour",
        required=True,
        help="UTC hour, for example 2026-03-01T12:00:00Z",
    )
    inspect_parser.add_argument(
        "--output",
        type=Path,
        help="Optional location for the downloaded .json.gz file",
    )

    init_parser = subparsers.add_parser(
        "init-local-data",
        help="Initialize a local data-repository directory",
    )
    init_parser.add_argument("path", type=Path)
    init_parser.add_argument(
        "--start-hour",
        required=True,
        help="First GH Archive hour to process",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "run":
        config = Config.from_environment()
        run_with_git_storage(config)
        return 0

    if args.command == "inspect-archive":
        hour = parse_utc(args.hour)
        path = download_archive_hour(hour, destination=args.output)
        report = inspect_archive(path)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    if args.command == "init-local-data":
        initialize_local_data_repo(
            args.path,
            first_hour=parse_utc(args.start_hour),
        )
        print(f"Initialized data directory: {args.path}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
