"""Real duration acceptance; writes state only when a case starts or ends."""

import json
import subprocess
import time
from pathlib import Path

import httpx
from verify_generation import PROMPTS, SOUNDS

ROOT = Path(__file__).resolve().parents[1]
manifest = ROOT / "data/validation/production-results.json"
results = json.loads(manifest.read_text()) if manifest.exists() else {}
with httpx.Client(
    base_url="http://127.0.0.1:20820", timeout=30, trust_env=False
) as client:
    for mode, preset, seconds in [
        ("i2v", "preview", 4),
        ("r2v", "preview", 10),
        ("t2v", "native", 15),
    ]:
        name = f"{preset}_{mode}_{seconds}s"
        item = results.get(name)
        if item and item["status"] == "succeeded":
            continue
        if not item or item["status"] in ("failed", "cancelled"):
            files = (
                {
                    "images": (
                        "reference.png",
                        (ROOT / "data/validation/reference.png").read_bytes(),
                        "image/png",
                    )
                }
                if mode != "t2v"
                else None
            )
            response = client.post(
                "/api/jobs",
                data={
                    "prompt": PROMPTS[mode],
                    "soundscape": SOUNDS[mode],
                    "mode": mode,
                    "preset": preset,
                    "duration_seconds": seconds,
                    "seed": 42,
                },
                files=files,
            )
            response.raise_for_status()
            item = response.json()
            results[name] = item
            manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(name, item["id"], flush=True)
        while item["status"] not in ("failed", "cancelled", "succeeded"):
            time.sleep(60 if preset == "preview" else 300)
            try:
                response = client.get("/api/jobs/" + item["id"])
                response.raise_for_status()
                item = response.json()
            except httpx.HTTPError as error:
                print(f"Waiting for API recovery: {error}", flush=True)
                continue
        if item["status"] == "succeeded":
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", item["video_path"], "-f", "null", "-"],
                check=True,
            )
            item["full_decode_passed"] = True
        results[name] = item
        manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(name, item["status"], item["metrics"], flush=True)
        if item["status"] != "succeeded":
            raise RuntimeError(item.get("error"))
