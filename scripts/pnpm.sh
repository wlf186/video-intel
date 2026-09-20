#!/usr/bin/env bash
set -euo pipefail
root_dir="$(cd "$(dirname "$0")/.." && pwd)"
export npm_config_cache="$root_dir/cache/npm"
export XDG_DATA_HOME="$root_dir/cache/xdg-data"
python3 "$root_dir/scripts/bootstrap_tools.py" pnpm >/dev/null
exec node "$root_dir/.runtime/pnpm/package/bin/pnpm.cjs" --dir "$root_dir/frontend" "$@"
