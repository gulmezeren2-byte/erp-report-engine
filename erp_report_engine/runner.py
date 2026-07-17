"""The orchestration facade: one pure place that turns a Config into results.

The CLI, the MCP server, and tests all call these functions instead of
re-wiring extract -> kpi -> insights -> state -> render themselves. Nothing
here prints or calls sys.exit - callers decide how to present the result.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import pandas as pd

from .config import Config
from .connect import Auditor, make_engine, safe_read
from .extract import Extraction, extract_all
from .insights import build as build_insights
from .kpi import compute
from .render import render
from .semantic import Profile, load_profile
from .state import State

# CTE namespace for the canonical entities, kept clear of whatever the ERP calls
# its own tables (and of whatever the agent names its CTEs).
_CTE_PREFIX = "_erp_"


@dataclass
class RunResult:
    cfg: Config
    profile: Profile
    extraction: Extraction
    kpis: dict = field(default_factory=dict)
    findings: list[dict] = field(default_factory=list)
    auditor: Auditor = field(default_factory=Auditor)
    streak: int = 0
    html: str = ""
    report_path: str | None = None
    narrative: dict | None = None

    @property
    def mismatches(self) -> list[str]:
        return [i for i in self.extraction.issues if "MISMATCH" in i]


def _prepare(cfg: Config):
    profile = load_profile(cfg.profile_path)
    engine = make_engine(cfg.db_url, cfg.query_timeout_s)
    return profile, engine, Auditor()


def validate(cfg: Config) -> RunResult:
    """Connect, extract, reconcile - touch nothing else."""
    profile, engine, auditor = _prepare(cfg)
    ex = extract_all(engine, auditor, profile, cfg)
    return RunResult(cfg=cfg, profile=profile, extraction=ex, auditor=auditor)


def build_report(cfg: Config, *, write: bool = True, narrate: bool = False) -> RunResult:
    """Produce the weekly report (and optionally write it to out_dir)."""
    profile, engine, auditor = _prepare(cfg)
    ex = extract_all(engine, auditor, profile, cfg)
    kpis = compute(ex.frames, cfg.low_cover_weeks, ex.as_of)
    findings = build_insights(kpis, ex.frames, cfg.low_cover_weeks)

    narrative = None
    if narrate:
        from .narrate import narrate as _narrate
        narrative = _narrate(cfg, kpis, findings, ex)  # aggregates-only; None if unconfigured

    path = os.path.join(cfg.out_dir, f"erp_report_{kpis['this_week']}.html")
    state = State(cfg.state_db)
    # Only a run that actually writes a report gets to write run memory. This
    # used to record unconditionally, so every MCP `weekly_report` call - a READ
    # - appended a row and stored the path of a file that was never written, and
    # since streak() resolves a week via MAX(run_at), the last agent question
    # became the official record of the week.
    if write:
        state.record(kpis["this_week"], kpis, path)
    # This week counts either way (K6): a preview must report the same streak as
    # the written report, not one short of it.
    streak = state.streak("revenue", current=(kpis["this_week"], kpis))
    state.close()

    html = render(cfg, profile, kpis, findings, ex, auditor, streak, narrative=narrative)
    if write:
        os.makedirs(cfg.out_dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(html)
        os.replace(tmp, path)  # atomic - never leave a half-written report

    return RunResult(cfg=cfg, profile=profile, extraction=ex, kpis=kpis,
                     findings=findings, auditor=auditor, streak=streak, html=html,
                     report_path=path if write else None, narrative=narrative)


def scope_to_canonical(profile: Profile, cfg: Config, sql: str, dialect: str | None) -> str:
    """Rewrite an ad-hoc query so it reads the profile's canonical entities, and
    can reach nothing else.

    This is what "the agent talks to `orders`, never `LG_001_01_ORFICHE`" has to
    mean to be true. It was true of every tool EXCEPT the one that mattered:
    `query` passed raw SQL through, so an agent could read any table the login
    could reach - the ERP's own schema, the system catalogue, anything - and the
    semantic layer, which is the entire point of the product, was optional.

    Two halves, and neither works alone:

    - Every table the query names must be a canonical entity, unqualified. A
      qualified name is refused because `dbo.orders` would resolve to a real
      table rather than the entity below, and a CTE may not shadow an entity name
      for the same reason.
    - The entities it names are injected as CTEs built from the profile's own
      SQL. Without this the allowlist would be useless against a real ERP, where
      there IS no table called `orders` - the name only exists in the profile.

    So the agent writes `SELECT customer, SUM(net_total) FROM orders GROUP BY
    customer` and it runs, identically, on Logo Tiger, Netsis, Mikro or the demo.

    The CTEs are prefixed and the references rewritten to `_erp_orders AS orders`
    rather than just named `orders`, because a profile is perfectly entitled to
    read a source table that already has the canonical name - generic.yaml does
    exactly that - and `orders AS (SELECT ... FROM orders)` is a circular
    reference, not a query. Aliasing back to the entity name keeps the agent's
    own `orders.order_id` and `FROM orders o` working untouched.
    """
    import sqlglot
    from sqlglot import exp

    from .connect import ReadOnlyViolation

    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception as e:
        raise ReadOnlyViolation(
            f"could not parse this query as {dialect or 'generic'} SQL: {str(e)[:120]}"
        ) from e

    entities = set(profile.entities)
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    reserved = sorted(n for n in cte_names if n in entities or n.startswith(_CTE_PREFIX))
    if reserved:
        raise ReadOnlyViolation(
            f"a CTE may not be named {', '.join(reserved)} - that name belongs to the "
            f"canonical entity layer, and shadowing it would hide the entity itself"
        )

    used: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if table.db or table.catalog:
            raise ReadOnlyViolation(
                f"qualified table names are not readable here ({table.sql(dialect=dialect)}); "
                f"query the canonical entities instead: {', '.join(sorted(entities))}"
            )
        if name in cte_names:
            continue                      # defined by the query itself, not a table
        if name not in entities:
            raise ReadOnlyViolation(
                f"{name!r} is not a canonical entity. This server exposes only "
                f"{', '.join(sorted(entities))} - the raw ERP schema is deliberately "
                f"out of reach, including the system catalogue"
            )
        used.add(name)
        # point it at the CTE, aliased back to the name the query already uses
        alias = table.alias or name
        table.set("this", exp.to_identifier(_CTE_PREFIX + name))
        table.set("alias", exp.TableAlias(this=exp.to_identifier(alias)))

    for name in sorted(used):
        tree = tree.with_(_CTE_PREFIX + name, profile.render(name, cfg.profile_vars), copy=False)
    return tree.sql(dialect=dialect)


def guarded_query(cfg: Config, sql: str, params: dict | None = None,
                  row_cap: int | None = None) -> pd.DataFrame:
    """Run an ad-hoc read query over the CANONICAL entities, guarded and audited.

    Strict mode is the point: this SQL did not come from the operator's config,
    it came from an agent that may be repeating something it read in a database
    row. On top of the usual guard it default-denies every function the guard
    cannot name, so a novel vendor built-in cannot talk its way through - and
    `scope_to_canonical` means it can only read what the profile defines.
    """

    from . import week_calendar as wc
    from .connect import _SQLGLOT_DIALECT, assert_read_only, server_today

    profile, engine, auditor = _prepare(cfg)
    dialect = _SQLGLOT_DIALECT.get(engine.dialect.name)

    # The agent's own SQL, strictly, BEFORE it is composed with the operator's -
    # so a profile using some vendor function the guard cannot name doesn't
    # loosen the policy applied to the agent, and the error names the right SQL.
    assert_read_only(sql, dialect=dialect, strict=True)
    scoped = scope_to_canonical(profile, cfg, sql, dialect)

    params = dict(params or {})
    if ":since" in scoped and "since" not in params:
        as_of = server_today(engine, auditor)
        params["since"] = wc.window_start(as_of, cfg.lookback_weeks).isoformat()

    # the composite is re-guarded by safe_read, non-strict: the profile half is
    # the operator's own SQL and they are entitled to their vendor functions
    return safe_read(engine, auditor, "ad-hoc", scoped, params,
                     row_cap if row_cap is not None else cfg.row_cap)
