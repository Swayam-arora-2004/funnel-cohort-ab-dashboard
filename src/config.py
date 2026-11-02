"""The only module that reads environment variables (docs/TECH_SPECS.md section 3).

WHY one place: if every module read os.environ, a credential could be picked up anywhere and
it would be impossible to audit. Funnelling it through one frozen dataclass means
`grep -rn "os.environ" src app` must return exactly this file, and that is a check we can
actually run in review (SEC-2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env once, at import time. override=False so a real environment variable (for example
# one set by CI) always wins over the local file.
load_dotenv(override=False)

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Everything the application needs from the environment. Frozen so nothing can mutate it."""

    pg_host: str
    pg_port: int
    pg_db: str
    loader_user: str
    loader_password: str
    ro_user: str
    ro_password: str
    data_raw_dir: Path
    exports_dir: Path

    def url(self, user: str, password: str) -> str:
        """Build a SQLAlchemy URL. Never logged and never shown to a user (SEC-10)."""
        return f"postgresql+psycopg2://{user}:{password}@{self.pg_host}:{self.pg_port}/{self.pg_db}"

    @property
    def loader_url(self) -> str:
        return self.url(self.loader_user, self.loader_password)

    @property
    def ro_url(self) -> str:
        return self.url(self.ro_user, self.ro_password)


def _require(name: str) -> str:
    """Fetch a required variable, failing with a message that names it but never prints a value."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Required environment variable {name} is missing or empty. "
            "Copy .env.example to .env and fill it in (see docs/TECH_SPECS.md section 6)."
        )
    return value


def _resolve(raw: str) -> Path:
    """Resolve a configured path relative to the repo root, so commands work from any directory."""
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def get_settings() -> Settings:
    return Settings(
        pg_host=_require("PG_HOST"),
        pg_port=int(_require("PG_PORT")),
        pg_db=_require("PG_DB"),
        loader_user=_require("LOADER_USER"),
        loader_password=_require("LOADER_PASSWORD"),
        ro_user=_require("RO_USER"),
        ro_password=_require("RO_PASSWORD"),
        data_raw_dir=_resolve(os.environ.get("DATA_RAW_DIR", "./data/raw")),
        exports_dir=_resolve(os.environ.get("EXPORTS_DIR", "./exports")),
    )
