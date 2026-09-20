"""Project-local runtime paths and deployment settings."""

import os
from pathlib import Path

from .settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TMP = ROOT / "tmp"
CACHE = ROOT / "cache"
LOGS = ROOT / "logs"
RUN = ROOT / "run"
CHECKPOINT_SECONDS = 60
VERSION = "1.0.1"
_settings = None


def settings():
    global _settings
    if _settings is None:
        _settings = load_settings(ROOT)
    return _settings


def configure(value):
    global _settings
    _settings = value


def __getattr__(name):
    # Management commands must work even when the next-start config is invalid.
    if name in {"HOST", "PORT", "BACKEND_PORT", "MIN_FREE_BYTES"}:
        return getattr(settings(), name.lower())
    raise AttributeError(name)


def runtime_environment():
    env = dict(os.environ)
    env.update(settings().environment())
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
