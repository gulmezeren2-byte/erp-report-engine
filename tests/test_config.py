"""The config loader must refuse a password embedded in the connection URL,
in every shape a real driver accepts - not just user:pass@host."""

from __future__ import annotations

import pytest

from erp_report_engine.config import ConfigError, _reject_embedded_credential


@pytest.mark.parametrize("url", [
    "postgresql://user:secret@host/db",                                  # classic
    "postgresql://user@host/db?password=secret",                         # query param
    "postgresql://user@host/db?pwd=secret",                              # short query param
    "mssql+pyodbc:///?odbc_connect=DRIVER%3DODBC%3BUID%3Dsa%3BPWD%3Dhunter2",  # pyodbc, no @
])
def test_rejects_embedded_credentials(url):
    with pytest.raises(ConfigError):
        _reject_embedded_credential(url)


@pytest.mark.parametrize("url", [
    "sqlite:///C:/data/demo.db",
    "postgresql://readonly_user@host/db",
    "mssql+pyodbc://@server/db?driver=ODBC+Driver+17+for+SQL+Server",
])
def test_allows_credential_free_urls(url):
    _reject_embedded_credential(url)  # must not raise


# --- a typo must not become a default nobody chose ---
# `.get(key, default)` fails silently: `lookback_week` (singular) parses fine,
# changes nothing, and the operator concludes the setting is broken. For an
# unattended report, a setting that quietly did not apply is the same class of
# problem as a number nobody can trace.

def _write_cfg(tmp_path, **sections) -> str:
    import yaml
    base = {"connection": {"url": "sqlite:///demo.db"}, "profile": "generic"}
    base.update(sections)
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(base), encoding="utf-8")
    return str(p)


def test_a_valid_config_still_loads(tmp_path):
    from erp_report_engine.config import load_config
    cfg = load_config(_write_cfg(tmp_path, report={"lookback_weeks": 13, "company_alias": "X"}))
    assert cfg.lookback_weeks == 13 and cfg.company_alias == "X"


@pytest.mark.parametrize(("section", "block", "typo"), [
    ("report", {"lookback_week": 13}, "lookback_weeks"),        # singular
    ("report", {"low_cover_week": 3}, "low_cover_weeks"),
    ("limits", {"row_caps": 10}, "row_cap"),
    ("narrative", {"include_name": True}, "include_names"),
])
def test_a_mistyped_key_is_refused_and_the_right_one_suggested(tmp_path, section, block, typo):
    from erp_report_engine.config import load_config
    with pytest.raises(ConfigError) as e:
        load_config(_write_cfg(tmp_path, **{section: block}))
    assert "unknown config key" in str(e.value)
    assert typo in str(e.value)                 # and it names the key that was meant


def test_a_mistyped_top_level_key_is_refused(tmp_path):
    from erp_report_engine.config import load_config
    with pytest.raises(ConfigError, match="profile"):
        load_config(_write_cfg(tmp_path, profil="generic"))


def test_a_non_numeric_number_names_its_own_key(tmp_path):
    from erp_report_engine.config import load_config
    with pytest.raises(ConfigError, match="lookback_weeks must be a number"):
        load_config(_write_cfg(tmp_path, report={"lookback_weeks": "abc"}))
