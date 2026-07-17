"""The semantic profile layer.

ERP schemas are cryptic (Logo Tiger: LG_001_01_ORFICHE; Netsis: TBLSIPAMAS...).
A profile is a versioned YAML contract that maps one ERP's schema to the
engine's canonical entities. The engine only ever sees canonical columns -
swap the profile, keep the report.

Canonical entities and their required output columns:

    orders:       order_id, order_date, region, customer, status,
                  promised_date, actual_ship_date, net_total
    order_lines:  order_id, item_code, qty
    inventory:    item_code, stock_qty

Optional entities (mapped only if the profile defines them; everything
downstream degrades gracefully when they are absent):

    receivables:  invoice_id, customer, due_date, open_amount

Profile YAML shape:

    profile: logo_tiger
    dialect: mssql
    description: ...
    entities:
      orders:
        query: |
          SELECT ... FROM LG_{firm_no}_{period_no}_ORFICHE WHERE DATE_ >= :since
      ...

{placeholders} are substituted from config.profile_vars (identifier-safe
values only); :since is bound as a real query parameter.
"""

from __future__ import annotations

import importlib.resources
import re
from pathlib import Path

import yaml

from .connect import _SQLGLOT_DIALECT, assert_read_only
from .errors import ContractError

_BUNDLED = "erp_report_engine.profiles"

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "orders": [
        "order_id", "order_date", "region", "customer", "status",
        "promised_date", "actual_ship_date", "net_total",
    ],
    "order_lines": ["order_id", "item_code", "qty"],
    "inventory": ["item_code", "stock_qty"],
}

# Entities a profile MAY map; extracted only when present, and every consumer
# (aging analysis, report sections, Power BI export) is written to no-op without
# them - so an ERP with no accessible AR ledger still produces the full report.
OPTIONAL_COLUMNS: dict[str, list[str]] = {
    "receivables": ["invoice_id", "customer", "due_date", "open_amount"],
}

_SAFE_VAR = re.compile(r"^[A-Za-z0-9_]{1,16}$")


class ProfileError(ContractError):
    """A profile is malformed or breaks the canonical-entity contract."""


class Profile:
    def __init__(self, raw: dict, path: str):
        self.path = path
        self.name = raw.get("profile") or "unnamed"
        self.dialect = raw.get("dialect", "any")
        self.description = raw.get("description", "")
        self.contract: dict = raw.get("contract") or {}   # optional declarative checks
        self.entities: dict[str, str] = {}
        self.optional_entities: set[str] = set()
        ents = raw.get("entities") or {}
        for entity in REQUIRED_COLUMNS:
            spec = ents.get(entity)
            if not spec or not spec.get("query"):
                raise ProfileError(f"{path}: entity '{entity}' with a query is required")
            self.entities[entity] = spec["query"]
        for entity in OPTIONAL_COLUMNS:
            spec = ents.get(entity)
            if spec and spec.get("query"):
                self.entities[entity] = spec["query"]
                self.optional_entities.add(entity)

    def render(self, entity: str, profile_vars: dict[str, str]) -> str:
        sql = self.entities[entity]
        for key, val in profile_vars.items():
            if not _SAFE_VAR.match(val):
                raise ProfileError(
                    f"profile var {key}={val!r} is not identifier-safe (letters/digits/underscore only)"
                )
            sql = sql.replace("{" + key + "}", val)
        leftover = re.search(r"\{([A-Za-z0-9_]+)\}", sql)
        if leftover:
            raise ProfileError(
                f"entity '{entity}' still contains unfilled placeholder {{{leftover.group(1)}}} - "
                "add it to profile_vars in the config"
            )
        # Check with the dialect the profile DECLARES. Checking dialect-blind here
        # while safe_read re-checks with the engine's dialect let the two disagree:
        # the guard that ran at load time was not the guard that ran at execution.
        assert_read_only(sql, dialect=_SQLGLOT_DIALECT.get(self.dialect))
        return sql


def bundled_profiles() -> list[str]:
    """Names of the profiles shipped inside the wheel (e.g. 'generic', 'logo_tiger')."""
    try:
        return sorted(
            r.name[:-5]
            for r in importlib.resources.files(_BUNDLED).iterdir()
            if r.name.endswith(".yaml")
        )
    except (ModuleNotFoundError, FileNotFoundError, NotADirectoryError):
        return []


def _resolve(ref: str):
    """Resolve a profile reference to (source, display_name).

    `ref` may be a path to a YAML file on disk, or the name of a bundled
    profile ('logo_tiger' or 'logo_tiger.yaml'). The returned source exposes
    ``read_text`` (a pathlib.Path or an importlib.resources Traversable), so an
    installed wheel needs no ``profiles/`` folder next to the working directory.
    """
    p = Path(ref)
    if p.is_file():
        return p, str(p)
    name = p.name[:-5] if p.name.endswith(".yaml") else p.name
    try:
        res = importlib.resources.files(_BUNDLED).joinpath(f"{name}.yaml")
        if res.is_file():
            return res, f"{name} (bundled)"
    except (ModuleNotFoundError, FileNotFoundError, NotADirectoryError):
        pass
    known = ", ".join(bundled_profiles()) or "none"
    raise ProfileError(
        f"profile not found: {ref!r} - not a file on disk and not a bundled "
        f"profile (bundled profiles: {known})"
    )


def load_profile(ref: str) -> Profile:
    source, display = _resolve(ref)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ProfileError(f"profile not found: {display}") from None
    prof = Profile(raw, display)
    # validate every query is read-only at load time, with dummy vars
    dummy = {m: "X" for q in prof.entities.values() for m in re.findall(r"\{([A-Za-z0-9_]+)\}", q)}
    for entity in prof.entities:
        prof.render(entity, dummy)
    return prof
