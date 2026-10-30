"""Tests for the Sogedo API helper logic."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "sogedo"


def _load_with_const(modname, filename, pkg_name):
    """Load a package submodule, stubbing its `const` relative import."""
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = []
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg

    const = types.ModuleType(f"{pkg_name}.const")
    const.__package__ = pkg_name
    sys.modules[f"{pkg_name}.const"] = const

    spec = importlib.util.spec_from_file_location(f"{pkg_name}.{modname}", filename)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = pkg_name
    sys.modules[f"{pkg_name}.{modname}"] = module
    spec.loader.exec_module(module)
    return module


api = _load_with_const("sogedo_api", BASE / "sogedo_api.py", "sogedo_api_pkg")
select_latest = api.select_latest
login = api.login
parse_login_settings = api.parse_login_settings
SogedoAuthError = api.SogedoAuthError
SogedoClient = api.SogedoClient

LOGIN_PAGE = 'var SETTINGS = {"api":"CombinedSigninAndSignup","csrf":"CSRF","transId":"TX=abc"};'
REDIRECT = "https://mon-compte.sogedo.fr/auth?code=CODE&state=sogedo-x"


class FakeResponse:
    def __init__(self, *, text="", status_code=200, headers=None, url=""):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url

    def raise_for_status(self):
        assert self.status_code < 400

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """Stand-in for requests.Session, routed by endpoint."""

    def __init__(self, *, refresh_ok=False, sign_in_text='{"status":"200"}'):
        self.refresh_ok = refresh_ok
        self.sign_in_text = sign_in_text
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return FakeResponse(text=LOGIN_PAGE, url=url)

    def post(self, url, **kwargs):
        data = kwargs.get("data") or {}
        self.calls.append(("POST", url, data))
        if url == api.TOKEN_ENDPOINT:
            if data.get("grant_type") == "refresh_token" and not self.refresh_ok:
                return FakeResponse(text='{"error":"invalid_grant"}')
            body = {"access_token": "ACCESS", "refresh_token": "REFRESH", "expires_in": 3600}
            return FakeResponse(text=json.dumps(body))
        if url == api.SELF_ASSERTED_ENDPOINT:
            return FakeResponse(text=self.sign_in_text)
        if url == api.CONFIRM_ENDPOINT:
            return FakeResponse(headers={"location": REDIRECT})
        raise AssertionError(f"unexpected POST {url}")


def test_select_latest_skips_unavailable_and_zero_days():
    entries = [
        {"isIndexValueAvailable": True, "consumptionValue": 0.3, "indexDate": "2026-08-16"},
        {"isIndexValueAvailable": True, "consumptionValue": 0.0, "indexDate": "2026-08-17"},
        {"isIndexValueAvailable": False, "consumptionValue": 0.0, "indexDate": "2026-08-18"},
        {"isIndexValueAvailable": False, "consumptionValue": 0.0, "indexDate": "2026-08-19"},
    ]
    assert select_latest(entries)["indexDate"] == "2026-08-16"


def test_select_latest_falls_back_to_last_entry():
    entries = [
        {"isIndexValueAvailable": False, "consumptionValue": 0.0, "indexDate": "2026-08-01"},
        {"isIndexValueAvailable": False, "consumptionValue": 0.0, "indexDate": "2026-08-02"},
    ]
    assert select_latest(entries)["indexDate"] == "2026-08-02"


def test_select_latest_empty():
    assert select_latest([]) is None


def test_parse_login_settings():
    assert parse_login_settings(LOGIN_PAGE) == ("CSRF", "TX=abc")


def test_parse_login_settings_rejects_unknown_page():
    with pytest.raises(SogedoAuthError):
        parse_login_settings("<html>nope</html>")


def test_login_posts_credentials_and_returns_tokens():
    session = FakeSession()
    tokens = login("user@example.com", "secret", session)
    assert tokens["refresh_token"] == "REFRESH"
    (_, url, data) = next(c for c in session.calls if c[1] == api.SELF_ASSERTED_ENDPOINT)
    assert data["signInName"] == "user@example.com"
    assert data["password"] == "secret"


def test_login_rejects_bad_credentials():
    session = FakeSession(
        sign_in_text='{"status":"400"}{"status":"400","message":"Identifiants invalides"}'
    )
    with pytest.raises(SogedoAuthError, match="Identifiants invalides"):
        login("user@example.com", "wrong", session)


def test_client_uses_valid_refresh_token():
    session = FakeSession(refresh_ok=True)
    client = SogedoClient("user@example.com", "secret", "GOOD", session)
    assert client._ensure_access_token() == "ACCESS"
    assert not [c for c in session.calls if c[0] == "GET"]


def test_client_signs_in_when_refresh_token_lapsed():
    session = FakeSession(refresh_ok=False)
    client = SogedoClient("user@example.com", "secret", "STALE", session)
    assert client._ensure_access_token() == "ACCESS"
    assert client.refresh_token == "REFRESH"
