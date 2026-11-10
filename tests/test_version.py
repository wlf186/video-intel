"""Published tags, API metadata and frontend packages share one release version."""

import json
import os
from pathlib import Path

from video_intel.config import VERSION


def test_frontend_and_api_release_versions_match():
    root = Path(__file__).resolve().parents[1]
    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    assert package["version"] == VERSION


def test_release_tag_matches_api_version():
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        assert os.environ["GITHUB_REF_NAME"] == f"v{VERSION}"
