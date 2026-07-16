"""Configuration loading. Secrets never live in the config file.

config.yaml shape (see config.example.yaml):

    connection:
      url_env: ERP_DB_URL          # env var holding the SQLAlchemy URL
      # or discrete parts (password ALWAYS via env):
      # dialect: mssql+pyodbc / sqlite / postgresql+psycopg2 ...
    profile: profiles/logo_tiger.yaml
    profile_vars:                  # substituted into {placeholders} in queries
      firm_no: "001"
      period_no: "01"
    report:
      company_alias: "Şirket"      # display name only - use an alias if you prefer
      lookback_weeks: 13
      low_cover_weeks: 2.0
      out_dir: reports
      state_db: state.db
    limits:
      row_cap: 500000
      query_timeout_s: 60
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from .errors import ConfigError  # re-exported for callers that import from .config

__all__ = ["Config", "ConfigError", "load_config"]

_CRED_MSG = (
    "connection.url embeds a credential - refuse to run. Put the full URL in an "
    "environment variable and reference it with connection.url_env instead."
)


def _reject_embedded_credential(url: str) -> None:
    """Refuse a connection URL that carries a password in any common shape.

    Catches user:pass@host, `?password=`/`?pwd=` query parameters, and the
    pyodbc `odbc_connect=...PWD=...` form (which has no `@` at all).
    """
    from sqlalchemy.engine import make_url

    try:
        u = make_url(url)
    except Exception:
        low = url.lower()
        if "pwd=" in low or "password=" in low:
            raise ConfigError(_CRED_MSG) from None
        return
    q = {k.lower(): str(v) for k, v in u.query.items()}
    odbc = q.get("odbc_connect", "").lower()
    if u.password or "password" in q or "pwd" in q or "pwd=" in odbc or "password=" in odbc:
        raise ConfigError(_CRED_MSG)


@dataclass
class Config:
    db_url: str
    profile_path: str
    profile_vars: dict[str, str] = field(default_factory=dict)
    company_alias: str = "Company"
    lookback_weeks: int = 13
    low_cover_weeks: float = 2.0
    out_dir: str = "reports"
    state_db: str = "state.db"
    row_cap: int = 500_000
    query_timeout_s: int = 60
    delivery: dict[str, Any] | None = None
    narrative: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def load_config(path: str) -> Config:
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None

    conn = raw.get("connection") or {}
    url = None
    if conn.get("url_env"):
        url = os.environ.get(conn["url_env"])
        if not url:
            raise ConfigError(
                f"environment variable {conn['url_env']} is not set "
                "(secrets never live in the config file)"
            )
    elif conn.get("url"):
        url = conn["url"]
        _reject_embedded_credential(url)
    if not url:
        raise ConfigError("connection.url_env (preferred) or connection.url is required")

    profile = raw.get("profile")
    if not profile:
        raise ConfigError("profile is required (path to a profile YAML)")

    rep = raw.get("report") or {}
    lim = raw.get("limits") or {}
    return Config(
        db_url=url,
        profile_path=profile,
        profile_vars={k: str(v) for k, v in (raw.get("profile_vars") or {}).items()},
        company_alias=rep.get("company_alias", "Company"),
        lookback_weeks=int(rep.get("lookback_weeks", 13)),
        low_cover_weeks=float(rep.get("low_cover_weeks", 2.0)),
        out_dir=rep.get("out_dir", "reports"),
        state_db=rep.get("state_db", "state.db"),
        row_cap=int(lim.get("row_cap", 500_000)),
        query_timeout_s=int(lim.get("query_timeout_s", 60)),
        delivery=raw.get("delivery"),
        narrative=raw.get("narrative"),
        raw=raw,
    )
