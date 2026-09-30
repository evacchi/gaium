#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unit_dir="${HOME}/.config/systemd/user"

"${repo_root}/scripts/install-cli.sh"

mkdir -p "${unit_dir}"
cp "${repo_root}/systemd/faium-usage.service" "${unit_dir}/"
cp "${repo_root}/systemd/faium-usage.timer" "${unit_dir}/"

systemctl --user daemon-reload
systemctl --user enable --now faium-usage.timer

echo "Enabled faium-usage.timer"
