import re
from pathlib import Path

import pytest

from ado_defect_analysis.config import PROJECT_ROOT, Config

# Every helper in config.py reads env vars through one of these, so scanning for
# them finds the full set without maintaining a duplicate list by hand.
_ENV_READ_PATTERN = re.compile(
    r"""(?:os\.environ\.get|_env_int|_env_list|_env_path)\(\s*["']([A-Z0-9_]+)["']"""
)


def test_env_example_documents_every_setting_config_reads():
    """Guards against .env.example drifting behind Config.from_env().

    The example file is the only documentation of what's configurable, so a
    setting that exists in code but not there is effectively undiscoverable.
    """
    config_source = (PROJECT_ROOT / "src" / "ado_defect_analysis" / "config.py").read_text()
    read_vars = set(_ENV_READ_PATTERN.findall(config_source))

    env_example = (PROJECT_ROOT / ".env.example").read_text()
    documented = {
        line.split("=", 1)[0].strip()
        for line in env_example.splitlines()
        if "=" in line and not line.strip().startswith("#")
    }

    undocumented = read_vars - documented
    assert not undocumented, f".env.example is missing: {sorted(undocumented)}"


def test_relative_db_path_resolves_against_project_root(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEFECT_DB_PATH", "data/custom.db")

    config = Config.from_env()

    assert config.db_path == PROJECT_ROOT / "data" / "custom.db"
    assert config.db_path.is_absolute()


def test_absolute_db_path_is_left_alone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    absolute = tmp_path / "elsewhere.db"
    monkeypatch.setenv("DEFECT_DB_PATH", str(absolute))

    assert Config.from_env().db_path == absolute


def test_rejected_resolutions_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REJECTED_RESOLUTIONS", "Duplicate, Not a Bug")

    assert Config.from_env().rejected_resolutions == ["Duplicate", "Not a Bug"]
