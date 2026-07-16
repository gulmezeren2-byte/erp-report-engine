"""Declarative profile contracts: each check type flags its violations with the
right severity, and clean data stays silent."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from erp_report_engine.contracts import evaluate


def _prof(contract):
    return SimpleNamespace(contract=contract)


def test_not_null_is_warned():
    frames = {"orders": pd.DataFrame({"order_id": ["A", None], "net_total": [1, 2]})}
    out = evaluate(_prof({"orders": {"not_null": ["order_id"]}}), frames)
    assert out == [("warn", "contract[orders]: 1 rows have a null order_id")]


def test_accepted_values_with_fail_severity():
    frames = {"orders": pd.DataFrame({"status": ["open", "weird"]})}
    out = evaluate(_prof({"orders": {"severity": "fail",
                                     "accepted_values": {"status": ["open", "closed"]}}}), frames)
    assert out and out[0][0] == "fail" and "outside" in out[0][1]


def test_unique_violation():
    frames = {"orders": pd.DataFrame({"order_id": ["A", "A", "B"]})}
    out = evaluate(_prof({"orders": {"unique": "order_id"}}), frames)
    assert any("duplicate order_id" in t for _, t in out)


def test_relationship_orphans():
    frames = {"orders": pd.DataFrame({"order_id": ["A"]}),
              "order_lines": pd.DataFrame({"order_id": ["A", "Z"]})}
    out = evaluate(_prof({"order_lines": {"relationships": {"order_id": "orders"}}}), frames)
    assert any("does not exist" in t for _, t in out)


def test_min_rows():
    frames = {"orders": pd.DataFrame({"order_id": []})}
    out = evaluate(_prof({"orders": {"min_rows": 1}}), frames)
    assert any("below min_rows" in t for _, t in out)


def test_clean_data_is_silent():
    frames = {"orders": pd.DataFrame({"order_id": ["A", "B"], "status": ["open", "closed"]})}
    out = evaluate(_prof({"orders": {"not_null": ["order_id"],
                                     "accepted_values": {"status": ["open", "closed"]}}}), frames)
    assert out == []
