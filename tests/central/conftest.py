"""tests/central: the central server refuses to start when the process
environment would leak the SinAuto client-certificate passphrase (DEBUG=pw:*)
or divert its connection (HTTPS/ALL proxy variables). A developer machine or
CI runner that happens to export one of those must not fail unrelated tests,
so they are cleared for every test here; tests that exercise the refusal set
them explicitly."""

import pytest

_CENTRAL_REFUSED_ENVIRONMENT = (
    "DEBUG", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy",
    "npm_config_https_proxy", "npm_config_proxy",
)


@pytest.fixture(autouse=True)
def _clean_mtls_environment(monkeypatch):
    for name in _CENTRAL_REFUSED_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
