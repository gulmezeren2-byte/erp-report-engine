"""The runner facade is the seam the CLI and the MCP server both consume.
guarded_query is what an agent will call, so its guard must hold here too."""

from __future__ import annotations

import pytest

from erp_report_engine.config import Config
from erp_report_engine.errors import EngineError
from erp_report_engine.runner import guarded_query

_CFG = Config(db_url="sqlite:///:memory:", profile_path="generic")


def test_guarded_query_allows_a_select():
    df = guarded_query(_CFG, "SELECT 1 AS x")
    assert int(df.iloc[0, 0]) == 1


@pytest.mark.parametrize("sql", ["DROP TABLE t", "DELETE FROM t", "SELECT 1; DELETE FROM t"])
def test_guarded_query_blocks_writes(sql):
    with pytest.raises(EngineError):
        guarded_query(_CFG, sql)
