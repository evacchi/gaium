#!/bin/bash
# <xbar.title>GAIUM Usage</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.author>GAIUM</xbar.author>
# <xbar.desc>Local AI agent usage and estimated spend.</xbar.desc>
# <xbar.dependencies>python3</xbar.dependencies>

set -u

GAIUM_REPO_ROOT="__GAIUM_REPO_ROOT__"
STATE_FILE="${HOME}/.local/state/ai-agent-usage.json"

export PATH="/opt/homebrew/opt/python@3.14/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
PYTHON_BIN="${GAIUM_PYTHON:-/opt/homebrew/opt/python@3.14/bin/python3.14}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -n "${PYTHON_BIN}" && -d "${GAIUM_REPO_ROOT}/gaium" ]]; then
    PYTHONPATH="${GAIUM_REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
        "${PYTHON_BIN}" -m gaium.cli collect --window month >/dev/null 2>&1 || true
fi

if [[ ! -f "${STATE_FILE}" ]]; then
    printf '⚠ GAIUM unavailable\n'
    printf '%s\n' '---' 'No saved usage state. Install GAIUM and refresh this plugin.'
    exit 0
fi

if [[ -z "${PYTHON_BIN}" ]]; then
    printf '⚠ GAIUM unavailable\n'
    printf '%s\n' '---' 'Python 3 was not found.'
    exit 0
fi

"${PYTHON_BIN}" - "${STATE_FILE}" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def compact_count(value: object) -> str:
    try:
        number = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        number = 0
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return f"{number:,}"


def amount(value: object, estimated: bool) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        number = 0.0
    return f"{'~' if estimated else ''}${number:,.2f}"


state_path = Path(sys.argv[1])
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    print("⚠ GAIUM state error")
    print("---")
    print("The saved usage file could not be read.")
    raise SystemExit(0)

totals = state.get("totals") if isinstance(state, dict) else {}
totals = totals if isinstance(totals, dict) else {}
agents = state.get("agents", []) if isinstance(state, dict) else []
agents = agents if isinstance(agents, list) else []
window = state.get("window", {}) if isinstance(state, dict) else {}
window = window if isinstance(window, dict) else {}
estimated = bool(totals.get("cost_estimated"))
menu_title = amount(totals.get("cost_usd"), estimated)
print(f"🤖 {menu_title}")
print("---")
print(f"GAIUM usage · {window.get('label') or 'all'}")
print(f"Total · {compact_count(totals.get('total_tokens'))} tokens · {int(totals.get('requests') or 0):,} requests · {menu_title}")

for agent in agents:
    if not isinstance(agent, dict):
        continue
    name = str(agent.get("name") or "unknown").capitalize()
    cost = amount(agent.get("cost_usd"), bool(agent.get("cost_estimated")))
    tokens = compact_count(agent.get("total_tokens"))
    requests = int(agent.get("requests") or 0)
    print(f"---")
    print(f"{name} · {tokens} tokens · {requests:,} requests · {cost}")
    print(f"--Input · {int(agent.get('input_tokens') or 0):,} tokens")
    print(f"--Output · {int(agent.get('output_tokens') or 0):,} tokens")
    model = agent.get("active_model")
    if model:
        print(f"--Model · {model}")

generated_at = state.get("generated_at")
if generated_at:
    try:
        updated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        print("---")
        print(f"Updated · {updated.astimezone().strftime('%Y-%m-%d %H:%M')}")
    except (TypeError, ValueError):
        pass
print("---")
print("Refresh now | refresh=true")
PY
