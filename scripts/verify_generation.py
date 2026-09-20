#!/usr/bin/env python3
"""Run real H3 jobs through the public API; resume completed validation cases."""

import argparse
import json
import pathlib
import subprocess
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "data/validation"
PROMPTS = {
    "t2v": "A cinematic close-up of a small red toy car rolling slowly across a wet stone path in a lush garden. Raindrops ripple in shallow puddles. The camera tracks gently alongside the car. Soft overcast light, realistic textures, a single continuous shot.",
    "i2v": "The small red toy car from the first frame rolls slowly forward on the wet stone path. Gentle rain falls and ripples spread across a shallow puddle. The camera follows smoothly at ground level. Preserve the toy car's appearance. A single continuous realistic shot.",
    "r2v": "<Subject 1> is the small red toy car from <Picture 1>. Place the same red toy car on a wooden workbench in a sunlit workshop. The car rolls slowly across the wood, retaining its red body, wheels, shape and toy proportions. A close-up tracking shot with a softly blurred workshop background. Realistic textures, a single continuous shot.",
}
SOUNDS = {
    "t2v": "Gentle rainfall and faint rolling wheel sounds. No music or dialogue.",
    "i2v": "Raindrops striking stone and faint rolling wheel sounds. No music or dialogue.",
    "r2v": "Soft wheel sounds on a wooden surface and quiet room ambience. No music or dialogue.",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--presets", nargs="+", default=["preview", "standard", "native"]
    )
    parser.add_argument("--modes", nargs="+", default=["t2v", "i2v", "r2v"])
    parser.add_argument(
        "--manifest", type=pathlib.Path, default=DIRECTORY / "results.json"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:20820")
    parser.add_argument("--reference-image", type=pathlib.Path, default=DIRECTORY / "reference.png")
    args = parser.parse_args()
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    manifest = args.manifest
    manifest.parent.mkdir(parents=True, exist_ok=True)
    results = json.loads(manifest.read_text()) if manifest.exists() else {}
    image_path = args.reference_image
    image_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        base_url=args.base_url, timeout=30, trust_env=False
    ) as client:
        for preset in args.presets:
            for mode in args.modes:
                case = f"{preset}_{mode}"
                prior = results.get(case)
                if prior and prior["status"] == "succeeded":
                    print(f"Already verified: {case}", flush=True)
                    continue
                if prior and prior["status"] not in {"failed", "cancelled"}:
                    job_id = prior["id"]
                else:
                    payload = {
                        "prompt": PROMPTS[mode],
                        "soundscape": SOUNDS[mode],
                        "mode": mode,
                        "preset": preset,
                        "seed": 42,
                    }
                    files = (
                        {
                            "images": (
                                "reference.png",
                                image_path.read_bytes(),
                                "image/png",
                            )
                        }
                        if mode != "t2v"
                        else None
                    )
                    response = client.post("/api/jobs", data=payload, files=files)
                    response.raise_for_status()
                    results[case] = response.json()
                    job_id = results[case]["id"]
                    manifest.write_text(
                        json.dumps(results, ensure_ascii=False, indent=2)
                    )
                print(f"Started {case}: {job_id}", flush=True)
                last_report = 0
                while True:
                    item = client.get(f"/api/jobs/{job_id}").json()
                    if time.monotonic() - last_report > 30:
                        print(
                            f"{case}: {item['status']} {item['stage']} {item['metrics']}",
                            flush=True,
                        )
                        last_report = time.monotonic()
                    if item["status"] in {"succeeded", "failed", "cancelled"}:
                        break
                    time.sleep(3)
                results[case] = item
                manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2))
                if item["status"] != "succeeded":
                    raise RuntimeError(f"{case}: {item['error'] or item['status']}")
                if not image_path.exists() and mode == "t2v":
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-v",
                            "error",
                            "-i",
                            item["video_path"],
                            "-frames:v",
                            "1",
                            str(image_path),
                        ],
                        check=True,
                    )
                print(f"PASS {case}: {item['metrics']}", flush=True)


if __name__ == "__main__":
    main()
