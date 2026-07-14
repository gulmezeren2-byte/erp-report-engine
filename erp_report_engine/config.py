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


class ConfigError(Exception):
    pass


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
    raw: dict[str, Any] = field(default_factory=dict)


def load_config(path: str) -> Config:
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}")

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
        if "://" in url and "@" in url and ":" in url.split("@")[0].split("://")[-1]:
            raise ConfigError(
                "connection.url appears to embed a password - refuse to run. "
                "Use connection.url_env and put the full URL in an environment variable."
            )
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
        raw=raw,
    )
