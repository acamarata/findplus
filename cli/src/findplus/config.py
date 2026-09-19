"""Configuration for findplus.

Purpose : Single source of truth for all runtime settings and filesystem paths.
Inputs  : Environment variables, optionally loaded from a `.env` file in the project root.
Outputs : A cached `Settings` instance via `get_settings()`.
Constraints:
    - Nothing secret lives here. Auth material lives in `secrets_file`, which is
      deliberately placed OUTSIDE the repository by default.
    - The API binds to 127.0.0.1 and refuses other hosts unless explicitly overridden.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_GFMT = PROJECT_ROOT / "vendor" / "GoogleFindMyTools"

#: Default home for auth material + logs. Outside the repo on purpose.
DEFAULT_STATE_DIR = Path(os.environ.get("FINDPLUS_STATE_DIR", Path.home() / ".findplus"))


class Settings(BaseSettings):
    """Runtime settings. Every field is overridable via env var of the same name."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Polling ------------------------------------------------------------
    poll_interval_minutes: float = Field(
        default=5.0,
        description="Minutes between Find Hub queries. Hard floor of 5 unless "
        "ALLOW_FAST_POLLING=true, to avoid Google rate-limiting / account flags.",
    )
    allow_fast_polling: bool = False
    poll_timeout_seconds: float = 90.0
    poll_max_backoff_minutes: float = 60.0

    # --- Analysis -----------------------------------------------------------
    movement_threshold_meters: float = 25.0
    gap_threshold_minutes: float = 20.0

    # --- Retention ----------------------------------------------------------
    retention_days: int = Field(default=0, description="0 = keep history forever.")

    # --- Storage ------------------------------------------------------------
    database_path: Path = PROJECT_ROOT / "data" / "findplus.sqlite"
    state_dir: Path = DEFAULT_STATE_DIR

    # --- API / UI -----------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8647
    ui_refresh_seconds: int = 45

    # --- Logging ------------------------------------------------------------
    log_level: str = "INFO"
    log_max_bytes: int = 5_000_000
    log_backup_count: int = 5

    @field_validator("poll_interval_minutes")
    @classmethod
    def _floor_poll_interval(cls, v: float) -> float:
        # Enforced again at runtime in poller.py; validated here for early feedback.
        if v <= 0:
            raise ValueError("poll_interval_minutes must be positive")
        return v

    @field_validator("host")
    @classmethod
    def _warn_on_public_bind(cls, v: str) -> str:
        if v not in {"127.0.0.1", "localhost", "::1"} and not os.environ.get(
            "FINDPLUS_ALLOW_PUBLIC_BIND"
        ):
            raise ValueError(
                f"Refusing to bind to {v!r}. This app holds a child's location history "
                "and is local-only by design. Set FINDPLUS_ALLOW_PUBLIC_BIND=1 to override."
            )
        return v

    # --- Derived paths ------------------------------------------------------
    @property
    def effective_poll_interval_minutes(self) -> float:
        """Poll interval after applying the 5-minute safety floor."""
        if self.allow_fast_polling:
            return self.poll_interval_minutes
        return max(5.0, self.poll_interval_minutes)

    @property
    def secrets_file(self) -> Path:
        """GoogleFindMyTools `secrets.json`: AAS token, ADM token, FCM creds, owner key."""
        return self.state_dir / "secrets.json"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "findplus.log"

    @property
    def pid_file(self) -> Path:
        return self.state_dir / "findplus.pid"

    @property
    def database_url(self) -> str:
        return f"sqlite+pysqlite:///{self.database_path}"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def ensure_dirs(self) -> None:
        """Create state/data directories with owner-only permissions where sensitive."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test hook: drop the cached Settings so env changes take effect."""
    get_settings.cache_clear()
