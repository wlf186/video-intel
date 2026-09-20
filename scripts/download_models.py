#!/usr/bin/env python3
"""Download the pinned H3 components, resuming partial files and verifying SHA-256."""

import concurrent.futures
import hashlib
import http.client
import json
import pathlib
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = "Comfy-Org/MiniMax-H3"
REVISION = "a98869194787969724c7425d95d0ed73ce9202af"
FILES = [
    "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "vae/minimax_h3_video_vae_fp16.safetensors",
    "vae/minimax_h3_audio_vae_fp32.safetensors",
    "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
]


def download(info):
    name, size, expected = info["rfilename"], info["size"], info["lfs"]["sha256"]
    target = ROOT / "models" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt = target.with_suffix(".verified.json")
    if (
        target.exists()
        and target.stat().st_size == size
        and receipt.exists()
        and json.loads(receipt.read_text()).get("sha256") == expected
    ):
        print(f"Verified existing: {name}", flush=True)
        return
    partial = target.with_suffix(".partial")
    if target.exists() and not partial.exists():
        target.rename(partial)
    for attempt in range(30):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset >= size:
            break
        request = urllib.request.Request(
            f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}?download=true",
            headers={
                "Range": f"bytes={offset}-",
                "User-Agent": "video-intel-local-demo",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if offset and response.status != 206:
                    raise RuntimeError("Server did not honor the resume range")
                last_report = time.monotonic()
                with partial.open("ab" if offset else "wb") as output:
                    while chunk := response.read(4 * 1024 * 1024):
                        output.write(chunk)
                        offset += len(chunk)
                        if time.monotonic() - last_report > 15:
                            print(
                                f"{name}: {offset / 1e9:.2f}/{size / 1e9:.2f} GB",
                                flush=True,
                            )
                            last_report = time.monotonic()
            if partial.stat().st_size == size:
                break
        except (OSError, http.client.HTTPException, RuntimeError) as error:
            print(f"Retry {attempt + 1} {name}: {type(error).__name__}", flush=True)
            time.sleep(min(2 + attempt, 15))
    if not partial.exists() or partial.stat().st_size != size:
        raise RuntimeError(f"Incomplete download: {name}")
    print(f"Checking SHA-256: {name}", flush=True)
    digest = hashlib.sha256()
    with partial.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError(f"Checksum mismatch: {name}; remove {partial} and retry")
    partial.rename(target)
    receipt.write_text(
        json.dumps({"sha256": expected, "bytes": size, "revision": REVISION})
    )
    print(f"Ready: {name}", flush=True)


if __name__ == "__main__":
    with urllib.request.urlopen(
        f"https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true",
        timeout=30,
    ) as response:
        metadata = json.load(response)
    entries = {item["rfilename"]: item for item in metadata["siblings"]}
    inventory = [entries[name] for name in FILES]
    (ROOT / "models").mkdir(exist_ok=True)
    (ROOT / "models" / "manifest.json").write_text(
        json.dumps(
            {"repository": REPO, "revision": REVISION, "files": inventory}, indent=2
        )
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(download, inventory))
