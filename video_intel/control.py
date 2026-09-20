"""Foreground/background entrypoints, with PID identity checks."""

import json
import os
import signal
import subprocess
import sys
import time

import httpx
import psutil

from . import config
from .process_identity import token
from .settings import ConfigurationError, load_settings


def running():
    try:
        meta = json.loads((config.RUN / "supervisor.identity.json").read_text())
        process = psutil.Process(meta["pid"])
        if (
            all(meta.get(key) == value for key, value in token(process.pid).items())
            and "video_intel.launch" in process.cmdline()
        ):
            return process
    except (OSError, ValueError, KeyError, psutil.Error):
        pass
    return None


def running_endpoint(process):
    """Read the actual web arguments, only for our identity-checked child."""
    if process is None:
        return None
    try:
        meta = json.loads((config.RUN / "web.identity.json").read_text())
        web = psutil.Process(meta["pid"])
        expected = token(web.pid)
        if not all(meta.get(k) == v for k, v in expected.items()):
            return None
        if web.ppid() != process.pid or web.status() == psutil.STATUS_ZOMBIE:
            return None
        command = web.cmdline()
        if "video_intel.app:app" not in command:
            return None
        host = command[command.index("--host") + 1]
        port = int(command[command.index("--port") + 1])
        if not 1 <= port <= 65535 or token(web.pid) != expected:
            return None
        return host, port
    except (OSError, ValueError, KeyError, IndexError, psutil.Error):
        return None


def running_settings(process, endpoint):
    try:
        meta = json.loads((config.RUN / "supervisor.identity.json").read_text())
        if meta["pid"] != process.pid or not all(
            meta.get(k) == v for k, v in token(process.pid).items()
        ):
            return None
        # Older supervisors have no snapshot. Their environment plus the actual
        # web arguments preserves compatibility without reading the edited .env.
        environment = dict(
            meta["settings"] if "settings" in meta else process.environ()
        )
        environment["VIDEO_INTEL_LOAD_ENV"] = "0"
        if endpoint:
            environment.update(
                VIDEO_INTEL_HOST=endpoint[0], VIDEO_INTEL_PORT=str(endpoint[1])
            )
        return load_settings(config.ROOT, environment)
    except (OSError, ValueError, KeyError, psutil.Error):
        return None


def endpoint_url(endpoint):
    host, port = endpoint
    return f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"


def ready(endpoint=None):
    if endpoint is None:
        endpoint = running_endpoint(running())
    if endpoint is None:
        return None
    try:
        response = httpx.get(
            f"{endpoint_url(endpoint)}/api/health", timeout=2, trust_env=False
        )
        return response.json() if response.is_success else None
    except (httpx.HTTPError, ValueError):
        return None


def stop():
    process = running()
    if not process:
        print("Service is stopped")
        return
    try:
        expected = token(process.pid)
        os.kill(process.pid, signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError):
        print("Service stopped")
        return
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if (
                token(process.pid) != expected
                or process.status() == psutil.STATUS_ZOMBIE
            ):
                break
        except (OSError, psutil.NoSuchProcess):
            break
        time.sleep(0.25)
    else:
        raise SystemExit("Shutdown still running; inspect logs/supervisor.log")
    print("Service stopped")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action in {"start", "restart", "run"}:
        try:
            config.configure(load_settings(config.ROOT))
        except ConfigurationError as exc:
            raise SystemExit(str(exc)) from exc
    config.RUN.mkdir(exist_ok=True)
    config.LOGS.mkdir(exist_ok=True)
    if action == "run":
        from .launch import main as launch

        launch()
    elif action == "stop":
        stop()
    elif action in {"start", "restart"}:
        if action == "restart":
            stop()
        if running():
            print("Already running")
            return
        with (config.LOGS / "bootstrap.log").open("w") as output:
            child = subprocess.Popen(
                [sys.executable, "-m", "video_intel.launch"],
                cwd=config.ROOT,
                env=config.runtime_environment(),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise SystemExit(
                    "Startup failed; inspect logs/bootstrap.log and logs/supervisor.log"
                )
            health = ready()
            if health and health["status"] == "ready" and health["worker_alive"]:
                print(
                    f"Sandevistan Video ready at {endpoint_url((config.HOST, config.PORT))} (listen {config.HOST}:{config.PORT})"
                )
                return
            time.sleep(1)
        raise SystemExit(
            "Service started but not ready after 120 seconds; inspect logs"
        )
    elif action == "status":
        process = running()
        endpoint = running_endpoint(process)
        configuration_error, desired = None, None
        try:
            desired = load_settings(config.ROOT)
        except ConfigurationError as exc:
            configuration_error = str(exc)
        active = running_settings(process, endpoint) if process else None
        print(
            json.dumps(
                {
                    "running": bool(process),
                    "pid": process.pid if process else None,
                    "health": ready(endpoint) if endpoint else None,
                    "endpoint": f"{endpoint[0]}:{endpoint[1]}" if endpoint else None,
                    "configured_endpoint": f"{desired.host}:{desired.port}"
                    if desired
                    else None,
                    "restart_required": active != desired
                    if active and desired
                    else None,
                    "configuration_error": configuration_error,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif action == "logs":
        name = sys.argv[2] if len(sys.argv) > 2 else "supervisor"
        if name not in {"supervisor", "web", "comfy", "bootstrap"}:
            raise SystemExit("Choose supervisor, web, comfy, or bootstrap")
        subprocess.run(
            ["tail", "-n", "80", "-f", str(config.LOGS / f"{name}.log")], check=False
        )
    else:
        raise SystemExit(
            "Usage: service.sh start|stop|restart|status|logs [web|comfy]|run"
        )


if __name__ == "__main__":
    main()
