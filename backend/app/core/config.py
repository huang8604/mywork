from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    app_timezone: str
    public_base_url: str
    cors_origins: tuple[str, ...]
    trusted_hosts: tuple[str, ...]
    trusted_proxy_cidrs: tuple[str, ...]
    trusted_local_web: bool
    api_token_pepper_file: str | None
    api_token_pepper: str
    api_rate_limit_per_minute: int
    idempotency_retention_days: int
    max_import_bytes: int
    max_import_rows: int
    max_practice_words: int
    max_batch_results: int
    log_level: str
    frontend_dist: str

    @classmethod
    def from_env(cls) -> "Settings":
        value = cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./data/vocab.db"),
            app_timezone=os.getenv("APP_TIMEZONE", "Asia/Shanghai"),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
            cors_origins=_csv("CORS_ORIGINS", "http://localhost:8000"),
            trusted_hosts=_csv("TRUSTED_HOSTS", "localhost,127.0.0.1,testserver"),
            trusted_proxy_cidrs=_csv("TRUSTED_PROXY_CIDRS", "127.0.0.0/8,::1/128"),
            trusted_local_web=_boolean("TRUSTED_LOCAL_WEB", False),
            api_token_pepper_file=os.getenv("API_TOKEN_PEPPER_FILE"),
            api_token_pepper=os.getenv("API_TOKEN_PEPPER", ""),
            api_rate_limit_per_minute=int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "60")),
            idempotency_retention_days=int(os.getenv("IDEMPOTENCY_RETENTION_DAYS", "30")),
            max_import_bytes=int(os.getenv("MAX_IMPORT_BYTES", str(10 * 1024 * 1024))),
            max_import_rows=int(os.getenv("MAX_IMPORT_ROWS", "10000")),
            max_practice_words=int(os.getenv("MAX_PRACTICE_WORDS", "200")),
            max_batch_results=int(os.getenv("MAX_BATCH_RESULTS", "200")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            frontend_dist=os.getenv(
                "FRONTEND_DIST",
                str(Path(__file__).resolve().parents[3] / "frontend" / "dist"),
            ),
        )
        value.validate()
        return value

    def validate(self) -> None:
        ZoneInfo(self.app_timezone)
        if self.idempotency_retention_days < 30:
            raise ValueError("IDEMPOTENCY_RETENTION_DAYS must be at least 30")
        if min(
            self.api_rate_limit_per_minute,
            self.max_import_bytes,
            self.max_import_rows,
            self.max_practice_words,
            self.max_batch_results,
        ) <= 0:
            raise ValueError("configured limits must be positive")
        for network in self.trusted_proxy_cidrs:
            ipaddress.ip_network(network, strict=False)
        if "*" in self.cors_origins:
            raise ValueError("wildcard CORS origins are not allowed")
        if not self.api_token_pepper_file and not self.api_token_pepper:
            raise ValueError("API_TOKEN_PEPPER_FILE or API_TOKEN_PEPPER is required")

    def token_pepper_bytes(self) -> bytes:
        if self.api_token_pepper_file:
            pepper = Path(self.api_token_pepper_file).read_bytes().strip()
            if len(pepper) < 32:
                raise ValueError("token pepper file must contain at least 32 bytes")
            return pepper
        if len(self.api_token_pepper.encode("utf-8")) < 16:
            raise ValueError("API_TOKEN_PEPPER must contain at least 16 bytes")
        return self.api_token_pepper.encode("utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
