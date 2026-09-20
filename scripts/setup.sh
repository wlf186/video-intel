#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
skip_models=0
if [[ "${1:-}" == "--skip-models" && $# == 1 ]]; then
  skip_models=1
elif (( $# )); then
  echo 'Usage: ./scripts/setup.sh [--skip-models]' >&2
  exit 2
fi
command -v python3 >/dev/null
command -v ffmpeg >/dev/null
command -v node >/dev/null
[[ -f requirements.lock ]] || { echo 'Missing requirements.lock; refusing unlocked installation' >&2; exit 1; }
[[ -f frontend/pnpm-lock.yaml ]] || { echo 'Missing pnpm-lock.yaml; refusing unlocked installation' >&2; exit 1; }
if [[ -x .venv/bin/python && -f run/supervisor.identity.json ]]; then
  .venv/bin/python -c 'from video_intel.control import running; assert running() is None, "Stop the service before installing dependencies"'
fi
mkdir -p tmp/runtime cache/uv cache/npm .runtime
export TMPDIR="$PWD/tmp/runtime" UV_CACHE_DIR="$PWD/cache/uv" UV_PYTHON_INSTALL_DIR="$PWD/.runtime/python"
python3 scripts/bootstrap_tools.py all
uv_bin="$PWD/.runtime/bin/uv"
python_version="$(python3 -c 'import json; print(json.load(open("scripts/toolchain.json"))["python"])')"
mkdir -p vendor logs
if [ ! -d vendor/ComfyUI/.git ]; then
  git clone --branch v0.35.0 --depth 1 https://github.com/Comfy-Org/ComfyUI.git vendor/ComfyUI
fi
comfy_commit="$(python3 -c 'import json; print(json.load(open("scripts/toolchain.json"))["comfyui_commit"])')"
if [ "$(git -C vendor/ComfyUI rev-parse HEAD)" != "$comfy_commit" ]; then
  echo 'Unexpected ComfyUI revision. Expected v0.35.0 / 40c4fcdf513a4523e39d54a9d391908af8df8171.' >&2
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  "$uv_bin" venv --python "$python_version" .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 is required"'
python3 scripts/sync_environment.py
if (( ! skip_models )); then
  .venv/bin/python scripts/download_models.py
fi
./scripts/pnpm.sh install --frozen-lockfile
./scripts/pnpm.sh build
echo 'Setup complete. Run ./service.sh start.'
