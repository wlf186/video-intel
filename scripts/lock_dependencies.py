"""Generate hashed Linux locks, preserving existing resolutions unless upgraded."""

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from bootstrap_tools import ROOT, VERSIONS, ensure_uv

LOCKS = {
    "requirements.lock": ["requirements.in"],
    "requirements-ci.lock": ["requirements-api.in", "requirements-dev.in"],
}


def validate_comfy_requirements():
    source = ROOT / "requirements-comfy.in"
    lines = source.read_bytes().splitlines(keepends=True)
    expected = lines[1].decode().strip().removeprefix("# Upstream SHA256: ")
    if hashlib.sha256(b"".join(lines[2:])).hexdigest() != expected:
        raise ValueError(
            "ComfyUI dependency snapshot was modified; verify upstream provenance"
        )
    if VERSIONS["comfyui_commit"] not in lines[0].decode():
        raise ValueError("ComfyUI dependency snapshot revision differs from toolchain")


def compile_lock(uv, name, sources, output, upgrade):
    command = [
        str(uv),
        "pip",
        "compile",
        "--python-version",
        VERSIONS["python"],
        "--python-platform",
        "x86_64-unknown-linux-gnu",
        "--generate-hashes",
        "--no-header",
        "--output-file",
        str(output),
    ]
    if name == "requirements.lock":
        command += ["--torch-backend", "cu130"]
    else:
        command += ["--constraint", "requirements.lock"]
    if upgrade:
        command += ["--upgrade"]
    command += sources
    subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        env={**os.environ, "UV_CACHE_DIR": str(ROOT / "cache/uv")},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--upgrade", action="store_true")
    args = parser.parse_args()
    if args.check and args.upgrade:
        parser.error("--check and --upgrade cannot be combined")
    validate_comfy_requirements()
    uv = ensure_uv()
    (ROOT / "tmp").mkdir(exist_ok=True)
    failures = []
    with tempfile.TemporaryDirectory(
        prefix="dependency-locks-", dir=ROOT / "tmp"
    ) as folder:
        for name, sources in LOCKS.items():
            destination = ROOT / name
            output = Path(folder) / name
            if destination.exists():
                shutil.copyfile(destination, output)
            elif args.check:
                failures.append(name)
                continue
            compile_lock(uv, name, sources, output, args.upgrade)
            if args.check:
                if destination.read_bytes() != output.read_bytes():
                    failures.append(name)
            else:
                shutil.copyfile(output, destination)
    if failures:
        raise SystemExit("Missing or stale dependency locks: " + ", ".join(failures))


if __name__ == "__main__":
    main()
