from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .aggregator import DEFAULT_STATE_PATH, collect_usage, parse_window, write_state


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "collect":
        return collect_command(args)
    if args.command == "show":
        return show_command(args)

    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="faium", description="Fedora AI Usage Monitor")
    subparsers = parser.add_subparsers(dest="command")

    collect = subparsers.add_parser("collect", help="Aggregate local AI agent usage logs")
    collect.add_argument("--output", type=Path, default=DEFAULT_STATE_PATH)
    collect.add_argument("--window", default="24h", help="Time window such as month, 24h, 7d, or all")
    collect.add_argument("--watch", action="store_true", help="Refresh continuously")
    collect.add_argument("--interval", type=int, default=900, help="Watch refresh interval in seconds")
    collect.set_defaults(command="collect")

    show = subparsers.add_parser("show", help="Print the current aggregated state")
    show.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    show.set_defaults(command="show")

    return parser


def collect_command(args: argparse.Namespace) -> int:
    while True:
        since, window_label = parse_window(args.window)
        state = collect_usage(since=since, window_label=window_label)
        output = write_state(state, args.output)
        print(f"wrote {output}")
        if not args.watch:
            return 0
        time.sleep(max(args.interval, 5))


def show_command(args: argparse.Namespace) -> int:
    state_path = args.state.expanduser()
    if not state_path.exists():
        print(f"No FAIUM state found at {state_path}", file=sys.stderr)
        return 1

    state = json.loads(state_path.read_text(encoding="utf-8"))
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
