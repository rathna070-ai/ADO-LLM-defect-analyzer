"""Environment-driven configuration for the ADO defect analysis pipeline.

Every setting has a sane default except credentials. Nothing here talks to a
network or a file on import — call `Config.from_env()` explicitly so tests
can construct a `Config` without touching `.env` at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class AdoConfig:
    organization: str = ""
    project: str = ""
    pat: str = ""
    api_version: str = "7.1"
    work_item_type: str = "Bug"
    area_path: str = ""
    lookback_days: int = 180
    root_cause_field: str = "Microsoft.VSTS.CMMI.RootCause"
    batch_size: int = 200
    fetch_comments: bool = False

    @property
    def base_url(self) -> str:
        return f"https://dev.azure.com/{self.organization}/{self.project}/_apis"


@dataclass
class LlmConfig:
    provider: str = "groq"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    copilot_api_key: str = ""
    copilot_model: str = ""
    request_timeout_seconds: int = 60
    temperature: float = 0.0
    max_tokens: int = 2048
    categorize_batch_size: int = 10


@dataclass
class Config:
    ado: AdoConfig = field(default_factory=AdoConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    db_path: Path = PROJECT_ROOT / "data" / "defects.db"
    output_dir: Path = PROJECT_ROOT / "data" / "exports"

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config from process environment variables (loads .env if present)."""
        try:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env")
        except ImportError:
            pass

        ado = AdoConfig(
            organization=os.environ.get("ADO_ORGANIZATION", ""),
            project=os.environ.get("ADO_PROJECT", ""),
            pat=os.environ.get("ADO_PAT", ""),
            api_version=os.environ.get("ADO_API_VERSION", "7.1"),
            work_item_type=os.environ.get("ADO_WORK_ITEM_TYPE", "Bug"),
            area_path=os.environ.get("ADO_AREA_PATH", ""),
            lookback_days=_env_int("ADO_LOOKBACK_DAYS", 180),
            root_cause_field=os.environ.get(
                "ADO_ROOT_CAUSE_FIELD", "Microsoft.VSTS.CMMI.RootCause"
            ),
            batch_size=_env_int("ADO_BATCH_SIZE", 200),
            fetch_comments=os.environ.get("ADO_FETCH_COMMENTS", "false").lower() == "true",
        )
        llm = LlmConfig(
            provider=os.environ.get("LLM_PROVIDER", "groq").lower(),
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            groq_model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            groq_base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            copilot_api_key=os.environ.get("COPILOT_API_KEY", ""),
            copilot_model=os.environ.get("COPILOT_MODEL", ""),
            request_timeout_seconds=_env_int("LLM_REQUEST_TIMEOUT_SECONDS", 60),
            temperature=float(os.environ.get("LLM_TEMPERATURE", "0.0")),
            max_tokens=_env_int("LLM_MAX_TOKENS", 2048),
            categorize_batch_size=_env_int("LLM_CATEGORIZE_BATCH_SIZE", 10),
        )
        db_path = Path(os.environ.get("DEFECT_DB_PATH", str(cls.db_path)))
        output_dir = Path(os.environ.get("DEFECT_OUTPUT_DIR", str(cls.output_dir)))
        return cls(ado=ado, llm=llm, db_path=db_path, output_dir=output_dir)
