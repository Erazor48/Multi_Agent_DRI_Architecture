from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Provider selection ────────────────────────────────────────────────
    llm_provider: Literal["anthropic", "gemini"] = Field(
        "gemini", description="Active LLM provider: 'anthropic' or 'gemini'"
    )

    # ── Anthropic ─────────────────────────────────────────────────────────
    anthropic_api_key: str = Field("", description="Anthropic API key")
    anthropic_root_model: str = Field("claude-sonnet-4-6")
    anthropic_default_model: str = Field("claude-sonnet-4-6")

    # ── Gemini ────────────────────────────────────────────────────────────
    google_api_key: str = Field("", description="Google AI Studio / Vertex AI key")
    gemini_root_model: str = Field("gemini-2.5-pro-preview-05-06", description="Model for CEO (most capable)")
    gemini_default_model: str = Field("gemini-2.5-flash-preview-04-17", description="Model for all other agents")

    # ── Unified model accessors (resolve to active provider) ──────────────
    @property
    def root_model(self) -> str:
        return self.gemini_root_model if self.llm_provider == "gemini" else self.anthropic_root_model

    @property
    def default_model(self) -> str:
        return self.gemini_default_model if self.llm_provider == "gemini" else self.anthropic_default_model

    # ── Common LLM settings ───────────────────────────────────────────────
    max_tokens_per_response: int = Field(8192, ge=1024, le=65536)

    # ── Budget ────────────────────────────────────────────────────────────
    budget_max_tokens_per_session: int = Field(2_000_000, ge=10_000)
    budget_child_default_share: float = Field(0.4, gt=0.0, lt=1.0)
    budget_warning_threshold: float = Field(0.2, gt=0.0, lt=1.0)

    # ── Tools ─────────────────────────────────────────────────────────────
    tavily_api_key: str = Field("", description="Tavily search API key (optional)")
    brave_api_key: str = Field("", description="Brave search API key (optional)")

    # ── Storage ───────────────────────────────────────────────────────────
    database_url: str = Field("sqlite+aiosqlite:///./dri_company.db")

    # ── Workspace ─────────────────────────────────────────────────────────
    workspace_dir: Path = Field(Path("./workspace"))

    # ── Orchestration ─────────────────────────────────────────────────────
    max_concurrent_agents: int = Field(20, ge=1, le=200)
    max_spawn_depth: int = Field(10, ge=1, le=50)
    agent_timeout_seconds: int = Field(300, ge=10, le=3600)

    @field_validator("workspace_dir", mode="after")
    @classmethod
    def ensure_workspace_exists(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v

    @model_validator(mode="after")
    def validate_provider_key(self) -> "Settings":
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        if self.llm_provider == "gemini" and not self.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required when LLM_PROVIDER=gemini")
        return self

    @property
    def has_web_search(self) -> bool:
        return bool(self.tavily_api_key or self.brave_api_key)

    @property
    def active_api_key(self) -> str:
        return self.google_api_key if self.llm_provider == "gemini" else self.anthropic_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
