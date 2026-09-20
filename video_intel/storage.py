"""Ownership-based cleanup. No client-supplied filesystem paths are accepted."""

import shutil
import time
from pathlib import Path

from . import config
from . import service as jobs


def allocated(path):
    path = Path(path)
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return 0
    size = getattr(stat, "st_blocks", 0) * 512 or stat.st_size
    if path.is_symlink() or not path.is_dir():
        return size
    return size + sum(allocated(child) for child in path.iterdir())


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
    if path.exists() or path.is_symlink():
        raise OSError(f"Unable to remove {path.name}")


class Storage:
    def __init__(self, service):
        self.service = service
        self.cached = None
        self.cached_at = 0
        self.sizes_at = 0
        self.sizes = {}
        service.storage = self

    def invalidate(self):
        self.cached_at = 0
        self.sizes_at = 0

    def task_sizes(self, refresh=False):
        """Read only task-owned paths; share the result across list and overview."""
        with self.service.actions:
            if not refresh and self.sizes_at and time.monotonic() - self.sizes_at < 60:
                return self.sizes
            sizes = {}
            for item in self.service.list(limit=100000):
                try:
                    sizes[item["id"]] = sum(allocated(p) for p in self.task_paths(item))
                except (ValueError, OSError):
                    sizes[item["id"]] = None
            self.sizes = sizes
            self.sizes_at = time.monotonic()
            return sizes

    def task_paths(self, item):
        job_id = jobs.valid_id(item["id"])
        paths = [
            jobs.safe_path(jobs.OUTPUT, job_id),
            jobs.safe_path(jobs.INPUT, job_id),
            jobs.safe_path(config.TMP / "jobs", job_id),
        ]
        for name in item["images"]:
            if name.startswith(job_id + "_") and "/" not in name and "\\" not in name:
                paths.append(jobs.safe_path(jobs.INPUT, name))
        return paths

    def busy(self):
        return bool(
            self.service.count(status="queued") + self.service.count(status="running")
            or self.service.uploads
            or self.service.executing_id
        )

    def snapshot(self, refresh=False, include_jobs=True):
        with self.service.actions:
            if self.cached and not refresh and time.monotonic() - self.cached_at < 60:
                return {
                    k: v for k, v in self.cached.items() if include_jobs or k != "jobs"
                }
            sizes = self.task_sizes(refresh)
            items = []
            for item in self.service.list(limit=100000):
                try:
                    size = sizes.get(item["id"])
                    items.append(
                        {
                            "id": item["id"],
                            "prompt": item["prompt"][:160],
                            "status": item["status"],
                            "mode": item["mode"],
                            "preset": item["preset"],
                            "duration_seconds": item["duration_seconds"],
                            "created_at": item["created_at"],
                            "bytes": size,
                            "cleanup_error": item.get("cleanup_error"),
                        }
                    )
                except (ValueError, OSError):
                    continue
            disk = shutil.disk_usage(jobs.DATA)
            categories = {
                "tasks": allocated(jobs.INPUT) + allocated(jobs.OUTPUT),
                "temporary": allocated(config.TMP),
                "cache": allocated(config.CACHE),
                "logs": allocated(config.LOGS),
                "database": sum(
                    allocated(Path(str(self.service.database) + suffix))
                    for suffix in ("", "-wal", "-shm")
                ),
                "protected": allocated(config.ROOT / "models")
                + allocated(config.ROOT / ".venv")
                + allocated(config.ROOT / "vendor"),
            }
            self.cached = {
                "categories": categories,
                "jobs": items,
                "disk": {"total": disk.total, "used": disk.used, "free": disk.free},
                "project_bytes": sum(categories.values()),
                "updated_at": jobs.now(),
                "busy": self.busy(),
                "cleanable_bytes": self.preview([], ["residual", "temporary"])[
                    "estimated_bytes"
                ],
            }
            self.cached_at = time.monotonic()
            return {k: v for k, v in self.cached.items() if include_jobs or k != "jobs"}

    def residual_paths(self):
        paths = []
        for item in self.service.list(limit=100000, status="terminal"):
            if (
                self.service.readers[item["id"]]
                or self.service.executing_id == item["id"]
            ):
                continue
            root = jobs.safe_path(jobs.OUTPUT, item["id"])
            if not root.exists():
                continue
            keep = {"workflow.json", "metadata.json", "poster.webp"}
            if item["status"] == "succeeded" and item.get("video_path"):
                primary = jobs.safe_path(root, Path(item["video_path"]).name)
                if not primary.is_file():
                    continue
                keep.add(primary.name)
            paths += [
                p for p in root.iterdir() if p.name not in keep and not p.is_symlink()
            ]
        return paths

    def candidates(self, job_ids, kinds):
        if len(job_ids) > 100:
            raise ValueError("每次最多清理 100 个任务 / Maximum 100 tasks per cleanup")
        allowed = {"residual", "temporary", "cache", "logs", "database"}
        if not set(kinds) <= allowed:
            raise ValueError("Invalid cleanup category")
        groups, skipped = [], []
        for job_id in dict.fromkeys(job_ids):
            jobs.valid_id(job_id)
            try:
                item = self.service.get(job_id)
                if (
                    item["status"] not in jobs.TERMINAL
                    or self.service.readers[job_id]
                    or self.service.executing_id == job_id
                ):
                    skipped.append(
                        {
                            "id": job_id,
                            "reason": "任务运行中或文件正在读取 / Task active or file in use",
                        }
                    )
                    continue
                groups.append((job_id, self.task_paths(item)))
            except KeyError:
                skipped.append(
                    {"id": job_id, "reason": "任务已不存在 / Already removed"}
                )
        for kind in dict.fromkeys(kinds):
            if kind in {"temporary", "cache", "database"} and self.busy():
                skipped.append(
                    {
                        "id": kind,
                        "reason": "请等待任务和上传结束 / Wait until the engine and uploads are idle",
                    }
                )
                continue
            if kind == "residual":
                # Explicit task deletion already owns these paths.
                deleting = set(job_ids)
                paths = [
                    p for p in self.residual_paths() if p.parent.name not in deleting
                ]
            elif kind in {"temporary", "cache"}:
                root = config.TMP if kind == "temporary" else config.CACHE
                if root.is_symlink():
                    raise ValueError("Runtime root cannot be a symbolic link")
                paths = []
                if root.exists():
                    for child in root.iterdir():
                        if (
                            kind == "temporary"
                            and child.name == "comfy"
                            and not child.is_symlink()
                            and not (child / "temp").is_symlink()
                            and (child / "temp").is_dir()
                        ):
                            paths.extend((child / "temp").iterdir())
                        elif child.is_dir() and not child.is_symlink():
                            paths.extend(child.iterdir())
                        else:
                            paths.append(child)
            elif kind == "logs":
                paths = [
                    p
                    for p in config.LOGS.glob("*.log.*")
                    if p.name.rsplit(".", 1)[-1].isdigit()
                ]
            else:
                paths = []
            groups.append((kind, paths))
        return groups, skipped

    def preview(self, job_ids, kinds):
        with self.service.actions:
            groups, skipped = self.candidates(job_ids, kinds)
            return {
                "estimated_bytes": sum(
                    allocated(p) for _, paths in groups for p in paths
                ),
                "items": [
                    {"id": k, "bytes": sum(allocated(p) for p in paths)}
                    for k, paths in groups
                ],
                "skipped": skipped,
            }

    def cleanup(self, job_ids, kinds):
        deleted, failed = [], []
        with self.service.actions:
            groups, skipped = self.candidates(job_ids, kinds)
            for key, paths in groups:
                reclaimed = 0
                try:
                    if key == "database":
                        before = allocated(self.service.database)
                        with self.service.lock:
                            self.service.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            self.service.db.execute("VACUUM")
                        reclaimed = max(0, before - allocated(self.service.database))
                    else:
                        if key in job_ids:
                            self.service.update(key, deleting=True, cleanup_error=None)
                        for path in paths:
                            size = allocated(path)
                            remove(path)
                            reclaimed += size
                        if key in job_ids:
                            with self.service.connect() as db:
                                db.execute("DELETE FROM jobs WHERE id=?", (key,))
                                self.service.live.pop(key, None)
                    deleted.append({"id": key, "reclaimed_bytes": reclaimed})
                except (OSError, ValueError, RuntimeError) as error:
                    if key in job_ids:
                        self.service.update(key, cleanup_error=str(error)[:500])
                    failed.append(
                        {"id": key, "reason": str(error), "reclaimed_bytes": reclaimed}
                    )
            self.invalidate()
            result = {
                "deleted": deleted,
                "failed": failed,
                "skipped": skipped,
                "reclaimed_bytes": sum(x["reclaimed_bytes"] for x in deleted + failed),
            }
            self.service.emit("storage", result)
            return result

    def recover(self):
        ids = [
            x["id"]
            for x in self.service.list(limit=100000, status="terminal")
            if x.get("deleting")
        ]
        for offset in range(0, len(ids), 100):
            self.cleanup(ids[offset : offset + 100], [])
