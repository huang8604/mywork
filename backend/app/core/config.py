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
    dictionary_index_path: str
    frontend_dist: str
    ai_base_url: str
    ai_api_key_file: str | None
    ai_api_key: str
    ai_model: str
    tts_base_url: str
    tts_api_key_file: str | None
    tts_api_key: str
    tts_model: str
    tts_voice: str
    tts_audio_dir: str
    tts_timeout_seconds: float
    tts_provider: str
    tts_auto_generate_on_import: bool
    volc_base_url: str
    volc_api_key_file: str | None
    volc_api_key: str
    volc_model: str
    volc_resource_id: str
    volc_voice: str
    volc_timeout_seconds: float
    web_login_required: bool
    web_admin_username: str
    web_admin_password: str
    web_admin_password_file: str | None
    session_secret: str
    session_secret_file: str | None
    session_max_age: int

    @classmethod
    def from_env(cls) -> "Settings":
        ai_api_key_file = os.getenv("AI_API_KEY_FILE")
        if ai_api_key_file:
            ai_api_key = Path(ai_api_key_file).read_text(encoding="utf-8").strip()
            if not ai_api_key:
                raise ValueError("AI_API_KEY_FILE must not be empty")
        else:
            ai_api_key = os.getenv("AI_API_KEY", "").strip()
        tts_api_key_file = os.getenv("TTS_API_KEY_FILE")
        if tts_api_key_file:
            tts_api_key = Path(tts_api_key_file).read_text(encoding="utf-8").strip()
            if not tts_api_key:
                raise ValueError("TTS_API_KEY_FILE must not be empty")
        else:
            tts_api_key = os.getenv("TTS_API_KEY", "").strip()
        volc_api_key_file = os.getenv("VOLC_TTS_API_KEY_FILE")
        if volc_api_key_file:
            volc_api_key = Path(volc_api_key_file).read_text(encoding="utf-8").strip()
            if not volc_api_key:
                raise ValueError("VOLC_TTS_API_KEY_FILE must not be empty")
        else:
            volc_api_key = os.getenv("VOLC_TTS_API_KEY", "").strip()
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
            dictionary_index_path=os.getenv(
                "DICTIONARY_INDEX_PATH",
                str(Path(__file__).resolve().parents[3] / "dictionary-index.json"),
            ),
            frontend_dist=os.getenv(
                "FRONTEND_DIST",
                str(Path(__file__).resolve().parents[3] / "frontend" / "dist"),
            ),
            ai_base_url=os.getenv("AI_BASE_URL", "").rstrip("/"),
            ai_api_key_file=ai_api_key_file,
            ai_api_key=ai_api_key,
            ai_model=os.getenv("AI_MODEL", "gpt-4o-mini"),
            tts_base_url=os.getenv("TTS_BASE_URL", "https://api.xiaomimimo.com/v1").rstrip("/"),
            tts_api_key_file=tts_api_key_file,
            tts_api_key=tts_api_key,
            tts_model=os.getenv("TTS_MODEL", "mimo-v2.5-tts"),
            tts_voice=os.getenv("TTS_VOICE", "Chloe"),
            tts_audio_dir=os.getenv("TTS_AUDIO_DIR", "").strip(),
            tts_timeout_seconds=float(os.getenv("TTS_TIMEOUT_SECONDS", "60")),
            tts_provider=os.getenv("TTS_PROVIDER", "mimo").strip().lower() or "mimo",
            tts_auto_generate_on_import=_boolean("TTS_AUTO_GENERATE_ON_IMPORT", True),
            volc_base_url=os.getenv("VOLC_TTS_BASE_URL", "https://openspeech.bytedance.com").rstrip("/"),
            volc_api_key_file=volc_api_key_file,
            volc_api_key=volc_api_key,
            volc_model=os.getenv("VOLC_TTS_MODEL", "doubao-seed-tts-2.0"),
            volc_resource_id=os.getenv("VOLC_TTS_RESOURCE_ID", "seed-tts-2.0"),
            volc_voice=os.getenv("VOLC_TTS_VOICE", "BV700_V2_streaming"),
            volc_timeout_seconds=float(os.getenv("VOLC_TTS_TIMEOUT_SECONDS", "60")),
            web_login_required=_boolean("WEB_LOGIN_REQUIRED", False),
            web_admin_username=os.getenv("WEB_ADMIN_USERNAME", "admin"),
            web_admin_password=os.getenv("WEB_ADMIN_PASSWORD", ""),
            web_admin_password_file=os.getenv("WEB_ADMIN_PASSWORD_FILE"),
            session_secret=os.getenv("SESSION_SECRET", ""),
            session_secret_file=os.getenv("SESSION_SECRET_FILE"),
            session_max_age=int(os.getenv("SESSION_MAX_AGE", "604800")),
        )
        value.validate()
        return value

    def validate(self) -> None:
        ZoneInfo(self.app_timezone)
        if self.idempotency_retention_days < 30:
            raise ValueError("IDEMPOTENCY_RETENTION_DAYS must be at least 30")
        if self.session_max_age <= 0:
            raise ValueError("SESSION_MAX_AGE must be positive")
        if self.tts_timeout_seconds <= 0:
            raise ValueError("TTS_TIMEOUT_SECONDS must be positive")
        if self.volc_timeout_seconds <= 0:
            raise ValueError("VOLC_TTS_TIMEOUT_SECONDS must be positive")
        if self.tts_provider not in {"mimo", "volc"}:
            raise ValueError("TTS_PROVIDER must be 'mimo' or 'volc'")
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

    def session_secret_bytes(self) -> bytes:
        if self.session_secret_file:
            secret = Path(self.session_secret_file).read_bytes().strip()
            if len(secret) < 32:
                raise ValueError("session secret file must contain at least 32 bytes")
            return secret
        if self.session_secret:
            if len(self.session_secret.encode("utf-8")) < 32:
                raise ValueError("SESSION_SECRET must contain at least 32 bytes")
            return self.session_secret.encode("utf-8")
        # Fall back to the token pepper (already a high-entropy secret) so deployers
        # don't have to provision a second secret just to enable cookie login.
        return self.token_pepper_bytes()

    @property
    def ai_enabled(self) -> bool:
        return bool(self.ai_base_url and self.ai_api_key)

    @property
    def tts_enabled(self) -> bool:
        return bool(self.tts_base_url and self.tts_api_key)

    @property
    def volc_enabled(self) -> bool:
        return bool(self.volc_base_url and self.volc_api_key)

    def provider_enabled(self, provider: str) -> bool:
        return self.tts_enabled if provider == "mimo" else self.volc_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
