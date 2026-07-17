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
      lookback_weeks: 26
      low_cover_weeks: 2.0
      out_dir: reports
      state_db: state.db
    limits:
      row_cap: 500000
      query_timeout_s: 60
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from .errors import ConfigError  # re-exported for callers that import from .config

__all__ = ["Config", "ConfigError", "load_config"]

_CRED_MSG = (
    "connection.url embeds a credential - refuse to run. Put the full URL in an "
    "environment variable and reference it with connection.url_env instead."
)


# Any query-string key that is some spelling of a secret. Matching a PATTERN
# rather than a fixed list is deliberate: an explicit {password, pwd} pair let
# MySQLdb's `?passwd=` and libpq's `?sslpassword=` through, and the next driver
# will invent another spelling.
_CRED_KEY = re.compile(r"(password|passwd|pwd|secret)", re.IGNORECASE)


def _reject_embedded_credential(url: str) -> None:
    """Refuse a connection URL that carries a password in any common shape.

    Catches user:pass@host, any `?...password/passwd/pwd/secret...=` query
    parameter, and the pyodbc `odbc_connect=...PWD=...` form (which has no `@`).
    """
    from sqlalchemy.engine import make_url

    try:
        u = make_url(url)
    except Exception:
        if _CRED_KEY.search(url):
            raise ConfigError(_CRED_MSG) from None
        return
    if u.password or any(_CRED_KEY.search(k) for k in u.query):
        raise ConfigError(_CRED_MSG)
    odbc = str(u.query.get("odbc_connect", ""))
    if _CRED_KEY.search(odbc):
        raise ConfigError(_CRED_MSG)


@dataclass
class Config:
    db_url: str
    profile_path: str
    profile_vars: dict[str, str] = field(default_factory=dict)
    company_alias: str = "Company"
    # Two quarters. The chart still shows 13 weeks; the extra history is what the
    # XmR control limits are computed from, and limits only settle around n>=15.
    lookback_weeks: int = 26
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
        lookback_weeks=int(rep.get("lookback_weeks", 26)),
        low_cover_weeks=float(rep.get("low_cover_weeks", 2.0)),
        out_dir=rep.get("out_dir", "reports"),
        state_db=rep.get("state_db", "state.db"),
        row_cap=int(lim.get("row_cap", 500_000)),
        query_timeout_s=int(lim.get("query_timeout_s", 60)),
        delivery=raw.get("delivery"),
        narrative=raw.get("narrative"),
        raw=raw,
    )
