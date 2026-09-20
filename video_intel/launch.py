"""Bounded supervision with project-local caches and rotating child logs."""

import fcntl
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import psutil

from . import config
from .process_identity import token


def logger(name):
    result = logging.getLogger("service." + name)
    result.setLevel(logging.INFO)
    if result.handlers:
        return result
    handler = RotatingFileHandler(
        config.LOGS / f"{name}.log",
        maxBytes=5 * 1024**2,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    result.addHandler(handler)
    return result


def identity(name, pid):
    process = psutil.Process(pid)
    (config.RUN / f"{name}.pid").write_text(str(pid))
    (config.RUN / f"{name}.identity.json").write_text(
        json.dumps(
            {
                "pid": pid,
                "created": process.create_time(),
                "command": process.cmdline(),
                **(
                    {"settings": config.settings().environment()}
                    if name == "supervisor"
                    else {}
                ),
                **token(pid),
            }
        )
    )


def drain(pipe, log):
    for line in iter(pipe.readline, ""):
        line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        if "\r" in line:
            line = line.split("\r")[-1]
        if line:
            log.info(line[:16000])
    pipe.close()


def stop_tree(process, timeout):
    if process.poll() is not None:
        return
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        parent.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            parent.kill()
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(children, timeout=3)
        for child in alive:
            child.kill()
        process.wait(timeout=5)
    except psutil.NoSuchProcess:
        pass


def main():
    config.settings()
    for path in (
        config.RUN,
        config.LOGS,
        config.DATA / "inputs",
        config.DATA / "outputs",
        config.DATA / "comfy-user",
    ):
        path.mkdir(parents=True, exist_ok=True)
    with (config.RUN / "service.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Service already running")
        for host, port in [
            ("127.0.0.1", config.BACKEND_PORT),
            (config.HOST, config.PORT),
        ]:
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind((host, port))
        env = config.runtime_environment()
        model_config = config.RUN / "model_paths.yaml"
        desired = f"video_intel:\n  base_path: {config.ROOT / 'models'}\n  diffusion_models: diffusion_models\n  text_encoders: text_encoders\n  vae: vae\n"
        if not model_config.exists() or model_config.read_text() != desired:
            model_config.write_text(desired)
        commands = {
            "backend": [
                sys.executable,
                "vendor/ComfyUI/main.py",
                "--listen",
                "127.0.0.1",
                "--port",
                str(config.BACKEND_PORT),
                "--extra-model-paths-config",
                str(model_config),
                "--input-directory",
                str(config.DATA / "inputs"),
                "--output-directory",
                str(config.DATA / "outputs"),
                "--user-directory",
                str(config.DATA / "comfy-user"),
                "--database-url",
                "sqlite:///:memory:",
                "--temp-directory",
                str(config.TMP / "comfy"),
                "--enable-dynamic-vram",
                "--fast-disk",
                "--disable-pinned-memory",
                "--reserve-vram",
                "3",
                "--cache-none",
                "--disable-api-nodes",
                "--disable-auto-launch",
                "--preview-method",
                "none",
            ],
            "web": [
                sys.executable,
                "-m",
                "uvicorn",
                "video_intel.app:app",
                "--host",
                config.HOST,
                "--port",
                str(config.PORT),
                "--workers",
                "1",
                "--no-access-log",
                "--timeout-graceful-shutdown",
                "15",
            ],
        }
        stopped = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stopped.set())
        signal.signal(signal.SIGINT, lambda *_: stopped.set())
        log = logger("supervisor")
        processes, since = {}, {}
        failures = {key: 0 for key in commands}
        identity("supervisor", os.getpid())
        try:
            while not stopped.is_set():
                for name, command in commands.items():
                    if name in processes and processes[name].poll() is None:
                        if time.monotonic() - since[name] > 300:
                            failures[name] = 0
                        continue
                    if name in processes:
                        failures[name] += 1
                        log.error(
                            "%s exited (%s), failure %s/5",
                            name,
                            processes[name].returncode,
                            failures[name],
                        )
                        if failures[name] >= 5:
                            raise RuntimeError(
                                f"{name} repeatedly failed; manual restart required"
                            )
                        if stopped.wait(min(2 ** failures[name], 16)):
                            break
                    process = subprocess.Popen(
                        command,
                        cwd=config.ROOT,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        errors="replace",
                        bufsize=1,
                    )
                    processes[name] = process
                    since[name] = time.monotonic()
                    identity(name, process.pid)
                    threading.Thread(
                        target=drain,
                        args=(
                            process.stdout,
                            logger("comfy" if name == "backend" else "web"),
                        ),
                        daemon=True,
                    ).start()
                    log.info("Started %s PID %s", name, process.pid)
                stopped.wait(1)
        finally:
            # Let the web worker checkpoint/detach before the backend exits.
            for name in ("web", "backend"):
                if name in processes:
                    stop_tree(processes[name], 20)
            for name in ("supervisor", "web", "backend"):
                (config.RUN / f"{name}.pid").unlink(missing_ok=True)
                (config.RUN / f"{name}.identity.json").unlink(missing_ok=True)
            log.info("Service stopped")


if __name__ == "__main__":
    main()
