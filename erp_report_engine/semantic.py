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

# The canonical schema: for each entity, every column with its type and what it
# MEANS. This is what separates a semantic layer from a table-rename - an agent
# that knows `actual_ship_date` is NULL until a shipment happens writes correct
# on-time SQL; one handed only column names guesses. describe_model serves this
# to the agent, and REQUIRED_COLUMNS / OPTIONAL_COLUMNS are DERIVED from it below,
# so the contract the extractor checks and the schema the agent sees never drift.
#
# Shape: {entity: {"required": bool, "grain": str, "columns": {name: (type, desc)}}}
CANONICAL_SCHEMA: dict[str, dict] = {
    "orders": {
        "required": True,
        "grain": "one row per order (duplicates on order_id are collapsed to one)",
        "columns": {
            "order_id": ("text", "unique order identifier; the join key for order_lines"),
            "order_date": ("date", "when the order was placed - drives the ISO-week revenue and order-count KPIs"),
            "region": ("text", "sales region - used for week-over-week driver attribution"),
            "customer": ("text", "customer name - used for driver attribution and revenue concentration"),
            "status": ("text", "order status; 'delivered', 'shipped' or 'closed' count as fulfilled"),
            "promised_date": ("date", "the date the order was promised to ship"),
            "actual_ship_date": ("date", "when it actually shipped; on-time = actual_ship_date <= promised_date. "
                                 "NULL means NOT yet shipped - such a late order is not counted against on-time %"),
            "net_total": ("number", "order net total - this is the revenue measure"),
        },
    },
    "order_lines": {
        "required": True,
        "grain": "one row per order line",
        "columns": {
            "order_id": ("text", "the order this line belongs to (joins to orders.order_id)"),
            "item_code": ("text", "the stock item on the line (joins to inventory.item_code)"),
            "qty": ("number", "quantity ordered - summed over recent weeks to estimate weekly demand"),
        },
    },
    "inventory": {
        "required": True,
        "grain": "one row per item (quantities summed if the source splits by warehouse)",
        "columns": {
            "item_code": ("text", "stock item identifier"),
            "stock_qty": ("number", "units on hand - divided by average weekly demand to get weeks of cover"),
        },
    },
    "receivables": {
        "required": False,
        "grain": "one row per open invoice (positive, dated balances)",
        "columns": {
            "invoice_id": ("text", "unique open-invoice identifier"),
            "customer": ("text", "the customer who owes the balance"),
            "due_date": ("date", "when payment is due; overdue days = report date - due_date"),
            "open_amount": ("number", "the open balance; only positive, dated balances are aged"),
        },
    },
}

# A couple of runnable canonical queries per entity, to show an agent the shape of
# correct SQL against the semantic layer (all read-only, all in canonical names).
CANONICAL_EXAMPLES: dict[str, list[str]] = {
    "orders": [
        "SELECT customer, SUM(net_total) AS revenue FROM orders GROUP BY customer ORDER BY revenue DESC",
        "SELECT region, COUNT(*) AS orders FROM orders WHERE status IN ('delivered','shipped','closed') GROUP BY region",
    ],
    "order_lines": [
        "SELECT l.item_code, SUM(l.qty) AS units FROM order_lines l "
        "JOIN orders o ON o.order_id = l.order_id GROUP BY l.item_code ORDER BY units DESC",
    ],
    "inventory": ["SELECT item_code, stock_qty FROM inventory WHERE stock_qty = 0"],
    "receivables": [
        "SELECT customer, SUM(open_amount) AS owed FROM receivables GROUP BY customer ORDER BY owed DESC",
    ],
}

# Derived contracts - one source (CANONICAL_SCHEMA), no drift with the agent view.
REQUIRED_COLUMNS: dict[str, list[str]] = {
    e: list(spec["columns"]) for e, spec in CANONICAL_SCHEMA.items() if spec["required"]
}
OPTIONAL_COLUMNS: dict[str, list[str]] = {
    e: list(spec["columns"]) for e, spec in CANONICAL_SCHEMA.items() if not spec["required"]
}

# The canonical model has its own version, bumped only when an entity or column
# changes - so the published contract (docs/model.json) is stable across engine
# releases and only moves when the *model* does.
CANONICAL_MODEL_VERSION = "1"


def canonical_model() -> dict:
    """The full canonical model as a stable, JSON-serialisable contract.

    This is the machine-readable form of what `describe_model` tells an agent:
    every entity's grain, every column's type and meaning, and runnable example
    queries - independent of any one ERP profile. Published as docs/model.json
    and emitted by `erp-report-engine schema`, so a tool can consume the model
    without connecting, and CI fails if the published copy drifts from the code.
    """
    entities = {}
    for name, spec in CANONICAL_SCHEMA.items():
        entities[name] = {
            "required": spec["required"],
            "grain": spec["grain"],
            "columns": [
                {"name": col, "type": typ, "description": desc}
                for col, (typ, desc) in spec["columns"].items()
            ],
            "examples": CANONICAL_EXAMPLES.get(name, []),
        }
    return {
        "model_version": CANONICAL_MODEL_VERSION,
        "entities": entities,
        "notes": (
            "Query only these canonical entities and columns through the guarded, "
            "read-only path (the MCP `query` tool). A semantic profile maps them to a "
            "specific ERP's real tables; the raw schema is never exposed. Optional "
            "entities appear only when a profile maps them. Every access is read-only "
            "and audited."
        ),
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
