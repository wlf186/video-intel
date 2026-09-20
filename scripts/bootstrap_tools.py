"""Install checksum-pinned tools inside this checkout, without global installs."""

import argparse
import base64
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = json.loads((ROOT / "scripts/toolchain.json").read_text())
UV = ROOT / ".runtime/bin/uv"
PNPM = ROOT / ".runtime/pnpm/package/bin/pnpm.cjs"


def verified_download(url, algorithm, expected):
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    digest = hashlib.new(algorithm, data).digest()
    actual = (
        digest.hex() if algorithm == "sha256" else base64.b64encode(digest).decode()
    )
    if actual != expected:
        raise ValueError(f"Checksum mismatch for {url}")
    return data


def ensure_uv():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("Supported deployment: Linux x86_64")
    if UV.is_file():
        version = subprocess.check_output([str(UV), "--version"], text=True).split()[1]
        if version == VERSIONS["uv"]:
            return UV
    UV.parent.mkdir(parents=True, exist_ok=True)
    data = verified_download(
        f"https://github.com/astral-sh/uv/releases/download/{VERSIONS['uv']}/"
        "uv-x86_64-unknown-linux-gnu.tar.gz",
        "sha256",
        VERSIONS["uv_sha256"],
    )
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        member = archive.extractfile("uv-x86_64-unknown-linux-gnu/uv")
        if member is None:
            raise ValueError("uv binary missing from archive")
        with tempfile.NamedTemporaryFile(dir=UV.parent, delete=False) as target:
            shutil.copyfileobj(member, target)
    os.chmod(target.name, 0o755)
    os.replace(target.name, UV)
    return UV


def ensure_pnpm():
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js 22.12+ is required; Node 24.21.0 is recommended")
    version = subprocess.check_output([node, "--version"], text=True).strip()[1:]
    if tuple(map(int, version.split("."))) < (22, 12, 0):
        raise SystemExit("Node.js 22.12+ is required")
    manifest = PNPM.parents[1] / "package.json"
    if (
        PNPM.is_file()
        and json.loads(manifest.read_text())["version"] == VERSIONS["pnpm"]
    ):
        return PNPM
    data = verified_download(
        f"https://registry.npmjs.org/pnpm/-/pnpm-{VERSIONS['pnpm']}.tgz",
        "sha512",
        VERSIONS["pnpm_sha512"],
    )
    destination = ROOT / ".runtime/pnpm"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive.getmembers():
                target = (Path(temporary) / member.name).resolve()
                if not target.is_relative_to(Path(temporary).resolve()):
                    raise ValueError("Archive member escapes tool directory")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError("Missing archive member")
                    with target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(member.mode & 0o755)
                else:
                    raise ValueError(
                        "Tool archive must contain only regular files/directories"
                    )
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(temporary, destination)
    return PNPM


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=["uv", "pnpm", "all"])
    args = parser.parse_args()
    if args.tool in {"uv", "all"}:
        print(ensure_uv())
    if args.tool in {"pnpm", "all"}:
        print(ensure_pnpm())


if __name__ == "__main__":
    main()
