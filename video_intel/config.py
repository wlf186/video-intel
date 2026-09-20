"""Project-local runtime paths and deployment settings."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TMP = ROOT / "tmp"
CACHE = ROOT / "cache"
LOGS = ROOT / "logs"
RUN = ROOT / "run"
HOST = os.environ.get("VIDEO_INTEL_HOST", "0.0.0.0")
PORT = int(os.environ.get("VIDEO_INTEL_PORT", "20820"))
BACKEND_PORT = int(os.environ.get("VIDEO_INTEL_BACKEND_PORT", "8188"))
MIN_FREE_BYTES = int(os.environ.get("VIDEO_INTEL_MIN_FREE_BYTES", str(5 * 1024**3)))
CHECKPOINT_SECONDS = 60
VERSION = "1.0.0"


def runtime_environment():
    env = dict(os.environ)
    paths = {
        "TMPDIR": TMP / "runtime",
        "TMP": TMP / "runtime",
        "TEMP": TMP / "runtime",
        "XDG_CACHE_HOME": CACHE / "xdg",
        "HF_HOME": CACHE / "huggingface",
        "TORCH_HOME": CACHE / "torch",
        "TORCHINDUCTOR_CACHE_DIR": CACHE / "torchinductor",
        "TRITON_CACHE_DIR": CACHE / "triton",
        "CUDA_CACHE_PATH": CACHE / "cuda",
        "UV_CACHE_DIR": CACHE / "uv",
        "PIP_CACHE_DIR": CACHE / "pip",
        "GRADIO_TEMP_DIR": TMP / "gradio",
    }
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        GRADIO_ANALYTICS_ENABLED="False",
        PYTHONUNBUFFERED="1",
        PYTHONNOUSERSITE="1",
        OMP_NUM_THREADS="4",
        OPENBLAS_NUM_THREADS="4",
    )
    return env
