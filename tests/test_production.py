import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from video_intel import config
from video_intel import service as module
from video_intel.service import JobService, safe_path
from video_intel.storage import Storage
from video_intel.workflows import build_workflow


@pytest.fixture
def local(tmp_path, monkeypatch):
    data = tmp_path / "data"
    for key, value in {
        "ROOT": tmp_path,
        "DATA": data,
        "TMP": tmp_path / "tmp",
        "CACHE": tmp_path / "cache",
        "LOGS": tmp_path / "logs",
        "RUN": tmp_path / "run",
    }.items():
        monkeypatch.setattr(config, key, value)
        value.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "MIN_FREE_BYTES", 0)
    for key, value in {
        "ROOT": tmp_path,
        "DATA": data,
        "INPUT": data / "inputs",
        "OUTPUT": data / "outputs",
    }.items():
        monkeypatch.setattr(module, key, value)
    instance = JobService(database=data / "jobs.sqlite3")
    Storage(instance)
    yield instance
    instance.close()


@pytest.mark.parametrize(
    "seconds,frames",
    [
        (4, 107),
        (5, 124),
        (6, 158),
        (7, 175),
        (8, 192),
        (9, 226),
        (10, 243),
        (11, 277),
        (12, 294),
        (13, 328),
        (14, 345),
        (15, 362),
    ],
)
def test_duration_contract(local, seconds, frames):
    item = local.submit("A bird", duration_seconds=seconds)
    assert item["frames"] == frames
    assert item["duration_seconds"] == frames / 24
    assert item["requested_duration_seconds"] == seconds
    assert build_workflow(item)["5"]["inputs"]["length"] == frames


@pytest.mark.parametrize("duration", [3, 16, 0, 5.5, True, "10"])
def test_invalid_duration(local, duration):
    with pytest.raises(ValueError):
        local.submit("A bird", duration_seconds=duration)
    assert local.count() == 0


def test_telemetry_writes_are_bounded(local, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    item = local.submit("A bird")
    trace = []
    local.db.set_trace_callback(trace.append)
    for index in range(100):
        local.update(item["id"], durable=False, progress=index)
    assert not [s for s in trace if s.startswith("UPDATE")]
    assert local.get(item["id"])["progress"] == 99
    document = local.db.execute("SELECT document FROM jobs").fetchone()[0]
    assert json.loads(document)["progress"] == 0
    clock[0] = 161
    local.update(item["id"], durable=False, progress=99.5)
    assert len([s for s in trace if s.startswith("UPDATE")]) == 1
    local.update(item["id"], status="succeeded")
    assert len([s for s in trace if s.startswith("UPDATE")]) == 2


def completed(local):
    job = local.submit("A bird")
    path = module.OUTPUT / job["id"]
    path.mkdir()
    (path / "result.mp4").write_bytes(b"0123456789" * 100)
    (path / "metadata.json").write_text("{}")
    job = local.update(
        job["id"], status="succeeded", video_path=str(path / "result.mp4")
    )
    return job, path


def test_cleanup_protects_active_tasks_and_readers(local):
    job, path = completed(local)
    queued = local.submit("Waiting")
    local.readers[job["id"]] += 1
    result = local.storage.cleanup([job["id"], queued["id"]], [])
    assert not result["deleted"] and len(result["skipped"]) == 2
    assert path.exists()
    local.readers[job["id"]] -= 1
    result = local.storage.cleanup([job["id"]], [])
    assert result["reclaimed_bytes"] > 0 and not path.exists()
    with pytest.raises(KeyError):
        local.get(job["id"])
    assert local.storage.cleanup([job["id"]], [])["reclaimed_bytes"] == 0


def test_cleanup_recovers_partial_failure(local, monkeypatch):
    from video_intel import storage

    job, path = completed(local)
    original = storage.remove
    monkeypatch.setattr(storage, "remove", Mock(side_effect=OSError("Read-only test")))
    result = local.storage.cleanup([job["id"]], [])
    assert result["failed"] and local.get(job["id"])["deleting"]
    assert path.exists()
    monkeypatch.setattr(storage, "remove", original)
    local.storage.recover()
    assert not path.exists()
    with pytest.raises(KeyError):
        local.get(job["id"])


def test_residual_cleanup_keeps_final_video(local):
    job, path = completed(local)
    duplicate = path / "video_00001_.mp4"
    duplicate.write_bytes(b"duplicate")
    local.storage.cleanup([], ["residual"])
    assert not duplicate.exists()
    assert (path / "result.mp4").exists() and (path / "metadata.json").exists()
    assert local.get(job["id"])["status"] == "succeeded"


def test_cleanup_does_not_follow_symlinks(local, tmp_path):
    job, path = completed(local)
    external = tmp_path / "unrelated"
    external.mkdir()
    (external / "keep.txt").write_text("keep")
    (path / "link").symlink_to(external, target_is_directory=True)
    local.storage.cleanup([job["id"]], [])
    assert (external / "keep.txt").read_text() == "keep"
    (module.OUTPUT / "bad").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError):
        safe_path(module.OUTPUT / "bad", "keep.txt")
    with pytest.raises(ValueError):
        safe_path(module.OUTPUT, "../jobs.sqlite3")


def test_cache_cleanup_waits_for_upload_and_queue(local):
    cache = config.CACHE / "compiler"
    cache.mkdir()
    (cache / "keep.bin").write_bytes(b"cache")
    local.uploads = 1
    assert local.storage.cleanup([], ["cache"])["skipped"]
    local.uploads = 0
    job = local.submit("A bird")
    assert local.storage.cleanup([], ["cache"])["skipped"]
    local.cancel(job["id"])
    assert local.storage.cleanup([], ["cache"])["reclaimed_bytes"] > 0


def test_disk_admission_before_writing_inputs(local, monkeypatch):
    monkeypatch.setattr(config, "MIN_FREE_BYTES", 10**30)
    with pytest.raises(ValueError, match="磁盘"):
        local.submit("A bird")
    assert local.count() == 0 and not list(module.INPUT.iterdir())


def test_standalone_metadata_import(local):
    job, path = completed(local)
    document = local.get(job["id"])
    document.update(
        frames=243, duration_seconds=243 / 24, requested_duration_seconds=10
    )
    (path / "metadata.json").write_text(json.dumps(document))
    with local.connect() as db:
        db.execute("DELETE FROM jobs")
    local.migrate()
    assert local.get(job["id"])["frames"] == 243
    assert local.get(job["id"])["requested_duration_seconds"] == 10


def backend_setup(local, monkeypatch):
    connection = Mock()
    connection.recv.return_value = None
    monkeypatch.setattr(
        module.websocket, "create_connection", lambda *a, **kw: connection
    )
    monkeypatch.setattr(local, "measure", lambda metrics: None)
    post = Mock()
    monkeypatch.setattr(local.client, "post", post)
    return post


def test_recovery_does_not_resubmit(local, monkeypatch):
    post = backend_setup(local, monkeypatch)
    job = local.submit("A bird")
    job = local.update(job["id"], status="running", backend_prompt_id="known")
    monkeypatch.setattr(
        local, "backend_state", lambda _: ({"status": {"completed": True}}, False)
    )
    monkeypatch.setattr(
        local, "finalize", lambda job_id, *_: local.update(job_id, status="succeeded")
    )
    local.execute(job, recovering=True)
    post.assert_not_called()
    assert local.get(job["id"])["status"] == "succeeded"


def test_missing_recovery_never_replays(local, monkeypatch):
    post = backend_setup(local, monkeypatch)
    job = local.submit("A bird")
    monkeypatch.setattr(local, "backend_state", lambda _: (None, False))
    with pytest.raises(RuntimeError, match="中断"):
        local.execute(job, recovering=True)
    post.assert_not_called()


def test_dispatch_persists_id_before_request(local, monkeypatch):
    backend_setup(local, monkeypatch)
    job = local.submit("A bird")

    def post(path, json):
        assert path == "/prompt"
        assert local.get(job["id"])["backend_prompt_id"] == json["prompt_id"]
        return Mock()

    monkeypatch.setattr(local.client, "post", post)
    monkeypatch.setattr(
        local, "backend_state", lambda _: ({"status": {"completed": True}}, False)
    )
    monkeypatch.setattr(local, "finalize", lambda *args: None)
    local.execute(job)


def test_cancel_waits_for_backend_confirmation(local, monkeypatch):
    backend_setup(local, monkeypatch)
    job = local.submit("A bird")
    job = local.update(job["id"], status="running", cancel_requested=True)
    checks = [True, False]

    def state(_):
        assert local.get(job["id"])["status"] == "running"
        return None, checks.pop(0)

    monkeypatch.setattr(local, "backend_state", state)
    local.execute(job)
    assert not checks and local.get(job["id"])["status"] == "cancelled"


@pytest.fixture
def client(local, monkeypatch):
    (config.ROOT / "static").mkdir(exist_ok=True)
    from video_intel import app as application

    monkeypatch.setattr(application, "service", local)
    monkeypatch.setattr(application, "storage", local.storage)
    monkeypatch.setattr(application, "INPUT", module.INPUT)
    monkeypatch.setattr(application, "OUTPUT", module.OUTPUT)
    return TestClient(application.app)


def test_api_compatibility_and_pagination(local, client):
    first = client.post("/api/jobs", data={"prompt": "A bird"})
    assert first.status_code == 202 and first.json()["frames"] == 124
    second = client.post(
        "/api/jobs", data={"prompt": "A river", "duration_seconds": "15"}
    )
    assert second.status_code == 202 and second.json()["frames"] == 362
    invalid = client.post(
        "/api/jobs", data={"prompt": "A bird", "duration_seconds": "16"}
    )
    assert invalid.status_code == 422
    page = client.get("/api/jobs?limit=1&offset=1")
    assert page.headers["X-Total-Count"] == "2" and len(page.json()) == 1
    assert len(client.get("/api/jobs?search=river").json()) == 1
    assert len(client.get("/api/capabilities").json()["durations"]) == 12


def test_prompt_preview_is_read_only_and_matches_submission(local, client):
    data = {
        "prompt": "A person (S1) says: <d>[Chinese] 你好！</d>",
        "soundscape": "Light wind.",
        "music": "Sparse piano notes.",
        "prompt_format": "guided",
    }
    writes = local.db.total_changes
    preview = client.post("/api/prompts/preview", json=data)
    assert preview.status_code == 200
    assert local.db.total_changes == writes
    assert local.count() == 0
    assert local.jobs.qsize() == 0
    submitted = client.post("/api/jobs", data=data)
    assert submitted.status_code == 202
    for key, value in preview.json().items():
        assert submitted.json()[key] == value
    assert (
        build_workflow(submitted.json())["5"]["inputs"]["prompt"]
        == preview.json()["effective_prompt"]
    )


def test_preview_and_submission_preserve_reference_order_and_reuse(local, client):
    import io

    from PIL import Image

    content = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(content, format="PNG")
    data = {
        "prompt": "<Subject 1> holds <Subject 3> next to <Subject 2>.",
        "mode": "r2v",
    }
    descriptions = ["Person", "Basketball", "Coffee cup"]
    preview = client.post(
        "/api/prompts/preview",
        json={
            **data,
            "image_count": 3,
            "reference_descriptions": descriptions,
        },
    )
    submitted = client.post(
        "/api/jobs",
        data={
            **data,
            "reference_descriptions": json.dumps(descriptions),
        },
        files=[
            ("images", (f"{i}.png", content.getvalue(), "image/png")) for i in range(3)
        ],
    )
    assert submitted.status_code == 202
    original = submitted.json()
    assert original["effective_prompt"] == preview.json()["effective_prompt"]
    reused = {**data, "source_job_id": original["id"]}
    reused_preview = client.post(
        "/api/prompts/preview",
        json={
            **reused,
            "reference_descriptions": descriptions,
        },
    )
    reused_job = client.post(
        "/api/jobs",
        data={
            **reused,
            "reference_descriptions": json.dumps(descriptions),
        },
    )
    assert reused_job.status_code == 202
    assert (
        reused_job.json()["effective_prompt"]
        == reused_preview.json()["effective_prompt"]
    )
    assert reused_job.json()["reference_descriptions"] == descriptions


def test_raw_api_retains_whitespace_and_exposes_ignored_settings(client):
    raw = "\n integrated_multimodal_description:\n[Shot 1] A bird.\noverall_soundscape:\nWind.\nnon_diegetic_music:\nN/A\n "
    data = {"prompt": raw, "soundscape": "This should not be merged."}
    preview = client.post("/api/prompts/preview", json=data)
    result = client.post("/api/jobs", data=data)
    assert result.status_code == 202
    assert result.json()["prompt_format"] == "raw"
    assert result.json()["prompt"] == result.json()["effective_prompt"] == raw
    assert result.json()["prompt_warnings"] == preview.json()["prompt_warnings"]
    assert result.json()["prompt_warnings"]


@pytest.mark.parametrize("prompt_format", ["guided", "raw"])
def test_browser_text_encoding_matches_json_preview(client, prompt_format):
    fields = {
        "prompt": " \n[Shot 1] A cup drops.\nIt rings.\n ",
        "soundscape": "Wind.\nA clink.",
        "music": "Piano.\nSlow fade.",
    }
    preview = client.post(
        "/api/prompts/preview", json={**fields, "prompt_format": prompt_format}
    )
    submitted = client.post(
        "/api/jobs",
        data={
            **{key: json.dumps(value) for key, value in fields.items()},
            "prompt_format": prompt_format,
            "text_encoding": "json",
        },
    )
    assert submitted.status_code == 202
    assert submitted.json()["effective_prompt"] == preview.json()["effective_prompt"]
    assert submitted.json()["prompt"] == fields["prompt"]


def test_encoded_prompt_keeps_sound_fields_optional(client):
    result = client.post(
        "/api/jobs",
        data={
            "prompt": json.dumps("A bird.\nA breeze."),
            "text_encoding": "json",
        },
    )
    assert result.status_code == 202
    assert result.json()["prompt"] == "A bird.\nA breeze."
    assert result.json()["soundscape"] == result.json()["music"] == ""


@pytest.mark.parametrize("value", ["invalid", "123", "null", "[]"])
def test_invalid_encoded_text_is_rejected_without_a_job(local, client, value):
    result = client.post(
        "/api/jobs",
        data={
            "prompt": value,
            "soundscape": '""',
            "music": '""',
            "text_encoding": "json",
        },
    )
    assert result.status_code == 422
    assert local.count() == 0


@pytest.mark.parametrize("value", ["not json", "{}", "[1]", '["' + "x" * 1001 + '"]'])
def test_reference_metadata_validation_does_not_create_tasks(local, client, value):
    result = client.post(
        "/api/jobs", data={"prompt": "A bird", "reference_descriptions": value}
    )
    assert result.status_code == 422
    assert local.count() == 0


def test_queued_prompt_snapshot_does_not_change_with_template(local, monkeypatch):
    item = local.submit("A bird")
    original = item["effective_prompt"]
    monkeypatch.setattr(
        module,
        "compile_prompt",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not recompile")
        ),
    )
    reopened = JobService(database=local.database)
    try:
        saved = reopened.get(item["id"])
        assert build_workflow(saved)["5"]["inputs"]["prompt"] == original
    finally:
        reopened.close()


def test_video_ranges_and_cleanup_api(local, client):
    job, _ = completed(local)
    response = client.get(
        f"/api/jobs/{job['id']}/video", headers={"Range": "bytes=0-3"}
    )
    assert response.status_code == 206 and response.content == b"0123"
    assert local.readers[job["id"]] == 0
    assert (
        client.post(
            "/api/storage/cleanup/preview", json={"job_ids": [job["id"]]}
        ).json()["estimated_bytes"]
        > 0
    )
    assert (
        client.post("/api/storage/cleanup", json={"job_ids": ["../models"]}).status_code
        == 422
    )
    assert (
        client.post("/api/storage/cleanup", json={"kinds": ["models"]}).status_code
        == 422
    )
    assert client.post("/api/storage/cleanup", json={"job_ids": [job["id"]]}).json()[
        "deleted"
    ]
    assert client.get(f"/api/jobs/{job['id']}/video").status_code == 404


def test_deleted_queued_task_does_not_stop_worker(local, monkeypatch):
    removed = local.submit("Removed queue entry")
    local.cancel(removed["id"])
    local.storage.cleanup([removed["id"]], [])
    following = local.submit("Next task")
    monkeypatch.setattr(local, "backend_ready", lambda: True)
    monkeypatch.setattr(module, "models_ready", lambda _: True)
    local.client.post = Mock()

    def execute(item, recovering=False):
        local.update(item["id"], status="succeeded")
        local.stop_event.set()

    monkeypatch.setattr(local, "execute", execute)
    local.run()
    assert local.get(following["id"])["status"] == "succeeded"


def test_linux_process_identity_ignores_wall_clock(local, monkeypatch):
    import os

    import psutil

    from video_intel import control
    from video_intel.process_identity import token

    process = psutil.Process(os.getpid())
    (config.RUN / "supervisor.identity.json").write_text(
        json.dumps({"pid": process.pid, "created": 0, **token(process.pid)})
    )
    monkeypatch.setattr(psutil.Process, "cmdline", lambda _: ["video_intel.launch"])
    assert control.running().pid == process.pid
    (config.RUN / "supervisor.identity.json").write_text(
        json.dumps(
            {
                "pid": process.pid,
                "start_ticks": "wrong",
                "boot_id": token(process.pid)["boot_id"],
            }
        )
    )
    assert control.running() is None


def test_temporary_comfy_symlink_does_not_delete_target(local, tmp_path):
    outside = tmp_path / "unowned"
    (outside / "temp").mkdir(parents=True)
    sentinel = outside / "temp/keep.txt"
    sentinel.write_text("keep")
    (config.TMP / "comfy").symlink_to(outside, target_is_directory=True)
    result = local.storage.cleanup([], ["temporary"])
    assert not result["failed"]
    assert sentinel.read_text() == "keep"


def test_temporary_cleanup_preserves_runtime_namespaces(local):
    for name in ("runtime", "comfy/temp"):
        directory = config.TMP / name
        directory.mkdir(parents=True)
        (directory / "leftover").write_text("temporary data")
    local.storage.cleanup([], ["temporary"])
    assert (config.TMP / "runtime").is_dir()
    assert (config.TMP / "comfy/temp").is_dir()
    assert not (config.TMP / "runtime/leftover").exists()


def test_request_body_limit(client):
    response = client.post(
        "/api/jobs", content=b"x", headers={"Content-Length": str(47 * 1024**2)}
    )
    assert response.status_code == 413


@pytest.mark.parametrize("audio_duration,fps", [(1, "24/1"), (124 / 24, "12/1")])
def test_finalize_rejects_short_audio_or_wrong_fps(
    local, monkeypatch, audio_duration, fps
):
    item = local.submit("A bird")
    directory = module.OUTPUT / item["id"]
    directory.mkdir()
    (directory / "raw.mp4").write_bytes(b"placeholder")
    probe = {
        "format": {"duration": str(124 / 24)},
        "streams": [
            {
                "codec_type": "video",
                "width": item["width"],
                "height": item["height"],
                "nb_frames": "124",
                "avg_frame_rate": fps,
                "duration": str(124 / 24),
            },
            {"codec_type": "audio", "channels": 2, "duration": str(audio_duration)},
        ],
    }
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps(probe).encode(),
    )
    with pytest.raises(RuntimeError, match="AV duration"):
        local.finalize(item["id"], directory, {})
    assert not (directory / "result.mp4").exists()


def test_sse_reconnect_resets_revision_from_previous_process(local):
    reset = local.events_after(1000)
    assert reset == [{"id": 0, "kind": "reset", "data": {}}]
    local.emit("job", {"id": "example"})
    assert local.events_after(reset[0]["id"])[0]["kind"] == "job"


def test_storage_sort_is_global_and_default_list_does_not_scan(
    local, client, monkeypatch
):
    first, folder = completed(local)
    (folder / "large.bin").write_bytes(b"x" * 64000)
    second, _ = completed(local)
    third, _ = completed(local)
    original = local.storage.task_sizes
    scan = Mock(side_effect=original)
    monkeypatch.setattr(local.storage, "task_sizes", scan)
    default = client.get("/api/jobs?limit=1")
    assert default.json()[0]["id"] == third["id"]
    assert "storage_bytes" not in default.json()[0]
    scan.assert_not_called()
    result = client.get("/api/jobs?sort=size_desc&include_storage=true&limit=1")
    assert result.headers["X-Total-Count"] == "3"
    assert result.json()[0]["id"] == first["id"]
    assert result.json()[0]["storage_bytes"] >= 64000
    assert (
        client.get("/api/jobs?sort=size_desc&offset=1&limit=1").json()[0]["id"]
        == third["id"]
    )
    assert client.get("/api/jobs?sort=oldest&limit=1").json()[0]["id"] == first["id"]
    assert (
        client.get(
            "/api/jobs?sort=oldest&include_storage=true&offset=1&limit=1"
        ).json()[0]["id"]
        == second["id"]
    )
    assert client.get("/api/jobs?sort=invalid").status_code == 422


def test_task_size_cache_ttl_invalidation_and_no_protected_scan(local, monkeypatch):
    from video_intel import storage as storage_module

    job, folder = completed(local)
    original = storage_module.allocated
    scanned = []

    def measure(path):
        assert not any(part in {"models", ".venv", "vendor"} for part in path.parts)
        scanned.append(path)
        return original(path)

    monkeypatch.setattr(storage_module, "allocated", measure)
    initial = local.list(include_storage=True)[0]["storage_bytes"]
    assert scanned
    scanned.clear()
    (folder / "extra.bin").write_bytes(b"x" * 32000)
    for index in range(10):
        local.update(job["id"], durable=False, progress=index)
        assert local.list(include_storage=True)[0]["storage_bytes"] == initial
    assert not scanned
    local.storage.sizes_at -= 61
    assert local.list(include_storage=True)[0]["storage_bytes"] > initial
    scanned.clear()
    local.update(job["id"], status="failed")
    local.list(include_storage=True)
    assert scanned
    local.storage.cleanup([job["id"]], [])
    assert local.storage.task_sizes() == {}


def test_storage_overview_omits_jobs_and_refreshes_shared_sizes(local, client):
    job, folder = completed(local)
    before = local.list(include_storage=True)[0]["storage_bytes"]
    (folder / "extra.bin").write_bytes(b"x" * 32000)
    result = client.get("/api/storage?include_jobs=false&refresh=true").json()
    assert "jobs" not in result
    assert result["cleanable_bytes"] >= 32000
    assert local.list(include_storage=True)[0]["storage_bytes"] > before
    compatible = client.get("/api/storage").json()
    assert compatible["jobs"][0]["id"] == job["id"]
    assert compatible["categories"] == result["categories"]


def test_low_disk_error_has_stable_code(local, client, monkeypatch):
    monkeypatch.setattr(config, "MIN_FREE_BYTES", 10**30)
    result = client.post("/api/jobs", data={"prompt": "A bird"})
    assert result.status_code == 422
    assert result.json()["code"] == "insufficient_storage"
    assert isinstance(result.json()["detail"], str)
    assert local.count() == 0
