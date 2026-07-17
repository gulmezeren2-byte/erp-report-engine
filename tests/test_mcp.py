"""The guarded ERP MCP server. Logic is tested without the MCP runtime; a smoke
test builds the FastMCP server when the optional `mcp` extra is installed."""

from __future__ import annotations

import pytest

from erp_report_engine.config import Config, load_config
from erp_report_engine.errors import EngineError
from erp_report_engine.mcp_server import (
    _UNTRUSTED,
    _aging_report,
    _check_query,
    _describe_model,
    _query,
    _reconcile,
    _weekly_report,
)


@pytest.fixture(scope="module")
def demo_cfg(tmp_path_factory) -> Config:
    from erp_report_engine.demo_builder import build
    d = tmp_path_factory.mktemp("mcpdemo")
    cfg_path = build(target_dir=d)
    return load_config(str(cfg_path))


def test_describe_model_lists_canonical_entities(demo_cfg):
    d = _describe_model(demo_cfg)
    assert {"orders", "order_lines", "inventory"} <= set(d["entities"])
    assert "order_id" in d["entities"]["orders"]["columns"]
    assert d["entities"]["orders"]["required"] is True
    # the demo profile maps the optional receivables entity, flagged not-required
    assert "receivables" in d["entities"] and d["entities"]["receivables"]["required"] is False
    assert "due_date" in d["entities"]["receivables"]["columns"]


def test_aging_report_buckets_open_receivables(demo_cfg):
    a = _aging_report(demo_cfg)
    assert a["available"] is True
    assert a["total_open"] > 0 and 0 <= a["overdue_pct"] <= 100
    assert [b["bucket"] for b in a["buckets"]] == ["current", "1-30", "31-60", "61-90", "91+"]
    assert a["top_overdue_customers"]                 # a per-customer aggregate, not raw invoice rows
    assert a["_note"] == _UNTRUSTED


def test_check_query_allows_select_blocks_write(demo_cfg):
    assert _check_query(demo_cfg, "SELECT * FROM orders")["allowed"] is True
    bad = _check_query(demo_cfg, "DROP TABLE orders")
    assert bad["allowed"] is False and bad["reason"]


def test_check_query_answers_for_the_policy_query_actually_runs(demo_cfg):
    """check_query must not be more permissive than query, or it is a liar:
    'allowed', then refused on execution. Both are strict."""
    sql = "SELECT load_extension('evil.so')"
    assert _check_query(demo_cfg, sql)["allowed"] is False
    with pytest.raises(EngineError):        # ReadOnlyViolation is an EngineError
        _query(demo_cfg, sql)


def test_query_returns_rows_with_untrusted_note(demo_cfg):
    out = _query(demo_cfg, "SELECT order_id, net_total FROM orders", max_rows=5)
    assert out["columns"] == ["order_id", "net_total"]
    assert out["returned"] <= 5
    assert out["row_count"] >= out["returned"]
    assert out["_note"] == _UNTRUSTED           # every ERP-data result is framed as untrusted


def test_query_blocks_a_write(demo_cfg):
    with pytest.raises(EngineError):
        _query(demo_cfg, "DELETE FROM orders")


def test_weekly_report_carries_the_honesty_payload(demo_cfg):
    r = _weekly_report(demo_cfg)
    assert r["week"].startswith("20")
    assert r["findings"]
    assert r["reconciliation"]["orders"]["fetched"] >= 0
    assert r["audit_trail"] and "sql" in r["audit_trail"][0]
    assert r["_note"] == _UNTRUSTED


def test_reconcile_reports_a_verdict(demo_cfg):
    r = _reconcile(demo_cfg)
    assert r["verdict"] in ("OK", "MISMATCH - do not trust the numbers")
    # required entities always reconcile; the demo profile also maps receivables
    assert {"orders", "order_lines", "inventory"} <= set(r["reconciliation"])
    assert "receivables" in r["reconciliation"]


def test_build_server_registers_tools(demo_cfg):
    pytest.importorskip("mcp")
    from erp_report_engine.mcp_server import build_server
    server = build_server(demo_cfg)
    assert server is not None


# --- the semantic boundary: "the agent talks to `orders`, never LG_001_01_ORFICHE" ---
# That was true of every tool except the one that mattered. `query` passed raw SQL
# through, so an agent could read any table the login could reach and the semantic
# layer - the whole product - was optional. These pin it shut.

_OUT_OF_REACH = [
    ("raw_erp_table", "SELECT * FROM orders_raw"),
    ("system_catalogue", "SELECT name FROM sqlite_master"),
    ("qualified_name", "SELECT * FROM main.orders"),
    ("cte_shadowing_an_entity", "WITH orders AS (SELECT * FROM sqlite_master) SELECT * FROM orders"),
    ("cte_squatting_the_prefix", "WITH _erp_orders AS (SELECT 1 AS a) SELECT * FROM _erp_orders"),
]


@pytest.mark.parametrize(("name", "sql"), _OUT_OF_REACH, ids=[c[0] for c in _OUT_OF_REACH])
def test_query_cannot_escape_the_canonical_entities(demo_cfg, name, sql):
    with pytest.raises(EngineError):
        _query(demo_cfg, sql, max_rows=1)


def test_query_reads_canonical_entities_by_name(demo_cfg):
    """The entity names only exist in the profile - there is no `orders` table on
    a Logo Tiger database - so the scoping injects the profile's own SQL as CTEs.
    Without that the allowlist would be a way to make `query` useless."""
    out = _query(demo_cfg, "SELECT customer, SUM(net_total) AS rev FROM orders GROUP BY customer",
                 max_rows=5)
    assert out["columns"] == ["customer", "rev"]
    assert out["row_count"] > 0

    joined = _query(demo_cfg,
                    "SELECT o.customer, l.item_code FROM orders o "
                    "JOIN order_lines l ON l.order_id = o.order_id", max_rows=3)
    assert joined["columns"] == ["customer", "item_code"]
    assert joined["row_count"] > 0


def test_query_reaches_an_optional_entity_when_the_profile_maps_it(demo_cfg):
    out = _query(demo_cfg, "SELECT customer, open_amount FROM receivables", max_rows=3)
    assert out["columns"] == ["customer", "open_amount"]


def test_describe_model_is_a_semantic_layer_not_just_names(demo_cfg):
    """The agent gets meaning, not just column names - which is what puts a
    semantic layer on the correct side of the text-to-SQL accuracy line."""
    d = _describe_model(demo_cfg)
    o = d["entities"]["orders"]
    assert o["grain"] and o["examples"]                       # grain + example queries
    fields = {f["name"]: f for f in o["fields"]}
    assert fields["net_total"]["type"] == "number"
    assert "NULL" in fields["actual_ship_date"]["description"]  # the on-time gotcha is spelled out


def test_every_advertised_example_query_actually_runs(demo_cfg):
    """describe_model hands the agent example queries; if any didn't execute
    through the guarded path, we'd be teaching it to write broken SQL."""
    from erp_report_engine.semantic import CANONICAL_EXAMPLES
    for examples in CANONICAL_EXAMPLES.values():
        for sql in examples:
            out = _query(demo_cfg, sql, max_rows=2)
            assert "columns" in out and out["row_count"] >= 0   # ran, guarded, returned
