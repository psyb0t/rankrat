"""Parse immutable deployment configuration once at process startup."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from rankrat.constants import (
    DEFAULT_BOUNDARY_FILE,
    DEFAULT_HTTP_HOST,
    DEFAULT_HTTP_PORT,
    DEFAULT_LIGHTHOUSE_WORKER_SOCKET,
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_OAUTH_TOKEN_ROOT,
    DEFAULT_SCHEDULER_INTERVAL_SECONDS,
    DEFAULT_SECRET_ROOT,
    DEFAULT_STATE_RETENTION_DAYS,
    MAX_SCHEDULER_INTERVAL_SECONDS,
    MAX_STATE_RETENTION_DAYS,
    MIN_SCHEDULER_INTERVAL_SECONDS,
    MIN_STATE_RETENTION_DAYS,
)
from rankrat.errors import ConfigurationError

RuntimeMode = Literal["stdio", "http"]


class Settings(BaseSettings):
    """Validated process configuration; instances are never reloaded."""

    model_config = SettingsConfigDict(
        env_prefix="RANKRAT_",
        case_sensitive=False,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    boundary_file: Path = DEFAULT_BOUNDARY_FILE
    secret_root: Path = DEFAULT_SECRET_ROOT
    oauth_token_root: Path = DEFAULT_OAUTH_TOKEN_ROOT
    log_file: Path = DEFAULT_LOG_FILE
    mode: RuntimeMode = "stdio"
    http_host: str = DEFAULT_HTTP_HOST
    http_port: int = Field(default=DEFAULT_HTTP_PORT, ge=1, le=65_535)
    log_level: str = DEFAULT_LOG_LEVEL
    lighthouse_worker_socket: Path | None = DEFAULT_LIGHTHOUSE_WORKER_SOCKET
    state_database: Path | None = None
    scheduler_interval_seconds: int = Field(
        default=DEFAULT_SCHEDULER_INTERVAL_SECONDS,
        ge=MIN_SCHEDULER_INTERVAL_SECONDS,
        le=MAX_SCHEDULER_INTERVAL_SECONDS,
    )
    state_retention_days: int = Field(
        default=DEFAULT_STATE_RETENTION_DAYS,
        ge=MIN_STATE_RETENTION_DAYS,
        le=MAX_STATE_RETENTION_DAYS,
    )
    enable_openapi: bool = False
    read_only: bool = True
    unbounded: bool = False
    # Onboarding creates billable provider resources and rewrites the boundary
    # file this server enforces, so it widens its own future scope. Writable mode
    # alone should not hand an agent that reach: this is a second, explicit
    # switch, and it gates only the agent-reachable surfaces. The operator CLI
    # command is unaffected -- that one is a human at a terminal.
    allow_agent_onboarding: bool = False
    http_bearer_secret_file: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "RANKRAT_HTTP_BEARER_SECRET_FILE",
            "RANKRAT_HTTP_BEARER_TOKEN_FILE",
        ),
    )

    @field_validator("lighthouse_worker_socket", mode="before")
    @classmethod
    def empty_lighthouse_socket_disables_worker(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("state_database", mode="before")
    @classmethod
    def empty_state_database_disables_state(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator(
        "boundary_file",
        "secret_root",
        "oauth_token_root",
        "log_file",
        "lighthouse_worker_socket",
        "state_database",
        "http_bearer_secret_file",
    )
    @classmethod
    def validate_absolute_path(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("configured paths must be absolute")
        return value

    @field_validator("http_host")
    @classmethod
    def validate_http_host(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("http_host must not be empty")
        if normalized == "localhost":
            return normalized
        try:
            ipaddress.ip_address(normalized)
        except ValueError as error:
            raise ValueError("http_host must be an IP address or localhost") from error
        return normalized

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level must be a standard logging level")
        return normalized

    @model_validator(mode="after")
    def validate_network_exposure(self) -> Settings:
        if not self.is_loopback_bind and self.http_bearer_secret_file is None:
            raise ValueError("non-loopback HTTP bind requires an HTTP bearer secret file")
        if self.unbounded and self.read_only:
            raise ValueError("unbounded mode requires RANKRAT_READ_ONLY=false")
        if self.allow_agent_onboarding and self.read_only:
            raise ValueError("agent onboarding requires RANKRAT_READ_ONLY=false")
        return self

    @property
    def agent_onboarding_enabled(self) -> bool:
        """Reach the onboarding tool only when both switches are deliberately set."""

        return self.writes_enabled and self.allow_agent_onboarding

    @property
    def writes_enabled(self) -> bool:
        """Expose write tools only when the operator explicitly disables read-only mode."""

        return not self.read_only

    @property
    def is_loopback_bind(self) -> bool:
        if self.http_host == "localhost":
            return True
        return ipaddress.ip_address(self.http_host).is_loopback


def load_settings() -> Settings:
    """Load settings once and convert validation detail into a safe error."""
    try:
        return Settings()
    except ValueError as error:
        raise ConfigurationError("invalid Rankrat startup configuration") from error
