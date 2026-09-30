#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${HOME}/.local/share/gnome-shell/extensions/gaium@local"
bundle_dir="$(mktemp -d)"
bundle="${bundle_dir}/gaium@local.shell-extension.zip"

cleanup() {
  rm -rf "${bundle_dir}"
}
trap cleanup EXIT

mkdir -p "$(dirname "${target}")"

rm -rf "${target}"
cp -R "${repo_root}/extension/gaium@local" "${target}"

if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions pack -f -o "${bundle_dir}" "${repo_root}/extension/gaium@local" >/dev/null
  gnome-extensions install --force "${bundle}" >/dev/null || true
fi

echo "Installed GNOME Shell extension files to ${target}"

if command -v gnome-extensions >/dev/null 2>&1 && gnome-extensions list --user | grep -qx 'gaium@local'; then
  echo "GNOME currently lists gaium@local. Enable it with: gnome-extensions enable gaium@local"
else
  echo "GNOME does not list gaium@local in the current Shell session yet."
  echo "Log out and back in, then run: gnome-extensions enable gaium@local"
fi
