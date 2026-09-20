import io
import time

import pytest
from PIL import Image

from video_intel import service as module
from video_intel.service import JobService


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DATA", tmp_path)
    monkeypatch.setattr(module, "INPUT", tmp_path / "inputs")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "outputs")
    instance = JobService(database=tmp_path / "jobs.sqlite3")
    yield instance
    instance.close()


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (300, 500), (180, 40, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_cancelled_queue_items_do_not_use_capacity(service):
    jobs = [service.submit("A bird flying") for _ in range(9)]
    with pytest.raises(ValueError, match="队列已满"):
        service.submit("A bird flying")
    service.cancel(jobs[0]["id"])
    assert service.submit("A new bird")["status"] == "queued"
    assert service.get(jobs[0]["id"])["status"] == "cancelled"


def test_old_pending_jobs_still_count_after_many_new_cancellations(service):
    for _ in range(8):
        service.submit("A waiting bird")
    for _ in range(25):
        job = service.submit("A cancelled bird")
        service.cancel(job["id"])
    service.submit("The ninth pending bird")
    with pytest.raises(ValueError, match="队列已满"):
        service.submit("Queue must remain bounded")


def test_restart_preserves_queue_and_completed_jobs(service):
    pending = service.submit("Rain on leaves")
    done = service.submit("A quiet river")
    service.update(done["id"], status="succeeded", video_path="/example.mp4")
    reopened = JobService(database=service.database)
    try:
        assert reopened.get(pending["id"])["status"] == "queued"
        assert reopened.get(done["id"])["video_path"] == "/example.mp4"
        assert reopened.cancel(done["id"])["status"] == "succeeded"
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "mode,images", [("t2v", [b"bad"]), ("i2v", []), ("r2v", []), ("r2v", [b"x"] * 4)]
)
def test_mode_and_image_count_are_checked_before_decoding(service, mode, images):
    with pytest.raises(ValueError, match="图片"):
        service.submit("A quiet river", mode=mode, images=images)
    assert not service.list()


def test_invalid_image_is_rejected_without_creating_job(service):
    with pytest.raises(ValueError, match="图片无效"):
        service.submit("A quiet river", mode="i2v", images=[b"not an image"])
    assert not service.list()


def test_first_frame_is_cropped_but_reference_keeps_aspect_ratio(service):
    first = service.submit(
        "A moving toy", mode="i2v", preset="preview", images=[png()], seed=42
    )
    reference = service.submit("A moving toy", mode="r2v", images=[png()], seed=42)
    with Image.open(module.INPUT / first["images"][0]) as image:
        assert image.size == (608, 352)
    with Image.open(module.INPUT / reference["images"][0]) as image:
        assert image.size == (300, 500)
    assert first["seed"] == reference["seed"] == 42


def test_running_cancellation_does_not_mark_job_finished_before_backend_ack(service):
    item = service.submit("A rolling toy")
    service.update(item["id"], status="running")
    result = service.cancel(item["id"])
    assert result["cancel_requested"] is True
    assert result["status"] == "running"
    assert result["finished_at"] is None


@pytest.mark.parametrize("seed", [-2, 2**32, 1.5])
def test_invalid_seed_is_rejected(service, seed):
    with pytest.raises(ValueError, match="随机种子"):
        service.submit("A toy", seed=seed)


def test_failed_generation_does_not_stop_the_worker(service, monkeypatch):
    monkeypatch.setattr(module, "models_ready", lambda mode: True)
    monkeypatch.setattr(service, "backend_ready", lambda: True)
    monkeypatch.setattr(service.client, "post", lambda *args, **kwargs: None)
    failed = service.submit("first")
    following = service.submit("second")

    def execute(item, recovering=False):
        if item["id"] == failed["id"]:
            raise RuntimeError("Simulated inference error")
        service.update(item["id"], status="succeeded")

    monkeypatch.setattr(service, "execute", execute)
    service.start()
    deadline = time.monotonic() + 3
    while (
        time.monotonic() < deadline
        and service.get(following["id"])["status"] != "succeeded"
    ):
        time.sleep(0.01)
    assert service.get(failed["id"])["status"] == "failed"
    assert service.get(following["id"])["status"] == "succeeded"
    assert service.thread.is_alive()
