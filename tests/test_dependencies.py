import hashlib
import io
import json
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

import audit_dependencies as audit
import bootstrap_tools as bootstrap
import lock_dependencies as locks
import pytest
import sync_environment as sync


def test_download_rejects_corrupt_bytes(monkeypatch):
    monkeypatch.setattr(
        bootstrap.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"altered")
    )
    with pytest.raises(ValueError, match="Checksum"):
        bootstrap.verified_download(
            "https://example.test/tool",
            "sha256",
            hashlib.sha256(b"original").hexdigest(),
        )


def test_missing_lock_never_runs_installer(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail("Missing lock must fail before downloading or installing tools")

    monkeypatch.setattr(sync, "ensure_uv", forbidden)
    with pytest.raises(FileNotFoundError, match="refusing"):
        sync.sync_environment(tmp_path / "python", tmp_path / "missing.lock")


def test_real_installer_rejects_wrong_hash_and_removes_unlocked_packages(tmp_path):
    uv = bootstrap.ensure_uv()
    env = tmp_path / "env"
    subprocess.run([str(uv), "venv", "--python", sys.executable, str(env)], check=True)
    wheels = []
    for name in ["locked_fixture", "unlocked_fixture"]:
        wheel = tmp_path / f"{name}-1.0-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            prefix = f"{name}-1.0.dist-info"
            archive.writestr(f"{name}.py", "VALUE = 1\n")
            archive.writestr(
                f"{prefix}/METADATA",
                f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n",
            )
            archive.writestr(
                f"{prefix}/WHEEL",
                "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            )
            archive.writestr(f"{prefix}/RECORD", "")
        wheels.append(wheel)
    lock = tmp_path / "fixture.lock"
    lock.write_text(f"locked-fixture @ {wheels[0].as_uri()} --hash=sha256:{'0' * 64}\n")
    python = env / "bin/python"
    with pytest.raises(subprocess.CalledProcessError):
        sync.sync_environment(python, lock, full=False)
    digest = hashlib.sha256(wheels[0].read_bytes()).hexdigest()
    lock.write_text(f"locked-fixture @ {wheels[0].as_uri()} --hash=sha256:{digest}\n")
    subprocess.run(
        [str(uv), "pip", "install", "--python", str(python), str(wheels[1])], check=True
    )
    sync.sync_environment(python, lock, full=False)
    subprocess.run(
        [
            str(python),
            "-c",
            (
                "import importlib.util; import locked_fixture; "
                "assert importlib.util.find_spec('unlocked_fixture') is None"
            ),
        ],
        check=True,
    )


def test_cuda_audit_identity_and_unknown_local_version():
    assert audit.audit_version("torch", "2.10.0+cu130") == "2.10.0"
    with pytest.raises(ValueError, match="Unmapped"):
        audit.audit_version("example", "1.0+private")


def exception():
    return {
        "package": "torch",
        "version": "2.10.0+cu130",
        "ids": ["CVE-known"],
        "review_after": "2099-01-01",
        "reason": "Test evidence",
        "evidence": ["test.py"],
    }


def test_audit_only_accepts_exact_documented_advisory():
    deps = [
        {
            "name": "torch",
            "version": "2.10.0",
            "vulns": [
                {"id": "GHSA-known", "aliases": ["CVE-known"]},
                {"id": "CVE-new"},
            ],
        }
    ]
    accepted, rejected = audit.apply_exceptions(
        deps, {"torch": "2.10.0+cu130"}, [exception()]
    )
    assert len(accepted) == 1 and rejected[0]["advisory"]["id"] == "CVE-new"


@pytest.mark.parametrize(
    "deps,message",
    [
        ([{"name": "torch", "skip_reason": "not on PyPI"}], "Unaudited"),
        ([], "omitted"),
        ([{"name": "torch", "version": "2.9.0", "vulns": []}], "does not match"),
        ([{"name": "torch", "version": "2.10.0", "vulns": []}], "Stale"),
    ],
)
def test_incomplete_audit_and_stale_exception_fail(deps, message):
    with pytest.raises(ValueError, match=message):
        audit.apply_exceptions(deps, {"torch": "2.10.0+cu130"}, [exception()])


def test_expired_or_changed_exception_fails():
    item = exception()
    with pytest.raises(ValueError, match="Expired"):
        audit.apply_exceptions(
            [], {"torch": item["version"]}, [item], today=date(2099, 1, 1)
        )
    with pytest.raises(ValueError, match="version differs"):
        audit.apply_exceptions([], {"torch": "2.11.0+cu130"}, [item])


@pytest.mark.parametrize("output", ["not JSON", '{"error":"registry offline"}'])
def test_audit_network_error_is_not_success(monkeypatch, output):
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 1, output, ""),
    )
    with pytest.raises(RuntimeError):
        audit.run_json(["audit"])


def test_lock_check_does_not_mutate_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, "ROOT", tmp_path)
    monkeypatch.setattr(locks, "LOCKS", {"requirements.lock": ["requirements.in"]})
    monkeypatch.setattr(locks, "validate_comfy_requirements", lambda: None)
    monkeypatch.setattr(locks, "ensure_uv", lambda: Path("uv"))
    original = "example==1.0\n"
    destination = tmp_path / "requirements.lock"
    destination.write_text(original)

    def compile_candidate(uv, name, sources, output, upgrade):
        assert output.read_text() == original  # Existing versions seed resolution.
        assert not upgrade
        output.write_text("example==2.0\n")

    monkeypatch.setattr(locks, "compile_lock", compile_candidate)
    monkeypatch.setattr(sys, "argv", ["lock_dependencies.py", "--check"])
    with pytest.raises(SystemExit, match="stale"):
        locks.main()
    assert destination.read_text() == original


def test_model_workflow_does_not_accept_checkpoint_or_python_input():
    from video_intel.workflows import AUDIO_VAE, ENCODER, MODELS, VIDEO_VAE

    assert all(
        name.endswith(".safetensors")
        for name in [*MODELS.values(), ENCODER, VIDEO_VAE, AUDIO_VAE]
    )
    audit.check_evidence(
        json.loads((bootstrap.ROOT / "docs/dependency-exceptions.json").read_text())
    )


def test_tool_versions_and_python_locks_agree():
    full = audit.read_pins(bootstrap.ROOT / "requirements.lock")
    ci = audit.read_pins(bootstrap.ROOT / "requirements-ci.lock")
    assert all(full.get(name) == version for name, version in ci.items())
    package = json.loads((bootstrap.ROOT / "frontend/package.json").read_text())
    assert package["packageManager"] == f"pnpm@{bootstrap.VERSIONS['pnpm']}"
    assert full["pip-audit"] == bootstrap.VERSIONS["pip-audit"]
