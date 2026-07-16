"""Exit codes are a contract: a scheduler must be able to branch on WHY a run
failed, not just that it did. These drive the real CLI as a subprocess."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, "-m", "erp_report_engine", *args],
        capture_output=True, text=True, encoding="utf-8", cwd=str(cwd or ROOT),
    )


def test_missing_config_exits_2(tmp_path):
    proc = _run("validate", "-c", str(tmp_path / "nope.yaml"))
    assert proc.returncode == 2, proc.stdout + proc.stderr  # ConfigError


def test_embedded_password_exits_2(tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "connection:\n  url: postgresql://user:secret@host/db\nprofile: generic\n",
        encoding="utf-8",
    )
    proc = _run("validate", "-c", str(cfg))
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_unknown_profile_exits_4(tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "connection:\n  url: sqlite:///nonexistent.db\nprofile: no_such_erp\n",
        encoding="utf-8",
    )
    proc = _run("validate", "-c", str(cfg))
    assert proc.returncode == 4, proc.stdout + proc.stderr  # ContractError (ProfileError)


def test_result_json_on_stdout_logs_on_stderr():
    # build the demo, then run: stdout must be pure JSON, logs go to stderr
    build = subprocess.run([sys.executable, str(ROOT / "demo" / "build_demo_db.py")],
                           capture_output=True, text=True, cwd=str(ROOT))
    assert build.returncode == 0, build.stderr
    proc = _run("-v", "run", "-c", str(ROOT / "config.demo.yaml"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    import json
    payload = json.loads(proc.stdout)          # stdout parses cleanly as JSON
    assert "report" in payload
    assert "starting" in proc.stderr           # the log line landed on stderr, not stdout
