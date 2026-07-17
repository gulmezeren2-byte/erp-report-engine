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


# Every key the loader actually reads, per section. Checked rather than ignored,
# because the failure mode of `.get(key, default)` is silence: `lookback_week`
# (singular) parses fine, changes nothing, and the operator concludes the setting
# does not work. An unattended report that quietly used a default nobody chose is
# the same class of problem as a number nobody can trace.
_KNOWN: dict[str, set[str]] = {
    "": {"connection", "profile", "profile_vars", "report", "limits", "delivery", "narrative"},
    "connection": {"url", "url_env"},
    "report": {"company_alias", "lookback_weeks", "low_cover_weeks", "out_dir", "state_db"},
    "limits": {"row_cap", "query_timeout_s"},
    "narrative": {"api_base", "model", "api_key_env", "timeout_s", "include_names"},
    "delivery": {"email", "slack", "teams", "power_automate", "healthcheck"},
}


def _suggest(key: str, known: set[str]) -> str:
    import difflib
    near = difflib.get_close_matches(key, sorted(known), n=1, cutoff=0.7)
    return f" - did you mean {near[0]!r}?" if near else ""


def _reject_unknown_keys(raw: dict) -> None:
    for section, known in _KNOWN.items():
        block = raw if section == "" else raw.get(section)
        if not isinstance(block, dict):
            continue
        for key in block:
            if key not in known:
                where = f"{section}.{key}" if section else key
                raise ConfigError(
                    f"unknown config key {where!r}{_suggest(key, known)}. "
                    f"Known keys here: {', '.join(sorted(known))}"
                )


def _num(block: dict, key: str, default, cast):
    """Read a number, and say which key is wrong rather than raising ValueError
    from somewhere three frames down."""
    value = block.get(key, default)
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise ConfigError(
            f"report.{key} must be a number, got {value!r}"
        ) from None


def load_config(path: str) -> Config:
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} does not contain a YAML mapping")
    _reject_unknown_keys(raw)

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
        lookback_weeks=_num(rep, "lookback_weeks", 26, int),
        low_cover_weeks=_num(rep, "low_cover_weeks", 2.0, float),
        out_dir=rep.get("out_dir", "reports"),
        state_db=rep.get("state_db", "state.db"),
        row_cap=_num(lim, "row_cap", 500_000, int),
        query_timeout_s=_num(lim, "query_timeout_s", 60, int),
        delivery=raw.get("delivery"),
        narrative=raw.get("narrative"),
        raw=raw,
    )
