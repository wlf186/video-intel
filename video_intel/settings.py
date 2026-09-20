"""Small, data-only deployment settings reader; never evaluates shell code."""

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """A deployment setting cannot safely be used to start the service."""


DEFAULTS = {
    "VIDEO_INTEL_HOST": "0.0.0.0",
    "VIDEO_INTEL_PORT": "20820",
    "VIDEO_INTEL_BACKEND_PORT": "8188",
    "VIDEO_INTEL_MIN_FREE_BYTES": str(5 * 1024**3),
}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    backend_port: int
    min_free_bytes: int

    def environment(self):
        # Children, including supervised replacements, inherit this snapshot.
        return {
            "VIDEO_INTEL_HOST": self.host,
            "VIDEO_INTEL_PORT": str(self.port),
            "VIDEO_INTEL_BACKEND_PORT": str(self.backend_port),
            "VIDEO_INTEL_MIN_FREE_BYTES": str(self.min_free_bytes),
            "VIDEO_INTEL_LOAD_ENV": "0",
        }


def load_settings(root: Path, environ=None):
    environ = os.environ if environ is None else environ
    values = dict(DEFAULTS)
    origins = {key: "default" for key in DEFAULTS}
    path = root / ".env"
    if environ.get("VIDEO_INTEL_LOAD_ENV") != "0":
        try:
            content = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            content = ""
        except (OSError, UnicodeError) as exc:
            raise ConfigurationError(f"Cannot read {path}") from exc
        for number, line in enumerate(content.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(
                r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line
            )
            if not match:
                raise ConfigurationError(f"{path}:{number}: expected KEY=value")
            key, raw = match.groups()
            if key not in DEFAULTS:
                continue
            try:
                parts = shlex.split(raw, comments=True, posix=True)
            except ValueError as exc:
                raise ConfigurationError(
                    f"{path}:{number}: invalid quoting for {key}"
                ) from exc
            if len(parts) > 1:
                raise ConfigurationError(
                    f"{path}:{number}: expected one value for {key}"
                )
            values[key] = parts[0] if parts else ""
            origins[key] = f"{path}:{number}"
    for key in DEFAULTS:
        if key in environ:
            values[key] = environ[key]
            origins[key] = "environment"

    def invalid(key, reason):
        raise ConfigurationError(f"{origins[key]}: {key} {reason}")

    host = values["VIDEO_INTEL_HOST"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", host):
        invalid("VIDEO_INTEL_HOST", "must be an IPv4 address or hostname")
    numbers = {}
    for key in DEFAULTS.keys() - {"VIDEO_INTEL_HOST"}:
        value = values[key]
        if not re.fullmatch(r"[0-9]+", value):
            invalid(key, "must be an integer")
        try:
            numbers[key] = int(value)
        except ValueError:
            invalid(key, "must be a valid integer")
        if key.endswith("PORT") and not 1 <= numbers[key] <= 65535:
            invalid(key, "must be between 1 and 65535")
    if numbers["VIDEO_INTEL_PORT"] == numbers["VIDEO_INTEL_BACKEND_PORT"]:
        invalid(
            "VIDEO_INTEL_PORT",
            f"must differ from VIDEO_INTEL_BACKEND_PORT ({origins['VIDEO_INTEL_BACKEND_PORT']})",
        )
    return Settings(
        host,
        numbers["VIDEO_INTEL_PORT"],
        numbers["VIDEO_INTEL_BACKEND_PORT"],
        numbers["VIDEO_INTEL_MIN_FREE_BYTES"],
    )
