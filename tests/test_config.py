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
