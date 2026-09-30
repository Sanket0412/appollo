"""Loads .env and config/search.yaml into a single place the rest of the pipeline reads from."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_CONFIG_PATH = REPO_ROOT / "config" / "search.yaml"

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str
    anthropic_api_key: str | None
    resume_text_path: str
    gmail_address: str | None
    gmail_app_password: str | None
    digest_to: str | None
    search_config: dict


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to .env (see .env.example).")
    return value


def _load_search_config() -> dict:
    with SEARCH_CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=_require("DATABASE_URL"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        resume_text_path=os.environ.get("RESUME_TEXT_PATH", "data/private/resume.md"),
        gmail_address=os.environ.get("GMAIL_ADDRESS") or None,
        gmail_app_password=os.environ.get("GMAIL_APP_PASSWORD") or None,
        digest_to=os.environ.get("DIGEST_TO") or None,
        search_config=_load_search_config(),
    )


def is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def resume_text() -> str:
    env_text = os.environ.get("RESUME_TEXT")
    if env_text:
        return env_text
    path = REPO_ROOT / get_settings().resume_text_path
    if not path.exists():
        raise RuntimeError(f"No resume text found: set RESUME_TEXT or create {path}")
    return path.read_text(encoding="utf-8")
