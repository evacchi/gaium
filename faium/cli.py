from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .aggregator import (
    DEFAULT_CALIBRATION_PATH,
    DEFAULT_STATE_PATH,
    collect_usage,
    load_calibration,
    parse_window,
    write_calibration,
    write_state,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "collect":
        return collect_command(args)
    if args.command == "show":
        return show_command(args)
    if args.command == "calibrate":
        return calibrate_command(args)

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

    calibrate = subparsers.add_parser("calibrate", help="Normalize estimated spend to observed monthly spend")
    calibrate.add_argument("targets", nargs="+", help="Agent spend targets such as claude=7 codex=8")
    calibrate.add_argument("--window", default="month", help="Window to calibrate, usually month")
    calibrate.add_argument("--config", type=Path, default=DEFAULT_CALIBRATION_PATH)
    calibrate.set_defaults(command="calibrate")

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


def calibrate_command(args: argparse.Namespace) -> int:
    targets = parse_calibration_targets(args.targets)
    since, window_label = parse_window(args.window)
    state = collect_usage(since=since, window_label=window_label, calibration_path=None)

    current = {agent["name"]: float(agent["raw_cost_usd"]) for agent in state["agents"]}
    calibration = load_calibration(args.config)

    for agent, target in targets.items():
        raw_cost = current.get(agent, 0.0)
        if raw_cost <= 0:
            print(f"Cannot calibrate {agent}: current raw cost is {raw_cost:.6f}", file=sys.stderr)
            return 1
        calibration[agent] = target / raw_cost

    output = write_calibration(calibration, args.config)
    print(f"wrote {output}")
    for agent, target in targets.items():
        print(f"{agent}: target=${target:.2f} multiplier={calibration[agent]:.8f}")
    return 0


def parse_calibration_targets(values: list[str]) -> dict[str, float]:
    targets = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"calibration target must use agent=amount: {value}")
        agent, amount = value.split("=", 1)
        agent = agent.strip()
        if not agent:
            raise SystemExit(f"calibration target is missing an agent name: {value}")
        try:
            target = float(amount.strip().removeprefix("$"))
        except ValueError as exc:
            raise SystemExit(f"calibration target has invalid amount: {value}") from exc
        if target < 0:
            raise SystemExit(f"calibration target cannot be negative: {value}")
        targets[agent] = target
    return targets


if __name__ == "__main__":
    raise SystemExit(main())
