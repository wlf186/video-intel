"""Strictly synchronize a complete hashed lock, never resolve missing locks."""

import argparse
import os
import subprocess
from pathlib import Path

from bootstrap_tools import ROOT, ensure_uv


def sync_environment(python, lock, *, full=True):
    if not lock.is_file():
        raise FileNotFoundError(f"Missing {lock}; refusing unlocked installation")
    command = [
        str(ensure_uv()),
        "pip",
        "sync",
        "--python",
        str(python),
        "--require-hashes",
        "--strict",
        str(lock),
    ]
    if full:
        command += ["--torch-backend", "cu130"]
    subprocess.run(
        command,
        check=True,
        cwd=ROOT,
        env={**os.environ, "UV_CACHE_DIR": str(ROOT / "cache/uv")},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=ROOT / ".venv/bin/python")
    parser.add_argument("--ci", action="store_true")
    args = parser.parse_args()
    if args.ci and args.python.absolute() == ROOT / ".venv/bin/python":
        parser.error("Use a separate --python environment for the CI lock")
    if (
        args.python.absolute() == ROOT / ".venv/bin/python"
        and (ROOT / "run/supervisor.identity.json").exists()
    ):
        subprocess.run(
            [
                str(args.python),
                "-c",
                (
                    "from video_intel.control import running; "
                    "assert running() is None, 'Stop the service before syncing'"
                ),
            ],
            cwd=ROOT,
            check=True,
        )
    sync_environment(
        args.python,
        ROOT / ("requirements-ci.lock" if args.ci else "requirements.lock"),
        full=not args.ci,
    )


if __name__ == "__main__":
    main()
