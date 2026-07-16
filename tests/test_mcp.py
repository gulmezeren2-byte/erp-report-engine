"""The guarded ERP MCP server. Logic is tested without the MCP runtime; a smoke
test builds the FastMCP server when the optional `mcp` extra is installed."""

from __future__ import annotations

import pytest

from erp_report_engine.config import Config, load_config
from erp_report_engine.errors import EngineError
from erp_report_engine.mcp_server import (
    _UNTRUSTED,
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
    assert set(d["entities"]) == {"orders", "order_lines", "inventory"}
    assert "order_id" in d["entities"]["orders"]["columns"]


def test_check_query_allows_select_blocks_write():
    assert _check_query("SELECT * FROM orders")["allowed"] is True
    bad = _check_query("DROP TABLE orders")
    assert bad["allowed"] is False and bad["reason"]


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
    assert set(r["reconciliation"]) == {"orders", "order_lines", "inventory"}


def test_build_server_registers_tools(demo_cfg):
    pytest.importorskip("mcp")
    from erp_report_engine.mcp_server import build_server
    server = build_server(demo_cfg)
    assert server is not None
