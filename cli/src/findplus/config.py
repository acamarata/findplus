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

import contextlib
import os
from pathlib import Path

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from findplus.config_bind import is_public_bind
from findplus.config_keys import validate_config_key as validate_config_key
from findplus.config_keys import write_config_key as write_config_key
from findplus.providers.findhub.bootstrap import resolve_vendor_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
#: Packaging-aware: the packaged findplus/_vendor copy if installed, else the
#: repo dev-tree path (which may not exist — checked by callers, e.g. `findplus
#: doctor`'s "GoogleFindMyTools vendored" row). Resolved once at import time via
#: the same lookup ensure_gfmt_importable() uses, so an installed wheel reports
#: correctly instead of always pointing at a repo path that does not exist there.
VENDOR_GFMT = resolve_vendor_path()

#: Default home for auth material + logs. Outside the repo on purpose.
DEFAULT_STATE_DIR = Path(os.environ.get("FINDPLUS_STATE_DIR", Path.home() / ".findplus"))

#: The SQLite file plus the two siblings the engine creates at the process
#: umask in WAL mode. All three hold (or leak) location history.
DB_FILE_SUFFIXES = ("", "-wal", "-shm")

#: umask every findplus entry point installs: new files 0600, new dirs 0700.
PRIVATE_UMASK = 0o077


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
    geofence_default_accuracy_meters: float = Field(
        default=100.0,
        description="Fallback accuracy used when a fix has no accuracy_meters value, "
        "for geofence classification and group-presence clustering.",
    )

    # --- Groups / presence ---------------------------------------------------
    presence_window_minutes: int = Field(
        default=60,
        description="How far back a member's last fix can be and still count as "
        "reporting for group presence and staleness checks.",
    )
    group_window_minutes: int = Field(
        default=30,
        description="Half-width, in minutes, of the window used to match member "
        "place-events into one group_place_events row.",
    )

    # --- Alerts ---------------------------------------------------------------
    alerts_enabled: bool = Field(
        default=True,
        description="Master switch: when false, alert dispatch is skipped entirely.",
    )

    # --- Widget -----------------------------------------------------------------
    widget_show_map: bool = Field(
        default=False,
        description="Default for whether the macOS widget shows a map. The "
        "settings-table key `widget.show_map` wins over this when set from the UI.",
    )

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

    # --- Apple Find My provider ---------------------------------------------
    apple_anisette_url: str | None = Field(
        default=None,
        description="Remote anisette-server URL. Unset uses FindMy.py's "
        "LocalAnisetteProvider (a local anisette daemon) instead.",
    )

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
        if is_public_bind(v):
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
        self.harden_permissions()

    def sensitive_paths(self) -> list[Path]:
        """Every file that must be 0600, whether or not it exists yet."""
        db = self.database_path
        paths = [db.with_name(db.name + suffix) for suffix in DB_FILE_SUFFIXES]
        paths.append(self.log_file)
        return paths

    def harden_permissions(self) -> None:
        """chmod the state tree to 0700 and the history/log files to 0600.

        The database holds a child's location history; the default umask on a
        shared machine leaves it group- and world-readable. Missing files are
        skipped, and an OSError (a read-only mount, another user's file) is
        never fatal — `findplus doctor` reports what could not be fixed.
        """
        for directory in (self.state_dir, self.log_dir):
            with contextlib.suppress(OSError):
                if directory.is_dir():
                    os.chmod(directory, 0o700)
        for path in self.sensitive_paths():
            with contextlib.suppress(OSError):
                if path.exists():
                    os.chmod(path, 0o600)

    def ensure_state_dir(self) -> None:
        """Create state_dir (0700) and its logs/ subdir. Narrower than ensure_dirs():
        no database-path handling, just the state tree every path property hangs off."""
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        (self.state_dir / "logs").mkdir(mode=0o700, exist_ok=True)


def _unprefixed_config_env(state_dir: Path) -> dict[str, str]:
    """Read the bare (unprefixed) keys out of state_dir/config.env.

    Purpose    : specs/data-model.md § state dir says config.env keys are Settings
                 field names upper-cased with the FINDPLUS_ prefix OPTIONAL — both
                 forms accepted. pydantic-settings applies env_prefix to dotenv files
                 as well as to the environment, so the unprefixed form would otherwise
                 be silently dropped and `findplus config set LOG_LEVEL DEBUG` would
                 write a line that never reaches Settings.
    Inputs     : the resolved state dir.
    Outputs    : {field_name: raw string value} for unprefixed keys only; prefixed keys
                 are left to the normal dotenv source.
    Constraints: a real FINDPLUS_* environment variable always wins, so a key already
                 present in os.environ is skipped.
    """
    path = state_dir / "config.env"
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        name = key.strip().upper()
        if name.startswith("FINDPLUS_"):
            continue  # handled by the dotenv source
        field = name.lower()
        if field in Settings.model_fields and f"FINDPLUS_{name}" not in os.environ:
            values[field] = value.strip().strip("'\"")
    values.pop("state_dir", None)  # already resolved by the caller
    return values


def get_settings(state_dir: Path | None = None) -> Settings:
    """Build a fresh Settings, resolving state_dir at call time (arg -> FINDPLUS_STATE_DIR ->
    ~/.findplus) so test-session isolation (FINDPLUS_STATE_DIR set before import) and
    HOME-monkeypatched tests both work. Not cached: callers that need call-scoped stability
    should hold onto the returned instance."""
    _sd = state_dir or Path(os.environ.get("FINDPLUS_STATE_DIR", Path.home() / ".findplus"))
    # Dotenv sources, lowest precedence first (pydantic-settings lets a later
    # file win). Both are ABSOLUTE on purpose: a bare ".env" is resolved against
    # the process working directory, so running `findplus` from any checkout
    # that happened to contain a .env silently rewrote the daemon's database
    # path, state dir or log level. The only two files that may configure
    # findplus are the dev checkout's own .env and the state dir's config.env,
    # and the user's config.env wins over the dev tree.
    return Settings(
        state_dir=_sd,
        _env_file=[str(PROJECT_ROOT / ".env"), str(_sd / "config.env")],
        **_unprefixed_config_env(_sd),
    )


def reset_settings_cache() -> None:
    """No-op: get_settings() no longer caches. Kept so existing callers keep working."""
