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
    # record this week BEFORE the streak so "declined N weeks" counts it (K6)
    state.record(kpis["this_week"], kpis, path)
    streak = state.streak("revenue")
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


def guarded_query(cfg: Config, sql: str, params: dict | None = None,
                  row_cap: int | None = None) -> pd.DataFrame:
    """Run an ad-hoc read query through the same guarded, audited path as the
    report, in STRICT mode. Returns the resulting DataFrame.

    Strict is the point: this SQL did not come from the operator's config, it
    came from an agent that may be repeating something it read in a database
    row. On top of the usual guard it default-denies every function the guard
    cannot name, so a novel vendor built-in cannot talk its way through.
    """
    profile, engine, auditor = _prepare(cfg)  # noqa: F841 - profile validates config
    return safe_read(engine, auditor, "ad-hoc", sql, params or {},
                     row_cap if row_cap is not None else cfg.row_cap,
                     strict=True)
