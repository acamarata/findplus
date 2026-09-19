"""Configuration for findplus.

Purpose : Single source of truth for all runtime settings and filesystem paths.
Inputs  : Environment variables, optionally loaded from a `.env` file in the project root.
Outputs : A `Settings` instance via `get_settings()`, resolved from state_dir at call time.
Constraints:
    - Nothing secret lives here. Auth material lives in `secrets_file`, which is
      deliberately placed OUTSIDE the repository by default.
    - The API binds to 127.0.0.1 and refuses other hosts unless explicitly overridden.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_GFMT = PROJECT_ROOT / "vendor" / "GoogleFindMyTools"

#: Default home for auth material + logs. Outside the repo on purpose.
DEFAULT_STATE_DIR = Path(os.environ.get("FINDPLUS_STATE_DIR", Path.home() / ".findplus"))


class Settings(BaseSettings):
    """Runtime settings. Every field is overridable via env var of the same name."""

    model_config = SettingsConfigDict(
        env_prefix="FINDPLUS_",
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
    database_path: Path | None = None
    state_dir: Path = DEFAULT_STATE_DIR

    @model_validator(mode="after")
    def _default_database_path(self) -> Settings:
        """Fill database_path from state_dir when unset (D1: env override always wins)."""
        if self.database_path is None:
            self.database_path = self.state_dir / "findplus.sqlite"
        return self

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

    @computed_field
    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "findplus.log"

    @computed_field
    @property
    def alerts_file(self) -> Path:
        return self.state_dir / "alerts.json"

    @computed_field
    @property
    def daemon_file(self) -> Path:
        return self.state_dir / "daemon.json"

    @computed_field
    @property
    def apple_dir(self) -> Path:
        return self.state_dir / "apple"

    @computed_field
    @property
    def task_xml_path(self) -> Path:
        return self.state_dir / "FindPlus-task.xml"

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

    def ensure_state_dir(self) -> None:
        """Create state_dir (0700) and its logs/ subdir. Narrower than ensure_dirs():
        no database-path handling, just the state tree every path property hangs off."""
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        (self.state_dir / "logs").mkdir(mode=0o700, exist_ok=True)


def get_settings(state_dir: Path | None = None) -> Settings:
    """Build a fresh Settings, resolving state_dir at call time (arg -> FINDPLUS_STATE_DIR ->
    ~/.findplus) so test-session isolation (FINDPLUS_STATE_DIR set before import) and
    HOME-monkeypatched tests both work. Not cached: callers that need call-scoped stability
    should hold onto the returned instance."""
    _sd = state_dir or Path(os.environ.get("FINDPLUS_STATE_DIR", Path.home() / ".findplus"))
    return Settings(
        state_dir=_sd,
        _env_file=[str(_sd / "config.env"), ".env"],
    )


def reset_settings_cache() -> None:
    """No-op: get_settings() no longer caches. Kept so existing callers keep working."""
