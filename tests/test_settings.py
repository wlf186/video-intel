import json
import os
from unittest.mock import Mock

import pytest

from video_intel import config, control
from video_intel.settings import ConfigurationError, Settings, load_settings


def test_defaults_and_file_precedence(tmp_path):
    assert load_settings(tmp_path, {}) == Settings("0.0.0.0", 20820, 8188, 5 * 1024**3)
    (tmp_path / ".env").write_text(
        '\ufeff# deployment\nexport VIDEO_INTEL_HOST="127.0.0.1"\r\n'
        "VIDEO_INTEL_PORT = '20821' # web\nVIDEO_INTEL_MIN_FREE_BYTES=0\n"
        "IGNORED_TOKEN=secret\n"
    )
    settings = load_settings(tmp_path, {"VIDEO_INTEL_PORT": "20822"})
    assert settings == Settings("127.0.0.1", 20822, 8188, 0)
    assert "IGNORED_TOKEN" not in settings.environment()


@pytest.mark.parametrize(
    "entry",
    [
        "VIDEO_INTEL_PORT=0",
        "VIDEO_INTEL_PORT=65536",
        "VIDEO_INTEL_PORT=-1",
        "VIDEO_INTEL_PORT=abc",
        "VIDEO_INTEL_PORT=",
        "VIDEO_INTEL_PORT=8188",
        "VIDEO_INTEL_BACKEND_PORT=20820",
        "VIDEO_INTEL_MIN_FREE_BYTES=-1",
        "VIDEO_INTEL_HOST=",
        "VIDEO_INTEL_HOST=http://localhost",
        'VIDEO_INTEL_PORT="20821',
        "VIDEO_INTEL_PORT=20821 extra",
        "not an assignment",
    ],
)
def test_invalid_file_reports_location(tmp_path, entry):
    (tmp_path / ".env").write_text("# heading\n" + entry)
    with pytest.raises(ConfigurationError, match=r"\.env:2"):
        load_settings(tmp_path, {})


def test_invalid_environment_reports_key(tmp_path):
    with pytest.raises(ConfigurationError, match="environment: VIDEO_INTEL_PORT"):
        load_settings(tmp_path, {"VIDEO_INTEL_PORT": "bad"})


@pytest.mark.parametrize(
    "expression", ["$(touch SENTINEL)", "`touch SENTINEL`", "${PORT}"]
)
def test_values_are_never_executed_or_expanded(tmp_path, monkeypatch, expression):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PORT", "20821")
    (tmp_path / ".env").write_text(f"VIDEO_INTEL_PORT='{expression}'")
    with pytest.raises(ConfigurationError):
        load_settings(tmp_path, {})
    assert not (tmp_path / "SENTINEL").exists()


def test_child_environment_keeps_snapshot_after_file_corruption(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("VIDEO_INTEL_PORT=20821")
    settings = load_settings(tmp_path, {})
    monkeypatch.setattr(config, "_settings", settings)
    for name in ["TMP", "CACHE"]:
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    child_env = config.runtime_environment()
    (tmp_path / ".env").write_text("invalid syntax")
    assert load_settings(tmp_path, child_env) == settings
    assert child_env["VIDEO_INTEL_PORT"] == "20821"


@pytest.fixture
def management(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "RUN", tmp_path / "run")
    monkeypatch.setattr(config, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(config, "_settings", None)
    for key in [*Settings("0.0.0.0", 20820, 8188, 0).environment()]:
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def test_bad_restart_never_stops_existing_service(management, monkeypatch):
    (management / ".env").write_text("VIDEO_INTEL_PORT=invalid")
    stop = Mock()
    monkeypatch.setattr(control, "stop", stop)
    monkeypatch.setattr(control.sys, "argv", ["service.sh", "restart"])
    with pytest.raises(SystemExit, match="VIDEO_INTEL_PORT"):
        control.main()
    stop.assert_not_called()


@pytest.mark.parametrize("action", ["stop", "logs"])
def test_bad_file_does_not_block_management(management, monkeypatch, action):
    (management / ".env").write_text('VIDEO_INTEL_PORT="broken')
    operation = Mock()
    monkeypatch.setattr(control, "stop", operation)
    monkeypatch.setattr(control.subprocess, "run", operation)
    monkeypatch.setattr(control.sys, "argv", ["service.sh", action])
    control.main()
    operation.assert_called_once()


@pytest.mark.parametrize(
    "content,changed", [("VIDEO_INTEL_PORT=20822", True), ("broken", None)]
)
def test_status_uses_running_endpoint_after_edit(
    management, monkeypatch, capsys, content, changed
):
    (management / ".env").write_text(content)
    monkeypatch.setattr(control.sys, "argv", ["service.sh", "status"])
    monkeypatch.setattr(control, "running", lambda: Mock(pid=123))
    monkeypatch.setattr(control, "running_endpoint", lambda _: ("127.0.0.2", 20821))
    monkeypatch.setattr(
        control,
        "running_settings",
        lambda *_: Settings("127.0.0.2", 20821, 8188, 5 * 1024**3),
    )
    get = Mock(return_value=Mock(is_success=True, json=lambda: {"status": "ready"}))
    monkeypatch.setattr(control.httpx, "get", get)
    control.main()
    result = json.loads(capsys.readouterr().out)
    assert result["endpoint"] == "127.0.0.2:20821"
    assert result["health"]["status"] == "ready"
    assert result["restart_required"] == changed
    assert bool(result["configuration_error"]) == (changed is None)
    assert get.call_args.args[0] == "http://127.0.0.2:20821/api/health"


def test_stopped_status_does_not_probe_unowned_port(management, monkeypatch, capsys):
    monkeypatch.setattr(control.sys, "argv", ["service.sh", "status"])
    monkeypatch.setattr(control, "running", lambda: None)
    get = Mock()
    monkeypatch.setattr(control.httpx, "get", get)
    control.main()
    assert json.loads(capsys.readouterr().out)["health"] is None
    get.assert_not_called()


def test_endpoint_checks_identity_and_parent(management, monkeypatch):
    config.RUN.mkdir()
    identity = {"boot_id": "boot", "start_ticks": "123"}
    meta = {"pid": 234, **identity}
    (config.RUN / "web.identity.json").write_text(json.dumps(meta))
    web = Mock(
        pid=234,
        ppid=lambda: 123,
        cmdline=lambda: [
            "python",
            "-m",
            "uvicorn",
            "video_intel.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "20821",
        ],
    )
    monkeypatch.setattr(control.psutil, "Process", lambda _: web)
    monkeypatch.setattr(control, "token", lambda _: identity)
    assert control.running_endpoint(Mock(pid=123)) == ("0.0.0.0", 20821)
    assert control.running_endpoint(Mock(pid=999)) is None
    monkeypatch.setattr(control, "token", lambda _: {**identity, "start_ticks": "new"})
    assert control.running_endpoint(Mock(pid=123)) is None


def test_running_snapshot_and_legacy_environment(management, monkeypatch):
    config.RUN.mkdir()
    identity = {"boot_id": "boot", "start_ticks": "123"}
    monkeypatch.setattr(control, "token", lambda _: identity)
    process = Mock(
        pid=os.getpid(), environ=lambda: {"VIDEO_INTEL_BACKEND_PORT": "8189"}
    )
    p = config.RUN / "supervisor.identity.json"
    meta = {"pid": process.pid, **identity}
    p.write_text(json.dumps(meta))
    assert control.running_settings(process, ("0.0.0.0", 20821)).backend_port == 8189
    settings = Settings("0.0.0.0", 20821, 8190, 0)
    p.write_text(json.dumps({**meta, "settings": settings.environment()}))
    (management / ".env").write_text("broken")
    assert control.running_settings(process, ("0.0.0.0", 20821)) == settings
    p.write_text(json.dumps({**meta, "start_ticks": "stale"}))
    assert control.running_settings(process, ("0.0.0.0", 20821)) is None
