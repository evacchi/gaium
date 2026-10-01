#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plugin_dir="${HOME}/Library/Application Support/xbar/plugins"
plugin_path="${plugin_dir}/gaium.5m.sh"

mkdir -p "${plugin_dir}"
escaped_repo_root="$(printf '%s' "${repo_root}" | /usr/bin/sed 's/[\\&|]/\\&/g')"
/usr/bin/sed "s|__GAIUM_REPO_ROOT__|${escaped_repo_root}|g" \
    "${repo_root}/xbar/gaium.5m.sh" > "${plugin_path}"
/bin/chmod +x "${plugin_path}"

plugin_url_path="${plugin_path// /%20}"
/usr/bin/open "xbar://app.xbarapp.com/refreshPlugin?path=${plugin_url_path}" >/dev/null 2>&1 || true

printf 'Installed %s\n' "${plugin_path}"
printf 'xbar refreshes it every 5 minutes.\n'
