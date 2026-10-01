# GAIUM

GAIUM is the GNOME AI Usage Monitor: a GNOME Shell top-bar indicator plus a local usage aggregation pipeline for AI agent logs.

The first implementation uses a simple local JSON state file:

```text
~/.local/state/ai-agent-usage.json
```

The Python CLI refreshes that file. The GNOME Shell extension watches the file and renders current token usage, request count, spend, active models, and per-agent rows in the top bar menu.

## Repository Layout

```text
gaium/                    Python aggregator CLI
extension/gaium@local/    GNOME Shell extension
systemd/                  User service and timer
scripts/                  Local install helpers
tests/                    Aggregator tests
```

## Install Locally

Install the runtime CLI wrapper into `~/.local/bin`:

```bash
scripts/install-cli.sh
```

Generate the first monthly usage state file:

```bash
gaium collect --window month
```

`month` starts at local midnight on the first day of the current calendar month. Rolling windows such as `24h` and `7d` count backward from the current time.

Display the saved usage as a terminal table, or print the raw JSON for scripting:

```bash
gaium show
gaium show --json
```

This runtime path intentionally does not require `uv` or `pip`; it is what the systemd user timer uses.

For development, use `uv`.

Install the GNOME extension files:

```bash
scripts/install-extension.sh
```

On first install, or after changing the extension UUID, GNOME Shell may not discover the new local extension until the next session. If `gnome-extensions enable gaium@local` says the extension does not exist, restart the PC or log out and back in, then run:

```bash
gnome-extensions list --user | grep gaium
gnome-extensions enable gaium@local
```

On Wayland, logging out and back in or restarting the PC is the reliable way to refresh GNOME Shell's local extension registry.

Enable the 15-minute background refresh timer:

```bash
scripts/install-systemd-user.sh
```

Check the timer:

```bash
systemctl --user status gaium-usage.timer
```

## Agent Logs

GAIUM currently scans these local paths when present:

```text
~/.codex/state_5.sqlite
~/.codex/sessions
~/.claude/logs
~/.claude/projects
```

For Claude-style logs, it accepts JSON, JSONL, log, and text files that contain JSON objects with common usage fields such as `usage.input_tokens`, `usage.output_tokens`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `model`, and `created_at`.

For Codex Desktop, it reads `tokens_used`, `model`, and thread timestamps from `~/.codex/state_5.sqlite`. Codex rows are currently thread-level totals, filtered by each thread's last updated time.

To exclude Claude transcripts associated with specific account or organization UUIDs, list those UUIDs in the repo-local, git-ignored `.gaium.local.json` file:

```json
{
  "exclude_claude_identity_ids": ["account-uuid", "organization-uuid"],
  "exclude_claude_session_ids": ["session-uuid"]
}
```

GAIUM skips the entire Claude session when a structured identity field in any event matches one of the identity values, or when its session ID is listed explicitly. Claude can write identity metadata and transcript events to separate files, so GAIUM also excludes files linked by a matching session ID. It does not exclude a transcript merely because an ID appears in conversation text.

## Spend Estimates

GAIUM writes `cost_usd` into the state file and the panel menu displays that monthly aggregate spend. When logs do not contain a provider-billed cost, GAIUM estimates spend from bundled per-model pricing in `gaium/pricing.py`.

Claude logs include input, output, cache-write, and cache-read token counters, so Claude spend estimates include prompt caching. Repeated streaming records with the same assistant message ID are counted once using the latest cumulative usage. Claude model IDs with release-date suffixes use the corresponding known model price; unknown model versions are left unpriced instead of inheriting a rate from a broad model-name prefix. Codex Desktop currently exposes thread-level `tokens_used` totals locally, not a full input/output/cache breakdown, so Codex spend is marked with `cost_estimated: true` and `cost_notes: ["total tokens only"]`.`

Normalize estimates to your observed monthly provider spend with:

```bash
gaium calibrate --window month claude=7 codex=8
gaium collect --window month
```

Calibration writes multipliers to `~/.config/gaium/calibration.json`. The state file keeps both `raw_cost_usd` and normalized `cost_usd`, and marks calibrated rows with `cost_notes: ["calibrated"]`.

Pricing changes over time. Update `gaium/pricing.py` when provider rates change or when you want to use account-specific contract rates.

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

GAIUM is managed with `uv`. Create or refresh the local virtual environment and lockfile:

```bash
uv sync
```

Run tests:

```bash
uv run python -m unittest discover
```

Refresh state while developing:

```bash
uv run gaium collect --window 24h --watch --interval 30
```

Refresh the current calendar month while developing:

```bash
uv run gaium collect --window month --watch --interval 30
```

The helper scripts wrap those commands:

```bash
scripts/dev-test.sh
scripts/dev-collect.sh
```

GAIUM currently has no third-party Python runtime dependencies. If you do not have `uv`, install it with your distribution's package manager when available, or use the standalone installer from Astral. As a fallback for traditional Python packaging, `python -m pip install --user -e .` also works once `python3-pip` is installed.
