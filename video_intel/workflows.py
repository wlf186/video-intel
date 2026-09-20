from pathlib import Path

from .prompts import compile_prompt

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "t2v": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "i2v": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "r2v": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
}
ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
PRESETS = {"preview": (608, 352), "standard": (864, 480), "native": (1344, 768)}
DEFAULT_PRESET = "native"


def model_files(mode):
    return [
        ROOT / "models/diffusion_models" / MODELS[mode],
        ROOT / "models/text_encoders" / ENCODER,
        ROOT / "models/vae" / VIDEO_VAE,
        ROOT / "models/vae" / AUDIO_VAE,
    ]


def models_ready(mode):
    return all(
        path.is_file() and path.with_suffix(".verified.json").is_file()
        for path in model_files(mode)
    )


def build_workflow(job):
    """Native H3 API graph. Both decoders consume the joint AV latent."""
    width, height = PRESETS[job["preset"]]

    def node(kind, **inputs):
        return {"class_type": kind, "inputs": inputs}

    conditioning = {
        "clip": ["2", 0],
        "vae": ["3", 0],
        "prompt": job["effective_prompt"],
        "width": width,
        "height": height,
        "length": job.get("frames", 124),
    }
    graph = {
        "1": node("UNETLoader", unet_name=MODELS[job["mode"]], weight_dtype="default"),
        "2": node("CLIPLoader", clip_name=ENCODER, type="minimax", device="default"),
        "3": node("VAELoader", vae_name=VIDEO_VAE),
        "4": node("VAELoader", vae_name=AUDIO_VAE),
        "6": node("RandomNoise", noise_seed=job["seed"]),
        "7": node("BasicGuider", model=["1", 0], conditioning=["5", 0]),
        "8": node("KSamplerSelect", sampler_name="res_multistep"),
        "9": node(
            "BasicScheduler", model=["1", 0], scheduler="simple", steps=20, denoise=1.0
        ),
        "10": node(
            "SamplerCustomAdvanced",
            noise=["6", 0],
            guider=["7", 0],
            sampler=["8", 0],
            sigmas=["9", 0],
            latent_image=["5", 1],
        ),
        "11": node("VAEDecode", samples=["10", 0], vae=["3", 0]),
        "12": node("VAEDecodeAudio", samples=["10", 0], vae=["4", 0]),
        "13": node("CreateVideo", images=["11", 0], audio=["12", 0], fps=24.0),
        "14": node(
            "SaveVideo",
            video=["13", 0],
            filename_prefix=f"{job['id']}/video",
            format="mp4",
        ),
    }
    graph["14"]["inputs"].update(
        {
            "format.codec": "h264",
            "format.codec.encoding": "re-encode",
            "format.codec.encoding.crf": 18.0,
        }
    )
    for index, filename in enumerate(job["images"]):
        key = str(20 + index)
        graph[key] = node("LoadImage", image=filename)
        if job["mode"] == "i2v":
            conditioning["first_frame"] = [key, 0]
        else:
            conditioning[f"ref_images.ref_image_{index}"] = [key, 0]
    if job["mode"] == "r2v":
        conditioning["ref_image_size"] = "match"
        graph["5"] = node("MiniMaxH3ReferenceToVideo", **conditioning)
    else:
        graph["5"] = node("MiniMaxH3ImageToVideo", **conditioning)
    return graph


def format_prompt(prompt, soundscape, mode, count):
    return compile_prompt(prompt, soundscape, mode, count)["effective_prompt"]


def duration_frames(seconds):
    if type(seconds) is not int or not 4 <= seconds <= 15:
        raise ValueError(
            "视频时长必须是 4–15 之间的整数 / Duration must be an integer from 4 to 15"
        )
    return 5 + 17 * ((24 * seconds - 5 + 16) // 17)
