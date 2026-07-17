"""The trust benchmark's *contrast*, pinned as a fact.

The results page and the `trust-benchmark` CLI both claim that the naive checks
real tools ship - "does it start with SELECT?", "does it contain a write word?" -
walk straight past most of the corpus, while this project's guard clears all of
it. That claim is only honest if it is measured, so these tests measure it: the
real guard strictly dominates every baseline, and the two specific failure modes
the page describes in prose are the failures the code actually produces.

If a future change made a baseline pass the whole corpus, the benchmark would no
longer distinguish anything - so "the baseline is strictly worse" is itself a
tested invariant, not a hope.
"""

from __future__ import annotations

import pytest

from erp_report_engine.attack_corpus import CASES, compare, run, summarize
from erp_report_engine.baseline_guards import (
    baselines,
    starts_with_select,
    write_keyword_blocklist,
)
from erp_report_engine.connect import ReadOnlyViolation, assert_read_only

_SQL = {c.name: c for c in CASES}


def test_our_guard_is_perfect_on_the_corpus():
    """The headline the whole page rests on: every attack refused, every read allowed."""
    s = summarize(run(assert_read_only))
    assert s["all_correct"] is True
    assert s["attacks_blocked"] == s["attacks_total"]
    assert s["reads_allowed"] == s["reads_total"]


@pytest.mark.parametrize("guard", list(baselines().values()), ids=list(baselines()))
def test_every_baseline_is_strictly_worse(guard):
    """Each naive guard misses at least one attack the real guard catches. If one
    ever stopped missing anything, the corpus would no longer tell them apart -
    which is exactly the regression this pins."""
    s = summarize(run(guard))
    assert s["all_correct"] is False
    assert s["attacks_blocked"] < s["attacks_total"]


def test_shape_check_lets_select_shaped_side_effects_through():
    """The core claim: a first-keyword check waves a file-reading SELECT past, and
    a write hidden behind a read, and a write inside a CTE - all lead with the
    'right' keyword. The real guard refuses every one of them."""
    for name in ("pg_read_file", "xp_cmdshell", "two_statements", "cte_insert", "select_into"):
        sql, dialect = _SQL[name].sql, _SQL[name].dialect
        starts_with_select(sql, dialect=dialect)  # baseline: no exception -> allowed
        with pytest.raises(ReadOnlyViolation):
            assert_read_only(sql, dialect=dialect)  # ours: refused


def test_keyword_scan_is_unsafe_and_brittle_at_once():
    """The keyword blocklist misses the functions that carry no write word, yet
    trips on a write word inside a string literal - unsafe and unusable together."""
    # misses a file read (no blocklisted word anywhere in it)
    write_keyword_blocklist(_SQL["pg_read_file"].sql, dialect="postgres")
    # but blocks a legitimate read because 'delete' appears inside the string
    read = _SQL["literal_keyword"]
    with pytest.raises(ReadOnlyViolation):
        write_keyword_blocklist(read.sql, dialect=read.dialect)
    # ...which the real guard correctly allows (the keyword is data, not code)
    assert_read_only(read.sql, dialect=read.dialect)


def test_starts_with_select_is_redos_safe():
    """A pathological comment-like string is refused promptly, not exponentially.
    Regression for a ReDoS in the first cut of the head regex (nested quantifiers
    over `/*...*/`); if the linear form is ever undone, this hangs the suite."""
    evil = "/*" + "*//*" * 10000
    with pytest.raises(ReadOnlyViolation):
        starts_with_select(evil)


def test_starts_with_select_still_allows_every_real_read():
    """It is unsafe, not useless: the lenient shape check does pass all the reads
    (that is why it gets shipped). The danger is entirely in what it also passes."""
    s = summarize(run(starts_with_select))
    assert s["reads_allowed"] == s["reads_total"]


def test_compare_returns_one_labeled_row_per_guard():
    rows = compare({**baselines(), "this guard": assert_read_only})
    assert [r["guard"] for r in rows] == [*baselines(), "this guard"]
    for r in rows:
        assert {"attacks_blocked", "attacks_total", "reads_allowed", "reads_total"} <= set(r)
    # the last row is ours, and it is the only perfect one
    assert rows[-1]["all_correct"] is True
    assert all(r["all_correct"] is False for r in rows[:-1])
