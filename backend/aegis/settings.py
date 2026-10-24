"""Runtime configuration from environment variables (deployment config stays out of application logic).

See .env.example and docs/DEPLOYMENT.md. Nothing here is a secret by default.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.environ.get("AEGIS_ENV", "development").lower())
    host: str = field(default_factory=lambda: os.environ.get(
        "AEGIS_HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("PORT", _int("AEGIS_PORT", 8000)))
    max_upload_bytes: int = field(default_factory=lambda: _int("AEGIS_MAX_UPLOAD_MB", 5) * 1024 * 1024)
    max_upload_rows: int = field(default_factory=lambda: _int("AEGIS_MAX_UPLOAD_ROWS", 50000))
    max_datasets: int = field(default_factory=lambda: _int("AEGIS_MAX_DATASETS", 20))
    max_bench_seeds: int = field(default_factory=lambda: _int("AEGIS_MAX_BENCH_SEEDS", 100))
    basic_auth_user: str = field(default_factory=lambda: os.environ.get("AEGIS_BASIC_AUTH_USER", ""))
    basic_auth_password: str = field(default_factory=lambda: os.environ.get("AEGIS_BASIC_AUTH_PASSWORD", ""))
    allow_public: bool = field(default_factory=lambda: os.environ.get("AEGIS_ALLOW_PUBLIC", "").lower() == "true")
    cors_origins: list[str] = field(default_factory=lambda: [o for o in os.environ.get(
        "AEGIS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o])

    @property
    def production(self) -> bool:
        return self.env == "production"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.basic_auth_user and self.basic_auth_password)

    @property
    def access_mode(self) -> str:
        """basic-auth | public | locked. Production fails closed unless auth or explicit public access is set."""
        if self.auth_enabled:
            return "basic-auth"
        if self.production and not self.allow_public:
            return "locked"
        return "public"


settings = Settings()
