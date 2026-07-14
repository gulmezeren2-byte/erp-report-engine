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

import re

import yaml

from .connect import assert_read_only

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "orders": [
        "order_id", "order_date", "region", "customer", "status",
        "promised_date", "actual_ship_date", "net_total",
    ],
    "order_lines": ["order_id", "item_code", "qty"],
    "inventory": ["item_code", "stock_qty"],
}

_SAFE_VAR = re.compile(r"^[A-Za-z0-9_]{1,16}$")


class ProfileError(Exception):
    pass


class Profile:
    def __init__(self, raw: dict, path: str):
        self.path = path
        self.name = raw.get("profile") or "unnamed"
        self.dialect = raw.get("dialect", "any")
        self.description = raw.get("description", "")
        self.entities: dict[str, str] = {}
        ents = raw.get("entities") or {}
        for entity in REQUIRED_COLUMNS:
            spec = ents.get(entity)
            if not spec or not spec.get("query"):
                raise ProfileError(f"{path}: entity '{entity}' with a query is required")
            self.entities[entity] = spec["query"]

    def render(self, entity: str, profile_vars: dict[str, str]) -> str:
        sql = self.entities[entity]
        for key, val in profile_vars.items():
            if not _SAFE_VAR.match(val):
                raise ProfileError(
                    f"profile var {key}={val!r} is not identifier-safe (letters/digits/underscore only)"
                )
            sql = sql.replace("{" + key + "}", val)
        leftover = re.search(r"\{([a-z_]+)\}", sql)
        if leftover:
            raise ProfileError(
                f"entity '{entity}' still contains unfilled placeholder {{{leftover.group(1)}}} - "
                "add it to profile_vars in the config"
            )
        assert_read_only(sql)
        return sql


def load_profile(path: str) -> Profile:
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ProfileError(f"profile not found: {path}")
    prof = Profile(raw, path)
    # validate every query is read-only at load time, with dummy vars
    dummy = {m: "X" for q in prof.entities.values() for m in re.findall(r"\{([a-z_]+)\}", q)}
    for entity in prof.entities:
        prof.render(entity, dummy)
    return prof
