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
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_OAUTH_TOKEN_ROOT,
    DEFAULT_SECRET_ROOT,
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
    enable_openapi: bool = False
    enable_writes: bool = False
    http_bearer_secret_file: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "RANKRAT_HTTP_BEARER_SECRET_FILE",
            "RANKRAT_HTTP_BEARER_TOKEN_FILE",
        ),
    )
    admin_bearer_secret_file: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "RANKRAT_ADMIN_BEARER_SECRET_FILE",
            "RANKRAT_ADMIN_BEARER_TOKEN_FILE",
        ),
    )

    @field_validator(
        "boundary_file",
        "secret_root",
        "oauth_token_root",
        "log_file",
        "http_bearer_secret_file",
        "admin_bearer_secret_file",
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
        if self.enable_writes and self.admin_bearer_secret_file is None:
            raise ValueError("enabled writes require an admin bearer secret file")
        return self

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
