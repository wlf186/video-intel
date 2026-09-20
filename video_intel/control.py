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


def ready():
    try:
        response = httpx.get(
            f"http://127.0.0.1:{config.PORT}/api/health", timeout=2, trust_env=False
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
                print(f"Sandevistan Video ready at http://localhost:{config.PORT}")
                return
            time.sleep(1)
        raise SystemExit(
            "Service started but not ready after 120 seconds; inspect logs"
        )
    elif action == "status":
        process = running()
        print(
            json.dumps(
                {
                    "running": bool(process),
                    "pid": process.pid if process else None,
                    "health": ready(),
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
