"""The read-only guard, pinned against the bypasses an audit actually found.

The attack corpus lives in erp_report_engine.attack_corpus - ONE list, shared by
these tests, the `trust-benchmark` CLI, and the published results page, so the
number on the website is the number CI enforces here. Every side-effect case was
verified to PASS the guard before it grew a function check - a "read-only" guard
that inspected a statement's shape and never asked what it called.

The guard is tested per dialect. It used to be exercised only dialect-blind,
which is how tsql- and mysql-only constructs went unnoticed.
"""

from __future__ import annotations

import pytest

from erp_report_engine.attack_corpus import READS, SIDE_EFFECTS, WRITES
from erp_report_engine.connect import ReadOnlyViolation, assert_read_only

_ATTACKS = [*SIDE_EFFECTS, *WRITES]


@pytest.mark.parametrize("case", _ATTACKS, ids=[c.name for c in _ATTACKS])
def test_attack_is_refused(case):
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(case.sql, dialect=case.dialect)


@pytest.mark.parametrize("case", READS, ids=[c.name for c in READS])
def test_real_reads_still_pass(case):
    assert_read_only(case.sql, dialect=case.dialect)   # a guard that blocks real work is useless
    assert_read_only(case.sql, dialect=case.dialect, strict=True)


def test_corpus_all_correct_against_the_live_guard():
    """The trust benchmark's headline, pinned: every attack refused, every read
    allowed. This is what the results page publishes."""
    from erp_report_engine.attack_corpus import run, summarize
    s = summarize(run(assert_read_only))
    assert s["attacks_blocked"] == s["attacks_total"]
    assert s["reads_allowed"] == s["reads_total"]
    assert s["all_correct"]


def test_the_guard_fails_closed_when_it_cannot_parse():
    """A guard that cannot read a statement has nothing to say about it.

    This used to return silently on the theory that the lexical guard still held
    - but the lexical guard had never heard of OPENROWSET, and OPENROWSET is
    exactly what fails to parse.
    """
    with pytest.raises(ReadOnlyViolation, match="could not parse"):
        assert_read_only("SELECT * FROM t WHERE ((((", dialect="postgres")


def test_keywords_inside_string_literals_are_data_not_code():
    """The lexical scan blanks literals first. Blocking this taught users the
    guard was superstitious rather than principled - and superstition is what
    gets a guard switched off."""
    assert_read_only("SELECT 'please delete this note' AS note", dialect="postgres")
    assert_read_only("SELECT 'shipped into the warehouse' AS msg", dialect="postgres")
    assert_read_only("SELECT * FROM orders WHERE note = 'drop shipment'", dialect="postgres")


def test_a_column_named_like_a_dangerous_function_is_fine():
    assert_read_only("SELECT sleep FROM logs", dialect="mysql")


def test_strict_mode_default_denies_functions_the_guard_cannot_name():
    """The agent path. sqlglot's registry is the allowlist: it knows the portable
    analytic functions and nothing that reads a file or dials out."""
    vendor = "SELECT dbo.fn_Custom(1) FROM t"
    assert_read_only(vendor, dialect="tsql")                       # operator SQL: allowed
    with pytest.raises(ReadOnlyViolation, match="strict mode"):    # agent SQL: denied
        assert_read_only(vendor, dialect="tsql", strict=True)


def test_every_bundled_profile_passes_strict_mode():
    """The bundled profiles use no anonymous functions at all, which is what
    makes default-deny affordable rather than theoretical."""
    import re

    from erp_report_engine.connect import _SQLGLOT_DIALECT
    from erp_report_engine.semantic import bundled_profiles, load_profile

    names = bundled_profiles()
    assert {"generic", "logo_tiger", "netsis", "mikro"} <= set(names)
    for name in names:
        prof = load_profile(name)
        dialect = _SQLGLOT_DIALECT.get(prof.dialect)
        for entity, query in prof.entities.items():
            sql = re.sub(r"\{([A-Za-z0-9_]+)\}", "X", query)
            assert_read_only(sql, dialect=dialect, strict=True), f"{name}:{entity}"


def test_trust_benchmark_cli_reports_and_exits_clean(capsys):
    """The `trust-benchmark` command runs the corpus through the guard and
    reports it - the reproducible artifact behind the published page."""
    from types import SimpleNamespace

    from erp_report_engine.cli import cmd_trust_benchmark

    cmd_trust_benchmark(SimpleNamespace(json=False))
    human = capsys.readouterr().out
    assert "20/20 attacks refused" in human
    assert "6/6 reads allowed" in human
    assert "ALL CORRECT" in human

    cmd_trust_benchmark(SimpleNamespace(json=True))
    import json as _json
    payload = _json.loads(capsys.readouterr().out)
    assert payload["summary"]["all_correct"] is True
    assert payload["summary"]["attacks_blocked"] == payload["summary"]["attacks_total"]
    assert len(payload["cases"]) == 26         # 20 attacks + 6 reads, the whole corpus
