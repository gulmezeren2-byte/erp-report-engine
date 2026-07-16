"""Engine tests: the read-only guard, the profile contracts, and a full
end-to-end run against the bundled demo database."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from erp_report_engine.connect import ReadOnlyViolation, assert_read_only  # noqa: E402
from erp_report_engine.semantic import ProfileError, load_profile  # noqa: E402


# ------------------------------------------------------------ guard ---------
@pytest.mark.parametrize("sql", [
    "INSERT INTO x VALUES (1)",
    "UPDATE orders SET a=1",
    "DELETE FROM orders",
    "DROP TABLE orders",
    "SELECT 1; DELETE FROM orders",
    "SELECT * FROM t -- sneaky",
    "SELECT * FROM t /* block */",
    "SELECT * FROM t # mysql comment",
    "EXEC sp_who",
    "SELECT * INTO backup FROM orders",
    "SELECT 1; ROLLBACK",                        # transaction-control splice
    "SELECT 1;\nCOMMIT",
    "SELECT * FROM orders WITH (TABLOCKX)",       # write-escalating lock hint
    "SELECT * FROM orders WITH (UPDLOCK)",
    "WITH x AS (DELETE FROM orders RETURNING 1) SELECT * FROM x",  # write hidden in a CTE
])
def test_guard_blocks_writes_and_tricks(sql):
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(sql)


def test_guard_allows_real_read_queries():
    assert_read_only("SELECT a, b FROM t WHERE d >= :since")
    assert_read_only("WITH x AS (SELECT 1 AS a) SELECT * FROM x")
    assert_read_only("SELECT a FROM t UNION SELECT a FROM u")
    assert_read_only("SELECT COUNT(*) FROM ( SELECT 1 AS a ) t")


# ---------------------------------------------------------- profiles --------
def test_profiles_load_and_are_read_only():
    for name in ("generic", "logo_tiger", "netsis"):   # bundled by name, no path
        prof = load_profile(name)
        assert set(prof.entities) == {"orders", "order_lines", "inventory"}


def test_bundled_profiles_discoverable():
    from erp_report_engine.semantic import bundled_profiles
    assert {"generic", "logo_tiger", "netsis"} <= set(bundled_profiles())


def test_unknown_profile_is_rejected():
    with pytest.raises(ProfileError):
        load_profile("no_such_erp")


def test_profile_var_injection_is_rejected():
    prof = load_profile("logo_tiger")
    with pytest.raises(ProfileError):
        prof.render("orders", {"firm_no": "001; DROP TABLE x", "period_no": "01"})


# ------------------------------------------------------------- e2e ----------
def _run_cli(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "erp_report_engine", *args],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
    )


def test_end_to_end_on_demo_db(tmp_path):
    build = subprocess.run([sys.executable, str(ROOT / "demo" / "build_demo_db.py")],
                           capture_output=True, text=True, cwd=ROOT)
    assert build.returncode == 0, build.stderr

    proc = _run_cli("run", "-c", str(ROOT / "config.demo.yaml"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)

    assert payload["findings"], "the insight engine must always produce findings"
    assert payload["queries_executed"] >= 6  # 3 entities + 3 reconciliation counts
    assert any("duplicated" in i for i in payload["data_quality_issues"]), \
        "the seeded duplicate orders must be caught by the quality gate"

    report = ROOT / payload["report"]
    assert report.exists()
    html = report.read_text(encoding="utf-8")
    for marker in ("SQL audit trail", "Source reconciliation", "read-only"):
        assert marker in html


def test_validate_command():
    proc = _run_cli("validate", "-c", str(ROOT / "config.demo.yaml"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["entities"]["orders"]["fetched"] == payload["entities"]["orders"]["source_count"]
