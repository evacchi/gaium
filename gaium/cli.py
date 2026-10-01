from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

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
    parser = argparse.ArgumentParser(prog="gaium", description="GNOME AI Usage Monitor")
    subparsers = parser.add_subparsers(dest="command")

    collect = subparsers.add_parser("collect", help="Aggregate local AI agent usage logs")
    collect.add_argument("--output", type=Path, default=DEFAULT_STATE_PATH)
    collect.add_argument("--window", default="24h", help="Time window such as month, 24h, 7d, or all")
    collect.add_argument("--watch", action="store_true", help="Refresh continuously")
    collect.add_argument("--interval", type=int, default=900, help="Watch refresh interval in seconds")
    collect.set_defaults(command="collect")

    show = subparsers.add_parser("show", help="Display the current aggregated state")
    show.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    show.add_argument("--json", action="store_true", help="Print the raw JSON state")
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
        print(f"No GAIUM state found at {state_path}", file=sys.stderr)
        return 1

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Unable to read GAIUM state at {state_path}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(render_state_table(state, color=use_terminal_colors()))
    return 0


def render_state_table(state: Any, color: bool = False) -> str:
    if not isinstance(state, dict):
        return "Invalid GAIUM state: expected a JSON object."

    window = state.get("window")
    window_label = window.get("label") if isinstance(window, dict) else None
    generated_at = state.get("generated_at") or "unknown"
    title = "GAIUM usage"
    if window_label:
        title += f" · {window_label}"

    totals = state.get("totals")
    if not isinstance(totals, dict):
        totals = {}
    total_tokens = format_count(totals.get("total_tokens", 0))
    total_requests = format_count(totals.get("requests", 0))
    total_cost = format_cost(totals.get("cost_usd", 0), bool(totals.get("cost_estimated")))

    lines = [paint(title, "1;36", color), f"Updated: {generated_at}"]
    lines.append(f"Totals: {total_tokens} tokens  ·  {total_requests} requests  ·  {total_cost}")

    agents = state.get("agents")
    if not isinstance(agents, list) or not agents:
        lines.extend(["", "No agent usage found for this window."])
        return "\n".join(lines)

    headers = ["AGENT", "TOKENS", "INPUT", "OUTPUT", "REQUESTS", "SPEND", "MODEL"]
    rows: list[list[str]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        rows.append([
            str(agent.get("name") or "unknown"),
            format_count(agent.get("total_tokens", 0)),
            format_count(agent.get("input_tokens", 0)),
            format_count(agent.get("output_tokens", 0)),
            format_count(agent.get("requests", 0)),
            format_cost(agent.get("cost_usd", 0), bool(agent.get("cost_estimated"))),
            format_model(agent),
        ])

    if not rows:
        lines.extend(["", "No agent usage found for this window."])
        return "\n".join(lines)

    terminal_width = shutil.get_terminal_size((100, 24)).columns
    widths = [
        min(16, max(len(headers[index]), *(len(row[index]) for row in rows)))
        for index in range(6)
    ]
    model_width = max(8, min(36, terminal_width - sum(widths) - 12))
    widths.append(min(model_width, max(len(headers[-1]), *(len(row[-1]) for row in rows))))

    def table_line(values: list[str], header: bool = False) -> str:
        cells = []
        for index, (value, width) in enumerate(zip(values, widths)):
            value = truncate(value, width)
            aligned = value.ljust(width) if index == 0 or index == len(widths) - 1 else value.rjust(width)
            if header:
                aligned = paint(aligned, "1;36", color)
            elif index == 0:
                aligned = paint(aligned, "1;32", color)
            elif index == 5:
                estimated = value.startswith("~")
                aligned = paint(aligned, "33" if estimated else "32", color)
            cells.append(aligned)
        return "  ".join(cells).rstrip()

    lines.extend(["", table_line(headers, header=True)])
    lines.append(paint("  ".join("─" * width for width in widths), "90", color))
    lines.extend(table_line(row) for row in rows)
    return "\n".join(lines)


def format_count(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError, OverflowError):
        return "0"


def format_cost(value: Any, estimated: bool) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError, OverflowError):
        amount = 0.0
    return f"{'~' if estimated else ''}${amount:,.4f}"


def format_model(agent: dict[str, Any]) -> str:
    active = agent.get("active_model")
    if active:
        return str(active)
    models = agent.get("models")
    if not isinstance(models, list) or not models:
        return "—"
    names = [str(model) for model in models[:2]]
    if len(models) > 2:
        names.append(f"+{len(models) - 2}")
    return ", ".join(names)


def truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def paint(value: str, ansi_code: str, enabled: bool) -> str:
    if not enabled:
        return value
    return f"\033[{ansi_code}m{value}\033[0m"


def use_terminal_colors() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"


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
