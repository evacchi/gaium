#!/usr/bin/env bash
set -euo pipefail

uv run gaium collect --window "${1:-24h}" --watch --interval "${2:-30}"
