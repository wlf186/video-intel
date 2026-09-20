"""Durable single-GPU queue, live progress, and recoverable backend execution."""

import copy
import io
import json
import logging
import queue
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from collections import Counter, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import httpx
import psutil
import websocket
from PIL import Image, ImageOps, UnidentifiedImageError

from . import config
from .prompts import compile_prompt
from .workflows import (
    DEFAULT_PRESET,
    MODELS,
    PRESETS,
    ROOT,
    build_workflow,
    duration_frames,
    models_ready,
)

LOG = logging.getLogger(__name__)
DATA = config.DATA
INPUT = DATA / "inputs"
OUTPUT = DATA / "outputs"
TERMINAL = {"succeeded", "failed", "cancelled"}
MAX_UPLOAD = 15 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 24_000_000
STAGES = {
    "queued": "排队中",
    "waiting": "等待推理引擎",
    "loading": "加载模型",
    "encoding": "编码文字与图片",
    "sampling": "采样",
    "video_decode": "视频解码",
    "audio_decode": "音频解码",
    "saving": "保存视频",
    "recovering": "恢复任务",
    "succeeded": "已完成",
    "failed": "生成失败",
    "cancelled": "已取消",
    "cancelling": "正在取消",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def valid_id(value):
    if not isinstance(value, str) or len(value) != 32 or uuid.UUID(value).hex != value:
        raise ValueError("Invalid task ID")
    return value


def safe_path(root, relative):
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("Symbolic links are not allowed")
    root = root.resolve()
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("Invalid file path")
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("Symbolic links are not allowed")
    return path


class InsufficientStorage(ValueError):
    pass


class JobService:
    def __init__(self, backend=None, database=None):
        self.backend = backend or f"http://127.0.0.1:{config.BACKEND_PORT}"
        self.database = Path(database or DATA / "jobs.sqlite3")
        for path in (DATA, INPUT, OUTPUT, self.database.parent):
            path.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.actions = threading.RLock()
        self.jobs = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.client = httpx.Client(base_url=self.backend, timeout=10, trust_env=False)
        self.live = {}
        self.last_write = {}
        self.readers = Counter()
        self.uploads = 0
        self.executing_id = None
        self.events = deque(maxlen=200)
        self.revision = 0
        self.db = sqlite3.connect(self.database, timeout=10, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created TEXT NOT NULL, document TEXT NOT NULL)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created)")
        self.db.commit()
        self.migrate()
        self.storage = None

    @contextmanager
    def connect(self):
        with self.lock, self.db:
            yield self.db

    def migrate(self):
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            backup = self.database.with_name(self.database.stem + "-v0-backup.sqlite3")
            if not backup.exists():
                with sqlite3.connect(backup) as destination:
                    self.db.backup(destination)
            with self.connect() as db:
                for job_id, document in db.execute(
                    "SELECT id, document FROM jobs"
                ).fetchall():
                    item = self.normalize(json.loads(document))
                    db.execute(
                        "UPDATE jobs SET document=? WHERE id=?",
                        (json.dumps(item, ensure_ascii=False), job_id),
                    )
                db.execute("PRAGMA user_version=1")
        # Adopt completed standalone validation jobs without copying any media.
        if self.database == DATA / "jobs.sqlite3":
            for path in OUTPUT.glob("*/metadata.json"):
                try:
                    item = self.normalize(json.loads(path.read_text()))
                    valid_id(item["id"])
                    if path.parent.name != item["id"] or item["status"] not in TERMINAL:
                        continue
                    if item.get("video_path"):
                        safe_path(OUTPUT / item["id"], Path(item["video_path"]).name)
                        if (
                            Path(item["video_path"]).resolve().parent
                            != path.parent.resolve()
                        ):
                            continue
                    with self.connect() as db:
                        db.execute(
                            "INSERT OR IGNORE INTO jobs VALUES (?, ?, ?)",
                            (
                                item["id"],
                                item["created_at"],
                                json.dumps(item, ensure_ascii=False),
                            ),
                        )
                except (ValueError, KeyError, OSError):
                    LOG.warning("Skipped invalid legacy metadata: %s", path)

    @staticmethod
    def normalize(item):
        item.setdefault(
            "requested_duration_seconds", int(item.get("duration_seconds", 5))
        )
        item.setdefault(
            "stage_code",
            item["status"] if item["status"] != "running" else "recovering",
        )
        item.setdefault("error_code", None)
        return item

    def emit(self, kind, data):
        with self.lock:
            self.revision += 1
            self.events.append(
                {"id": self.revision, "kind": kind, "data": copy.deepcopy(data)}
            )

    def events_after(self, revision):
        with self.lock:
            if revision > self.revision or (
                self.events and revision < self.events[0]["id"] - 1
            ):
                return [{"id": self.revision, "kind": "reset", "data": {}}]
            return [copy.deepcopy(e) for e in self.events if e["id"] > revision]

    def get(self, job_id):
        with self.lock:
            row = self.db.execute(
                "SELECT document FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            item = json.loads(row[0])
            item.update(copy.deepcopy(self.live.get(job_id, {})))
            return item

    def list(
        self,
        limit=30,
        offset=0,
        status=None,
        mode=None,
        search="",
        sort="newest",
        include_storage=False,
    ):
        if include_storage or sort == "size_desc":
            with self.actions:
                sizes = self.storage.task_sizes() if self.storage else {}
                items = self.list(
                    100000,
                    0,
                    status,
                    mode,
                    search,
                    sort="oldest" if sort == "oldest" else "newest",
                )
                if sort == "size_desc":
                    items.sort(
                        key=lambda item: sizes.get(item["id"]) or 0, reverse=True
                    )
                items = items[offset : offset + limit]
                if include_storage:
                    for item in items:
                        item["storage_bytes"] = sizes.get(item["id"])
                return items
        order = "ASC" if sort == "oldest" else "DESC"
        where, args = self.filters(status, mode, search)
        with self.lock:
            rows = self.db.execute(
                f"SELECT id FROM jobs {where} ORDER BY created {order}, id {order} LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
            return [self.get(row[0]) for row in rows]

    @staticmethod
    def filters(status=None, mode=None, search=""):
        terms, args = [], []
        if status == "terminal":
            terms.append(
                "json_extract(document, '$.status') IN ('succeeded','failed','cancelled')"
            )
        elif status:
            terms.append("json_extract(document, '$.status')=?")
            args.append(status)
        if mode:
            terms.append("json_extract(document, '$.mode')=?")
            args.append(mode)
        if search:
            terms.append(
                "instr(lower(json_extract(document, '$.prompt')), lower(?)) > 0"
            )
            args.append(search)
        return ("WHERE " + " AND ".join(terms) if terms else ""), args

    def count(self, status=None, mode=None, search=""):
        where, args = self.filters(status, mode, search)
        with self.lock:
            return self.db.execute(
                f"SELECT COUNT(*) FROM jobs {where}", args
            ).fetchone()[0]

    def update(self, job_id, durable=True, **changes):
        with self.lock:
            item = self.get(job_id)
            if "stage_code" in changes and "stage" not in changes:
                changes["stage"] = STAGES.get(
                    changes["stage_code"], changes["stage_code"]
                )
            if all(item.get(k) == v for k, v in changes.items()):
                return item
            item.update(copy.deepcopy(changes), updated_at=now())
            checkpoint = (
                time.monotonic() - self.last_write.get(job_id, 0)
                >= config.CHECKPOINT_SECONDS
            )
            if durable or checkpoint:
                with self.db:
                    self.db.execute(
                        "UPDATE jobs SET document=? WHERE id=?",
                        (json.dumps(item, ensure_ascii=False), job_id),
                    )
                self.last_write[job_id] = time.monotonic()
                self.live.pop(job_id, None)
            else:
                self.live[job_id] = item
            if self.storage and "status" in changes:
                self.storage.invalidate()
            self.emit("job" if durable else "progress", item)
            return item

    def check_disk(self):
        if shutil.disk_usage(DATA).free < config.MIN_FREE_BYTES:
            raise InsufficientStorage(
                "磁盘可用空间不足，请先清理 / Not enough free disk space; clean storage first"
            )

    def submit(
        self,
        prompt,
        mode="t2v",
        preset=DEFAULT_PRESET,
        seed=-1,
        soundscape="",
        images=(),
        duration_seconds=5,
        source_job_id=None,
        *,
        prompt_format="auto",
        music="",
        reference_descriptions=(),
    ):
        frames = duration_frames(duration_seconds)
        if not prompt.strip() or len(prompt) > 40000:
            raise ValueError(
                "请输入有效的提示词（最多 40000 字符） / Enter a valid prompt (up to 40000 characters)"
            )
        if mode not in MODELS or preset not in PRESETS:
            raise ValueError("不支持的生成模式或画质档位 / Invalid mode or quality")
        if type(seed) is not int or not -1 <= seed <= 2**32 - 1:
            raise ValueError("随机种子应为 -1 或 0–4294967295 的整数 / Invalid seed")
        if len(soundscape) > 4000:
            raise ValueError(
                "声音描述不能超过 4000 字符 / Sound description exceeds 4000 characters"
            )
        if self.stop_event.is_set():
            raise ValueError("服务正在停止 / Service is stopping")
        with self.actions:
            if source_job_id and not images and mode != "t2v":
                source = self.get(source_job_id)
                images = [
                    safe_path(INPUT, name).read_bytes() for name in source["images"]
                ]
            valid = (
                (mode == "t2v" and not images)
                or (mode == "i2v" and len(images) == 1)
                or (mode == "r2v" and 1 <= len(images) <= 3)
            )
            if not valid:
                raise ValueError(
                    "图片数量不正确：首帧 1 张，参考图 1–3 张 / Invalid image count"
                )
            compiled = compile_prompt(
                prompt,
                soundscape,
                mode,
                len(images),
                prompt_format=prompt_format,
                music=music,
                reference_descriptions=reference_descriptions,
            )
            self.check_disk()
            processed = []
            for content in images:
                if len(content) > MAX_UPLOAD:
                    raise ValueError("每张图片不能超过 15MB / Image exceeds 15MB")
                try:
                    with Image.open(io.BytesIO(content)) as source:
                        if (
                            source.width * source.height > Image.MAX_IMAGE_PIXELS
                            or source.format not in {"PNG", "JPEG", "WEBP"}
                        ):
                            raise ValueError(
                                "图片格式或尺寸无效 / Invalid image format or dimensions"
                            )
                        image = ImageOps.exif_transpose(source).convert("RGB")
                        if mode == "i2v":
                            image = ImageOps.fit(
                                image, PRESETS[preset], method=Image.Resampling.LANCZOS
                            )
                        else:
                            image.thumbnail((2048, 2048))
                        processed.append(image)
                except (
                    UnidentifiedImageError,
                    OSError,
                    Image.DecompressionBombError,
                    Image.DecompressionBombWarning,
                ) as error:
                    raise ValueError(
                        "图片无效或尺寸过大 / Invalid or oversized image"
                    ) from error
            job_id = uuid.uuid4().hex
            width, height = PRESETS[preset]
            item = {
                "id": job_id,
                "prompt": prompt,
                "soundscape": soundscape,
                "music": music,
                "reference_descriptions": list(reference_descriptions),
                "mode": mode,
                "preset": preset,
                "seed": secrets.randbelow(2**32) if seed == -1 else seed,
                "width": width,
                "height": height,
                "frames": frames,
                "fps": 24,
                "requested_duration_seconds": duration_seconds,
                "duration_seconds": frames / 24,
                "steps": 20,
                **compiled,
                "status": "queued",
                "stage": STAGES["queued"],
                "stage_code": "queued",
                "progress": 0,
                "created_at": now(),
                "updated_at": now(),
                "started_at": None,
                "finished_at": None,
                "error": None,
                "error_code": None,
                "images": [],
                "video_path": None,
                "video_url": None,
                "cancel_requested": False,
                "metrics": {},
            }
            with self.connect() as db:
                if self.count(status="queued") + self.count(status="running") >= 9:
                    raise ValueError("队列已满，请等待 / Queue is full")
                try:
                    if processed:
                        (INPUT / job_id).mkdir()
                    for index, image in enumerate(processed):
                        name = f"{job_id}/{index + 1}.png"
                        image.save(INPUT / name)
                        item["images"].append(name)
                    db.execute(
                        "INSERT INTO jobs VALUES (?, ?, ?)",
                        (
                            job_id,
                            item["created_at"],
                            json.dumps(item, ensure_ascii=False),
                        ),
                    )
                except Exception:
                    shutil.rmtree(INPUT / job_id, ignore_errors=True)
                    raise
            self.last_write[job_id] = time.monotonic()
            self.jobs.put(job_id)
            self.emit("job", item)
            if self.storage:
                self.storage.invalidate()
            return item

    def start(self):
        if self.thread is None:
            # Rebuild the in-memory scheduler from durable state, running job first.
            self.jobs = queue.Queue()
            pending = self.list(limit=100000)
            for item in sorted(
                (x for x in pending if x["status"] not in TERMINAL),
                key=lambda x: (x["status"] != "running", x["created_at"]),
            ):
                self.jobs.put(item["id"])
            self.thread = threading.Thread(
                target=self.run, daemon=True, name="h3-worker"
            )
            self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)
        with self.lock:
            for job_id in list(self.live):
                item = self.get(job_id)
                with self.db:
                    self.db.execute(
                        "UPDATE jobs SET document=? WHERE id=?",
                        (json.dumps(item, ensure_ascii=False), job_id),
                    )
            self.db.close()
        self.client.close()

    def cancel(self, job_id):
        with self.actions:
            item = self.get(job_id)
            if item["status"] in TERMINAL:
                return item
            if item["status"] == "queued":
                return self.update(
                    job_id,
                    status="cancelled",
                    stage_code="cancelled",
                    finished_at=now(),
                    cancel_requested=True,
                )
            return self.update(job_id, cancel_requested=True, stage_code="cancelling")

    def backend_ready(self):
        try:
            return self.client.get("/system_stats", timeout=2).is_success
        except httpx.HTTPError:
            return False

    def health(self):
        backend = self.backend_ready()
        ready = (
            backend
            and bool(self.thread and self.thread.is_alive())
            and all(models_ready(mode) for mode in MODELS)
        )
        return {
            "status": "ready" if ready else "starting",
            "backend": backend,
            "models": {mode: models_ready(mode) for mode in MODELS},
            "presets": PRESETS,
            "default_preset": DEFAULT_PRESET,
            "offline": True,
            "worker_alive": bool(self.thread and self.thread.is_alive()),
            "version": config.VERSION,
        }

    def backend_state(self, prompt_id):
        history = self.client.get(f"/history/{prompt_id}")
        history.raise_for_status()
        result = history.json().get(prompt_id)
        queue_response = self.client.get("/queue")
        queue_response.raise_for_status()
        tasks = queue_response.json()
        active = any(
            x[1] == prompt_id
            for x in tasks.get("queue_running", []) + tasks.get("queue_pending", [])
        )
        return result, active

    def run(self):
        while not self.stop_event.is_set():
            try:
                job_id = self.jobs.get(timeout=1)
            except queue.Empty:
                continue
            try:
                with self.actions:
                    try:
                        item = self.get(job_id)
                    except KeyError:
                        continue  # A cancelled queued task may already have been deleted.
                    if item["status"] in TERMINAL:
                        continue
                    self.executing_id = job_id
                while not self.stop_event.is_set() and not (
                    self.backend_ready()
                    and all(models_ready(m) for m in [item["mode"]])
                ):
                    self.update(job_id, durable=False, stage_code="waiting")
                    if self.get(job_id)["status"] in TERMINAL:
                        break
                    self.stop_event.wait(5)
                with self.actions:
                    item = self.get(job_id)
                    if item["status"] in TERMINAL or self.stop_event.is_set():
                        continue
                    self.check_disk()
                    recovering = item["status"] == "running"
                    item = self.update(
                        job_id,
                        status="running",
                        stage_code="recovering" if recovering else "loading",
                        started_at=item["started_at"] or now(),
                    )
                self.executing_id = job_id
                self.execute(item, recovering=recovering)
            except Exception as error:
                LOG.exception("Job %s failed", job_id)
                if not self.stop_event.is_set():
                    self.settle_failed(job_id)
                    if not self.stop_event.is_set():
                        code = (
                            "out_of_memory"
                            if "out of memory" in str(error).lower()
                            else "generation_failed"
                        )
                        self.update(
                            job_id,
                            status="failed",
                            stage_code="failed",
                            error=str(error)[:4000],
                            error_code=code,
                            finished_at=now(),
                        )
            finally:
                try:
                    if self.get(job_id)["status"] in TERMINAL:
                        self.client.post(
                            "/free", json={"unload_models": True, "free_memory": True}
                        )
                        if self.storage:
                            self.storage.invalidate()
                except (httpx.HTTPError, KeyError):
                    pass
                self.executing_id = None
                self.jobs.task_done()

    def settle_failed(self, job_id):
        prompt_id = self.get(job_id).get("backend_prompt_id")
        if not prompt_id:
            return
        while not self.stop_event.is_set():
            try:
                _, active = self.backend_state(prompt_id)
                if not active:
                    return
                self.client.post("/interrupt", json={})
                self.client.post("/queue", json={"delete": [prompt_id]})
            except httpx.HTTPError:
                try:
                    pid = int((ROOT / "run/backend.pid").read_text())
                    if not psutil.pid_exists(pid):
                        return
                except (OSError, ValueError):
                    return
            self.stop_event.wait(5)

    def execute(self, item, recovering=False):
        job_id = item["id"]
        directory = OUTPUT / job_id
        directory.mkdir(parents=True, exist_ok=True)
        graph = build_workflow(item)
        workflow = directory / "workflow.json"
        if not workflow.exists():
            workflow.write_text(json.dumps(graph, ensure_ascii=False, indent=2))
        prompt_id = item.get("backend_prompt_id") or str(uuid.UUID(job_id))
        ws_url = self.backend.replace("http://", "ws://").replace("https://", "wss://")
        connection = websocket.create_connection(
            f"{ws_url}/ws?clientId={job_id}",
            timeout=2,
            http_no_proxy=["127.0.0.1", "localhost"],
        )
        started = time.monotonic()
        elapsed_before = (
            item.get("metrics", {}).get("elapsed_seconds", 0) if recovering else 0
        )
        metrics = {
            "peak_gpu_used_mib": 0,
            "peak_backend_rss_mib": 0,
            "min_system_available_mib": psutil.virtual_memory().available / 2**20,
        }
        metrics.update(item.get("metrics", {}))
        last_metrics = last_check = 0
        interrupted = False
        try:
            if recovering:
                result, active = self.backend_state(prompt_id)
                if not result and not active:
                    raise RuntimeError(
                        "服务重启，后端任务已中断，请重新提交 / Backend task was interrupted; retry manually"
                    )
            else:
                # Persist before dispatch so a lost HTTP response cannot cause duplicate generation.
                self.update(job_id, backend_prompt_id=prompt_id)
                response = self.client.post(
                    "/prompt",
                    json={"prompt": graph, "client_id": job_id, "prompt_id": prompt_id},
                )
                response.raise_for_status()
            while not self.stop_event.is_set():
                current = self.get(job_id)
                if current["cancel_requested"] and not interrupted:
                    self.client.post("/interrupt", json={})
                    self.client.post("/queue", json={"delete": [prompt_id]})
                    interrupted = True
                stamp = time.monotonic()
                if stamp - last_metrics >= 10:
                    self.measure(metrics)
                    metrics["elapsed_seconds"] = round(
                        elapsed_before + stamp - started, 2
                    )
                    self.update(job_id, durable=False, metrics=metrics)
                    last_metrics = stamp
                message = None
                try:
                    message = connection.recv()
                except websocket.WebSocketTimeoutException:
                    pass
                except (
                    websocket.WebSocketConnectionClosedException,
                    ConnectionError,
                    OSError,
                ):
                    connection.close()
                    if not self.backend_ready():
                        raise RuntimeError("推理引擎已停止 / Inference backend stopped")
                    connection = websocket.create_connection(
                        f"{ws_url}/ws?clientId={job_id}",
                        timeout=2,
                        http_no_proxy=["127.0.0.1", "localhost"],
                    )
                if isinstance(message, str) and message:
                    event = json.loads(message)
                    event_data = event.get("data", {})
                    if event_data.get("prompt_id") == prompt_id:
                        if event["type"] == "progress":
                            self.update(
                                job_id,
                                durable=False,
                                progress=round(
                                    event_data["value"]
                                    / max(event_data["max"], 1)
                                    * 90,
                                    1,
                                ),
                                stage_code="cancelling" if interrupted else "sampling",
                                sample_step=event_data["value"],
                                sample_steps=event_data["max"],
                            )
                        elif event["type"] == "executing" and event_data.get("node"):
                            kind = graph.get(str(event_data["node"]), {}).get(
                                "class_type", ""
                            )
                            stage = {
                                "VAEDecode": "video_decode",
                                "VAEDecodeAudio": "audio_decode",
                                "SaveVideo": "saving",
                            }.get(kind)
                            stage = stage or (
                                "encoding"
                                if kind.startswith("MiniMaxH3")
                                else "loading"
                                if "Loader" in kind
                                else "sampling"
                            )
                            self.update(
                                job_id,
                                durable=stage != self.get(job_id)["stage_code"],
                                stage_code="cancelling" if interrupted else stage,
                            )
                        elif event["type"] == "execution_error" and not interrupted:
                            raise RuntimeError(
                                event_data.get("exception_message", "Inference error")
                            )
                if stamp - last_check >= 5 or interrupted:
                    result, active = self.backend_state(prompt_id)
                    last_check = stamp
                    if interrupted and not active:
                        self.update(
                            job_id,
                            status="cancelled",
                            stage_code="cancelled",
                            finished_at=now(),
                            metrics=metrics,
                        )
                        return
                    if result and result.get("status", {}).get("status_str") == "error":
                        raise RuntimeError(
                            json.dumps(
                                result["status"].get("messages", []), ensure_ascii=False
                            )[-3500:]
                        )
                    if result and result.get("status", {}).get("completed"):
                        break
                    if not result and not active:
                        raise RuntimeError(
                            "后端任务记录丢失 / Backend task no longer exists"
                        )
            else:
                return  # API restart detaches; the next instance reconciles the durable prompt ID.
        finally:
            connection.close()
        metrics["elapsed_seconds"] = round(
            elapsed_before + time.monotonic() - started, 2
        )
        self.finalize(job_id, directory, metrics)

    def finalize(self, job_id, directory, metrics):
        candidates = sorted(directory.glob("*.mp4"))
        if not candidates:
            raise RuntimeError("推理结束，但未找到输出视频 / Output video missing")
        target = directory / "result.mp4"
        source = target if target.exists() else candidates[0]
        probe = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(source),
                ],
                timeout=30,
            )
        )
        video = next((s for s in probe["streams"] if s["codec_type"] == "video"), None)
        audio = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)
        expected = self.get(job_id)
        if not video or not audio or audio.get("channels") != 2:
            raise RuntimeError(
                "输出缺少视频或双声道音轨 / Video or stereo audio missing"
            )
        if int(video.get("nb_frames", 0)) != expected["frames"] or (
            video["width"],
            video["height"],
        ) != (expected["width"], expected["height"]):
            raise RuntimeError(
                "输出尺寸或帧数不符合请求 / Output dimensions or frame count mismatch"
            )
        if (
            float(Fraction(video.get("avg_frame_rate", "0"))) != expected["fps"]
            or abs(float(video.get("duration", 0)) - expected["duration_seconds"])
            > 0.05
            or abs(float(audio.get("duration", 0)) - expected["duration_seconds"])
            > 0.25
        ):
            raise RuntimeError(
                "输出帧率或音画时长不匹配 / Output frame rate or AV duration mismatch"
            )
        # ComfyUI already writes faststart MP4. Rename on the same filesystem, without remux/copy.
        if source != target:
            source.replace(target)
        poster = directory / "poster.webp"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(target),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=480:-2",
                    str(poster),
                ],
                check=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError):
            LOG.warning("Poster generation failed for %s", job_id)
        media = {
            "duration": probe["format"].get("duration"),
            "streams": [
                {
                    k: s.get(k)
                    for k in (
                        "codec_type",
                        "codec_name",
                        "width",
                        "height",
                        "sample_rate",
                        "channels",
                        "nb_frames",
                        "avg_frame_rate",
                        "duration",
                    )
                }
                for s in probe["streams"]
            ],
        }
        item = self.update(
            job_id,
            status="succeeded",
            stage_code="succeeded",
            progress=100,
            finished_at=now(),
            video_path=str(target),
            video_url=f"/api/jobs/{job_id}/video",
            metrics=metrics,
            media=media,
        )
        (directory / "metadata.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2)
        )

    @staticmethod
    def measure(metrics):
        metrics["min_system_available_mib"] = min(
            metrics["min_system_available_mib"],
            psutil.virtual_memory().available / 2**20,
        )
        try:
            pid_path = ROOT / "run/backend.pid"
            if pid_path.exists():
                process = psutil.Process(int(pid_path.read_text()))
                metrics["peak_backend_rss_mib"] = max(
                    metrics["peak_backend_rss_mib"], process.memory_info().rss / 2**20
                )
            value = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                ],
                timeout=3,
                text=True,
            ).splitlines()[0]
            metrics["peak_gpu_used_mib"] = max(metrics["peak_gpu_used_mib"], int(value))
        except (OSError, ValueError, psutil.Error, subprocess.SubprocessError):
            LOG.debug("Resource sampling unavailable", exc_info=True)
