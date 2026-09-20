import asyncio
import json
import os
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import psutil
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import config
from .prompts import TEMPLATE_VERSION, compile_prompt
from .service import (
    INPUT,
    MAX_UPLOAD,
    OUTPUT,
    ROOT,
    InsufficientStorage,
    JobService,
    safe_path,
)
from .storage import Storage
from .workflows import DEFAULT_PRESET, PRESETS, duration_frames

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
config.settings()  # Validate deployment settings before initializing storage.
service = JobService()
storage = Storage(service)


@asynccontextmanager
async def lifespan(app):
    storage.recover()
    service.start()
    yield
    await run_in_threadpool(service.close)


app = FastAPI(
    title="Sandevistan Video",
    version=config.VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
app.mount("/docs-assets", StaticFiles(directory=ROOT / "static"), name="docs-assets")


@app.middleware("http")
async def uploads_guard(request: Request, call_next):
    uploading = request.method == "POST" and request.url.path == "/api/jobs"
    if uploading:
        # Bound the whole multipart request, including chunked uploads.
        limit = 3 * MAX_UPLOAD + 1024 * 1024
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if declared > limit:
            return JSONResponse({"detail": "Upload exceeds 46 MiB"}, status_code=413)
        receive = request._receive
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise HTTPException(413, "Upload exceeds 46 MiB")
            return message

        request._receive = bounded_receive
        with service.actions:
            service.uploads += 1
    try:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    finally:
        if uploading:
            with service.actions:
                service.uploads -= 1


@app.get("/docs", include_in_schema=False)
def api_docs():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Sandevistan Video API",
        swagger_js_url="/docs-assets/swagger/swagger-ui-bundle.js",
        swagger_css_url="/docs-assets/swagger/swagger-ui.css",
        swagger_favicon_url="/logo.png",
        swagger_ui_parameters={"validatorUrl": None},
    )


def get_job(job_id):
    try:
        return service.get(job_id)
    except KeyError:
        raise HTTPException(404, "任务不存在 / Task not found") from None


@app.get("/api/health")
def health():
    return service.health()


@app.get("/api/capabilities")
def capabilities():
    return {
        "presets": PRESETS,
        "default_preset": DEFAULT_PRESET,
        "default_duration": 5,
        "durations": [
            {
                "requested_duration_seconds": s,
                "frames": duration_frames(s),
                "duration_seconds": duration_frames(s) / 24,
            }
            for s in range(4, 16)
        ],
        "max_upload_bytes": MAX_UPLOAD,
        "max_prompt_chars": 16000,
        "max_soundscape_chars": 4000,
        "max_music_chars": 4000,
        "max_raw_prompt_chars": 40000,
        "max_reference_description_chars": 1000,
        "prompt_formats": ["auto", "guided", "raw"],
        "prompt_template_version": TEMPLATE_VERSION,
    }


class PromptPreviewRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=40000)
    mode: Literal["t2v", "i2v", "r2v"] = "t2v"
    soundscape: str = Field(default="", max_length=4000)
    music: str = Field(default="", max_length=4000)
    prompt_format: Literal["auto", "guided", "raw"] = "auto"
    reference_descriptions: list[str] = Field(default_factory=list, max_length=3)
    image_count: int = Field(default=0, ge=0, le=3)
    source_job_id: str | None = None


@app.post("/api/prompts/preview")
def preview_prompt(body: PromptPreviewRequest):
    count = body.image_count
    try:
        if body.source_job_id and not count and body.mode != "t2v":
            count = len(service.get(body.source_job_id)["images"])
        return compile_prompt(
            body.prompt,
            body.soundscape,
            body.mode,
            count,
            prompt_format=body.prompt_format,
            music=body.music,
            reference_descriptions=body.reference_descriptions,
        )
    except KeyError as error:
        raise HTTPException(404, "复用任务不存在 / Source task not found") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/jobs", status_code=202)
async def create_job(
    prompt: Annotated[str, Form()],
    mode: Annotated[Literal["t2v", "i2v", "r2v"], Form()] = "t2v",
    preset: Annotated[
        Literal["preview", "standard", "native"], Form()
    ] = DEFAULT_PRESET,
    seed: Annotated[int, Form()] = -1,
    soundscape: Annotated[str, Form()] = "",
    duration_seconds: Annotated[int, Form(ge=4, le=15)] = 5,
    source_job_id: Annotated[str | None, Form()] = None,
    images: Annotated[list[UploadFile] | None, File()] = None,
    prompt_format: Annotated[Literal["auto", "guided", "raw"], Form()] = "auto",
    music: Annotated[str, Form()] = "",
    reference_descriptions: Annotated[str, Form()] = "[]",
    text_encoding: Annotated[Literal["plain", "json"], Form()] = "plain",
):
    uploads = images or []
    if len(uploads) > 3:
        raise HTTPException(422, "最多上传 3 张图片 / Maximum 3 images")
    content = []
    try:
        # Browser FormData normalizes plain multiline values to CRLF. JSON
        # strings preserve the exact text shown in the JSON preview response.
        if text_encoding == "json":
            try:
                prompt, soundscape, music = (
                    json.loads(value) if value else ""
                    for value in (prompt, soundscape, music)
                )
            except (ValueError, TypeError) as error:
                raise ValueError("文本编码无效 / Invalid text encoding") from error
            if not all(isinstance(value, str) for value in (prompt, soundscape, music)):
                raise ValueError("文本字段必须为字符串 / Text fields must be strings")
        try:
            descriptions = json.loads(reference_descriptions)
        except (ValueError, TypeError) as error:
            raise ValueError(
                "主体说明必须为 JSON 数组 / Subject descriptions must be a JSON array"
            ) from error
        for upload in uploads:
            content.append(await upload.read(MAX_UPLOAD + 1))
        return await run_in_threadpool(
            service.submit,
            prompt,
            mode,
            preset,
            seed,
            soundscape,
            content,
            duration_seconds,
            source_job_id,
            prompt_format=prompt_format,
            music=music,
            reference_descriptions=descriptions,
        )
    except InsufficientStorage as error:
        return JSONResponse(
            {"detail": str(error), "code": "insufficient_storage"}, status_code=422
        )
    except (ValueError, KeyError, OSError) as error:
        raise HTTPException(422, str(error)) from error
    finally:
        for upload in uploads:
            await upload.close()


@app.get("/api/jobs")
def list_jobs(
    response: Response,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    mode: str | None = None,
    search: str = Query("", max_length=16000),
    sort: Literal["newest", "oldest", "size_desc"] = "newest",
    include_storage: bool = False,
):
    response.headers["X-Total-Count"] = str(service.count(status, mode, search))
    return service.list(limit, offset, status, mode, search, sort, include_storage)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return get_job(job_id)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    get_job(job_id)
    return service.cancel(job_id)


class LeasedFileResponse(FileResponse):
    def __init__(self, path, job_id, **kwargs):
        self.job_id = job_id
        super().__init__(path, **kwargs)

    async def __call__(self, scope, receive, send):
        with service.actions:
            if not Path(self.path).is_file():
                await Response(status_code=404)(scope, receive, send)
                return
            service.readers[self.job_id] += 1
        try:
            await super().__call__(scope, receive, send)
        finally:
            with service.actions:
                service.readers[self.job_id] -= 1


@app.get("/api/jobs/{job_id}/video")
def video(job_id: str, download: bool = False):
    item = get_job(job_id)
    if item["status"] != "succeeded":
        raise HTTPException(409, "视频尚未生成完成 / Video not ready")
    try:
        path = safe_path(OUTPUT / job_id, Path(item["video_path"]).name)
    except (ValueError, TypeError):
        raise HTTPException(404, "Output unavailable") from None
    if not path.is_file():
        raise HTTPException(404, "Output missing")
    return LeasedFileResponse(
        path,
        job_id,
        media_type="video/mp4",
        filename=f"sandevistan-{job_id[:8]}.mp4",
        content_disposition_type="attachment" if download else "inline",
    )


@app.get("/api/jobs/{job_id}/poster")
def poster(job_id: str):
    get_job(job_id)
    path = safe_path(OUTPUT / job_id, "poster.webp")
    if not path.is_file():
        raise HTTPException(404, "No poster")
    return LeasedFileResponse(
        path,
        job_id,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get("/api/jobs/{job_id}/images/{index}")
def input_image(job_id: str, index: int):
    item = get_job(job_id)
    if index < 0 or index >= len(item["images"]):
        raise HTTPException(404, "Image not found")
    try:
        path = safe_path(INPUT, item["images"][index])
    except ValueError:
        raise HTTPException(404, "Image not found") from None
    return LeasedFileResponse(path, job_id, media_type="image/png")


@app.get("/api/events")
async def events(request: Request):
    try:
        last = int(request.headers.get("last-event-id", service.revision))
    except ValueError:
        last = service.revision

    async def stream():
        nonlocal last
        yield "event: connected\ndata: {}\n\n"
        heartbeat = time.monotonic()
        while not await request.is_disconnected():
            for event in service.events_after(last):
                last = event["id"]
                yield f"id: {last}\nevent: {event['kind']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            if time.monotonic() - heartbeat > 15:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class CleanupRequest(BaseModel):
    job_ids: list[str] = Field(default_factory=list, max_length=100)
    kinds: list[Literal["residual", "temporary", "cache", "logs", "database"]] = Field(
        default_factory=list, max_length=5
    )


@app.get("/api/storage")
def storage_info(refresh: bool = False, include_jobs: bool = True):
    return storage.snapshot(refresh, include_jobs)


@app.post("/api/storage/cleanup/preview")
def cleanup_preview(body: CleanupRequest):
    try:
        return storage.preview(body.job_ids, body.kinds)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/storage/cleanup")
def cleanup(body: CleanupRequest):
    try:
        return storage.cleanup(body.job_ids, body.kinds)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


system_cached = None
system_at = 0


@app.get("/api/system")
def system_info():
    global system_cached, system_at
    if system_cached and time.monotonic() - system_at < 10:
        return system_cached
    gpu = None
    try:
        values = (
            subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=3,
            )
            .splitlines()[0]
            .split(",")
        )
        gpu = {
            "name": values[0].strip(),
            "used_mib": int(values[1]),
            "total_mib": int(values[2]),
            "utilization": int(values[3]),
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(DATA_PATH := config.DATA)
    system_cached = dict(
        **service.health(),
        gpu=gpu,
        memory={"total": memory.total, "available": memory.available},
        disk={"total": disk.total, "free": disk.free},
        bind=f"{config.HOST}:{config.PORT}",
        queue=service.count(status="queued"),
        running=service.count(status="running"),
        paths={
            "data": str(DATA_PATH.relative_to(ROOT)),
            "temporary": "tmp/",
            "cache": "cache/",
            "logs": "logs/",
        },
        recent_errors=[
            {"id": x["id"], "error": x["error"], "finished_at": x["finished_at"]}
            for x in service.list(limit=5, status="failed")
        ],
        updated_at=time.time(),
    )
    system_at = time.monotonic()
    return system_cached


@app.get("/api/logs")
def diagnostic_logs():
    parts = []
    for name in ("supervisor.log", "web.log", "comfy.log"):
        path = config.LOGS / name
        if path.exists():
            with path.open("rb") as source:
                source.seek(max(0, path.stat().st_size - 16000))
                parts.append(
                    {
                        "name": name,
                        "text": source.read().decode(errors="replace")[-12000:],
                    }
                )
    return parts


frontend = ROOT / "frontend/dist"
if frontend.exists():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="ui")
