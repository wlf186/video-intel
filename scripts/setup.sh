#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null
command -v ffmpeg >/dev/null
command -v npm >/dev/null
mkdir -p tmp/runtime cache/uv cache/npm
export TMPDIR="$PWD/tmp/runtime" UV_CACHE_DIR="$PWD/cache/uv"
mkdir -p vendor logs
if [ ! -d vendor/ComfyUI/.git ]; then
  git clone --branch v0.35.0 --depth 1 https://github.com/Comfy-Org/ComfyUI.git vendor/ComfyUI
fi
if [ "$(git -C vendor/ComfyUI rev-parse HEAD)" != "40c4fcdf513a4523e39d54a9d391908af8df8171" ]; then
  echo 'Unexpected ComfyUI revision. Expected v0.35.0 / 40c4fcdf513a4523e39d54a9d391908af8df8171.' >&2
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12 .venv
fi
uv pip install --python .venv/bin/python torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cu130
if [ -f requirements.lock ]; then
  uv pip install --python .venv/bin/python -r requirements.lock --extra-index-url https://download.pytorch.org/whl/cu130 --index-strategy unsafe-best-match
else
  uv pip install --python .venv/bin/python -r vendor/ComfyUI/requirements.txt fastapi uvicorn websocket-client pytest playwright ruff
fi
.venv/bin/python scripts/download_models.py
npm --prefix frontend ci --cache "$PWD/cache/npm"
npm --prefix frontend run build
echo 'Setup complete. Run ./service.sh start.'
