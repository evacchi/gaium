# FAIUM

FAIUM is the Fedora AI Usage Monitor: a GNOME Shell top-bar indicator plus a local usage aggregation pipeline for AI agent logs.

The first implementation uses a simple local JSON state file:

```text
~/.local/state/ai-agent-usage.json
```

The Python CLI refreshes that file. The GNOME Shell extension watches the file and renders current token usage, request count, spend, active models, and per-agent rows in the top bar menu.

## Repository Layout

```text
faium/                    Python aggregator CLI
extension/faium@local/    GNOME Shell extension
systemd/                  User service and timer
scripts/                  Local install helpers
tests/                    Aggregator tests
```

## Install Locally

Install the runtime CLI wrapper into `~/.local/bin`:

```bash
scripts/install-cli.sh
```

Generate the first usage state file:

```bash
faium collect --window 24h
```

For a calendar-month total, use:

```bash
faium collect --window month
```

`month` starts at local midnight on the first day of the current calendar month. Rolling windows such as `24h` and `7d` count backward from the current time.

This runtime path intentionally does not require `uv` or `pip`; it is what the systemd user timer uses.

For development, use `uv`.

Install and enable the GNOME extension:

```bash
scripts/install-extension.sh
gnome-extensions enable faium@local
```

Run those as two separate commands. The install script packages the extension and installs it through `gnome-extensions install --force` when GNOME's extension tooling is available.

If the extension does not appear immediately, restart GNOME Shell or log out and back in. On Wayland, logging out and back in is the reliable path.

Enable the 15-minute background refresh timer:

```bash
scripts/install-systemd-user.sh
```

Check the timer:

```bash
systemctl --user status faium-usage.timer
```

## Agent Logs

FAIUM currently scans these local paths when present:

```text
~/.codex/state_5.sqlite
~/.codex/sessions
~/.claude/logs
~/.claude/projects
```

For Claude-style logs, it accepts JSON, JSONL, log, and text files that contain JSON objects with common usage fields such as `usage.input_tokens`, `usage.output_tokens`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `model`, and `created_at`.

For Codex Desktop, it reads `tokens_used`, `model`, and thread timestamps from `~/.codex/state_5.sqlite`. Codex rows are currently thread-level totals, filtered by each thread's last updated time.

## Spend Estimates

FAIUM writes `cost_usd` into the state file and the panel menu displays that monthly aggregate spend. When logs do not contain a provider-billed cost, FAIUM estimates spend from bundled per-model pricing in `faium/pricing.py`.

Claude logs include input, output, cache-write, and cache-read token counters, so Claude spend estimates include prompt caching. Codex Desktop currently exposes thread-level `tokens_used` totals locally, not a full input/output/cache breakdown, so Codex spend is marked with `cost_estimated: true` and `cost_notes: ["total tokens only"]`.

Pricing changes over time. Update `faium/pricing.py` when provider rates change or when you want to use account-specific contract rates.

## Shortcut Recipe

Create a custom GNOME shortcut:

1. Open Settings.
2. Go to Keyboard.
3. Open View and Customize Shortcuts.
4. Add a custom shortcut bound to `Super + Shift + Ctrl + A`.
5. Use one of these commands:

```bash
ptyxis -- bash -c "a"
ptyxis -- bash -c "claude"
ptyxis -- bash -c "codex"
```

For a shell-controlled default agent, add this to `~/.bashrc` or `~/.zshrc`:

```bash
export DEFAULT_AI_AGENT="claude"
a() {
  "${DEFAULT_AI_AGENT:-claude}" "$@"
}
```

## Development

FAIUM is managed with `uv`. Create or refresh the local virtual environment and lockfile:

```bash
uv sync
```

Run tests:

```bash
uv run python -m unittest discover
```

Refresh state while developing:

```bash
uv run faium collect --window 24h --watch --interval 30
```

Refresh the current calendar month while developing:

```bash
uv run faium collect --window month --watch --interval 30
```

The helper scripts wrap those commands:

```bash
scripts/dev-test.sh
scripts/dev-collect.sh
```

FAIUM currently has no third-party Python runtime dependencies. If you do not have `uv`, install it with Fedora's package manager when available, or use the standalone installer from Astral. As a fallback for traditional Python packaging, `python -m pip install --user -e .` also works once `python3-pip` is installed.
