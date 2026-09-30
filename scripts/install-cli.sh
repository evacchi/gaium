#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin_dir="${HOME}/.local/bin"
target="${bin_dir}/gaium"

mkdir -p "${bin_dir}"
cat > "${target}" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${repo_root}:\${PYTHONPATH:-}"
exec python -m gaium.cli "\$@"
EOF
chmod +x "${target}"

echo "Installed ${target}"
echo "Make sure ${bin_dir} is on PATH, then run: gaium collect --window month"
