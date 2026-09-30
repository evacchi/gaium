#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${HOME}/.local/share/gnome-shell/extensions/faium@local"
bundle_dir="$(mktemp -d)"
bundle="${bundle_dir}/faium@local.shell-extension.zip"

cleanup() {
  rm -rf "${bundle_dir}"
}
trap cleanup EXIT

mkdir -p "$(dirname "${target}")"

if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions pack -f -o "${bundle_dir}" "${repo_root}/extension/faium@local"
  gnome-extensions install --force "${bundle}"
else
  rm -rf "${target}"
  cp -R "${repo_root}/extension/faium@local" "${target}"
fi

echo "Installed GNOME Shell extension to ${target}"
echo "Enable it with: gnome-extensions enable faium@local"
echo "If GNOME still says it does not exist, log out and back in, then run the enable command again."
