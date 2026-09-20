"""Audit locks and bootstrap tools; fail closed on skipped packages or stale VEX."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from bootstrap_tools import ROOT, VERSIONS


def read_pins(path):
    pins = {}
    for line in path.read_text().splitlines():
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^ ;\\]+)(?:\s+\\)?", line)
        if not match:
            raise ValueError(f"Non-pinned dependency in {path.name}: {line}")
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        if name in pins and pins[name] != match[2]:
            raise ValueError(f"Conflicting pin: {name}")
        pins[name] = match[2]
    if not pins:
        raise ValueError(f"Empty lock: {path}")
    return pins


def audit_version(name, version):
    # The official CUDA wheels share the upstream release's advisory identity.
    if name in {"torch", "torchvision", "torchaudio"} and version.endswith("+cu130"):
        return version.removesuffix("+cu130")
    if "+" in version:
        raise ValueError(f"Unmapped local distribution: {name}=={version}")
    return version


def apply_exceptions(dependencies, pins, exceptions, *, today=None):
    today = today or datetime.now(timezone.utc).date()
    for item in exceptions:
        if not item["reason"] or not item["evidence"]:
            raise ValueError("An exception requires rationale and evidence")
        if date.fromisoformat(item["review_after"]) <= today:
            raise ValueError(f"Expired exception: {item['ids']}")
        if pins.get(item["package"]) != item["version"]:
            raise ValueError(f"Exception version differs from lock: {item['package']}")
    accepted, rejected, used = [], [], set()
    for dep in dependencies:
        if "skip_reason" in dep:
            raise ValueError(
                f"Unaudited dependency: {dep['name']}: {dep['skip_reason']}"
            )
        name = dep["name"]
        if name not in pins or dep["version"] != audit_version(name, pins[name]):
            raise ValueError(f"Audit result does not match requested pin: {name}")
        for vuln in dep.get("vulns", []):
            ids = {vuln["id"], *vuln.get("aliases", [])}
            item = {
                "package": name,
                "installed_version": pins[name],
                "queried_version": dep["version"],
                "advisory": vuln,
            }
            matches = [
                i
                for i, e in enumerate(exceptions)
                if e["package"] == name and ids.intersection(e["ids"])
            ]
            if matches:
                used.update(matches)
                item["exception"] = exceptions[matches[0]]
                accepted.append(item)
            else:
                rejected.append(item)
    if {d["name"] for d in dependencies} != set(pins):
        raise ValueError("Audit omitted dependencies")
    if used != set(range(len(exceptions))):
        raise ValueError(
            "Stale exception no longer matches an advisory; remove/review it"
        )
    return accepted, rejected


def check_evidence(exceptions):
    from download_models import REVISION

    for item in exceptions:
        if (
            item["comfyui_commit"] != VERSIONS["comfyui_commit"]
            or item["model_revision"] != REVISION
        ):
            raise ValueError("Inference stack changed; reassess dependency exceptions")
        for path in item["evidence"]:
            if not (ROOT / path).is_file():
                raise ValueError(f"Missing exception evidence: {path}")


def run_json(command):
    result = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=False
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr or result.stdout)
    try:
        data = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError(result.stderr or result.stdout) from error
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data, result.returncode


def audit_python(pins):
    (ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="audit-", dir=ROOT / "tmp") as folder:
        normalized = Path(folder) / "requirements.txt"
        normalized.write_text(
            "".join(f"{n}=={audit_version(n, v)}\n" for n, v in sorted(pins.items()))
        )
        data, code = run_json(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "--no-deps",
                "--disable-pip",
                "--vulnerability-service",
                "osv",
                "--format",
                "json",
                "--progress-spinner",
                "off",
                "-r",
                str(normalized),
            ]
        )
    if "dependencies" not in data or (
        code and not any(d.get("vulns") for d in data["dependencies"])
    ):
        raise RuntimeError(
            "Python audit failed without a complete vulnerability report"
        )
    return data["dependencies"]


def audit_tools():
    payload = json.dumps({"pnpm": [VERSIONS["pnpm"]]}).encode()
    request = urllib.request.Request(
        "https://registry.npmjs.org/-/npm/v1/security/advisories/bulk",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        data = json.load(response)
    if not isinstance(data, dict) or any(
        not isinstance(v, list) for v in data.values()
    ):
        raise ValueError("Invalid tool audit response")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "tmp/dependency-audit.json"
    )
    args = parser.parse_args()
    report = {"status": "failed", "date": datetime.now(timezone.utc).date().isoformat()}
    try:
        pins = read_pins(ROOT / "requirements.lock")
        for name, version in read_pins(ROOT / "requirements-ci.lock").items():
            if name in pins and pins[name] != version:
                raise ValueError(f"CI/runtime dependency drift: {name}")
            pins[name] = version
        pins["uv"] = VERSIONS["uv"]
        exceptions = json.loads((ROOT / "docs/dependency-exceptions.json").read_text())
        check_evidence(exceptions)
        deps = audit_python(pins)
        accepted, rejected = apply_exceptions(deps, pins, exceptions)
        report.update(python=deps, accepted=accepted, rejected=rejected)
        frontend, code = run_json([str(ROOT / "scripts/pnpm.sh"), "audit", "--json"])
        counts = frontend.get("metadata", {}).get("vulnerabilities")
        if (
            not isinstance(counts, dict)
            or not counts
            or (code and not any(counts.values()))
        ):
            raise ValueError("Incomplete frontend audit")
        report["frontend"] = frontend
        report["tools"] = audit_tools()
        if rejected or any(counts.values()) or report["tools"]:
            raise ValueError("Unaccepted dependency vulnerabilities found")
        report["status"] = "passed_with_documented_exceptions" if accepted else "passed"
        print(
            f"Audited {len(pins)} Python packages and frontend/tool dependencies; "
            f"{len(exceptions)} documented exceptions, no unaccepted findings"
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if report["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    os.environ.setdefault("PIP_CACHE_DIR", str(ROOT / "cache/pip"))
    main()
