"""Sogedo authentication and API client.

Sogedo's customer portal uses Azure AD B2C. Device-code and ROPC flows are
disabled, so we drive the portal's own sign-in page: post the email/password
to the B2C SelfAsserted endpoint, then follow the confirmation redirect to get
an authorization code. The refresh token is used to mint short-lived access
tokens (valid 1h); when it expires, the client signs in again with the stored
credentials.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

_LOGGER = logging.getLogger(__name__)

# Azure AD B2C configuration (reverse-engineered from mon-compte.sogedo.fr)
AUTHORITY = (
    "https://login.mon-compte.sogedo.fr/aelb2cprod.onmicrosoft.com/b2c_1a_signup_signin"
)
CLIENT_ID = "f2889c1f-a3a8-486a-9465-9e279e83ae18"
SCOPE = (
    "openid profile offline_access "
    "https://aelb2cprod.onmicrosoft.com/f2889c1f-a3a8-486a-9465-9e279e83ae18/read"
)
REDIRECT_URI = "https://mon-compte.sogedo.fr/auth"
API_BASE = "https://mon-compte.sogedo.fr/api"

TOKEN_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/token"
AUTHORIZE_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/authorize"
SELF_ASSERTED_ENDPOINT = f"{AUTHORITY}/SelfAsserted"
CONFIRM_ENDPOINT = f"{AUTHORITY}/api/CombinedSigninAndSignup/confirmed"
POLICY = "B2C_1A_signup_signin"


class SogedoAuthError(Exception):
    """Raised when authentication fails."""


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(code_challenge: str, state: str) -> str:
    """Build the interactive authorization URL the user opens to log in."""
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "response_mode": "query",
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_ENDPOINT}?{urlencode(params)}"


def exchange_code(
    code: str, code_verifier: str, session: requests.Session | None = None
) -> dict[str, Any]:
    """Exchange an authorization code for tokens. Returns the token dict."""
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
        "scope": SCOPE,
    }
    resp = (session or requests).post(
        TOKEN_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    body = resp.json()
    if "access_token" not in body:
        raise SogedoAuthError(f"Code exchange failed: {body.get('error_description', body)}")
    return body


def parse_login_settings(html: str) -> tuple[str, str]:
    """Return (csrf, transaction id) from the B2C sign-in page.

    SETTINGS is a JS object literal (it contains functions), so a JSON parser
    cannot read it; the two values we need are plain quoted strings.
    """
    csrf = re.search(r'"csrf":"([^"]+)"', html)
    tx = re.search(r'"transId":"([^"]+)"', html)
    if not csrf or not tx:
        raise SogedoAuthError("Sogedo login page format changed")
    return csrf.group(1), tx.group(1)


def login(
    email: str, password: str, session: requests.Session | None = None
) -> dict[str, Any]:
    """Sign in with email/password and return the token response."""
    session = session or requests.Session()
    verifier, challenge = generate_pkce()
    page = session.get(
        build_authorize_url(challenge, "sogedo-" + challenge[:8]), timeout=30
    )
    page.raise_for_status()
    csrf, tx = parse_login_settings(page.text)

    headers = {
        "X-CSRF-TOKEN": csrf,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": "https://mon-compte.sogedo.fr",
        "Referer": page.url,
    }
    resp = session.post(
        SELF_ASSERTED_ENDPOINT,
        params={"tx": tx, "p": POLICY},
        data={"request": tx, "signInName": email, "password": password},
        headers=headers,
        timeout=30,
    )
    # A failed sign-in returns two concatenated JSON objects, so a strict JSON
    # parse is unsafe; the status and message are still greppable.
    if '"status":"200"' not in resp.text:
        message = re.search(r'"message":"([^"]*)"', resp.text)
        raise SogedoAuthError(
            message.group(1) if message else "Invalid email or password"
        )

    confirmed = session.post(
        CONFIRM_ENDPOINT,
        params={"rememberMe": "false", "csrf_token": csrf, "tx": tx, "p": POLICY},
        headers=headers,
        allow_redirects=False,
        timeout=30,
    )
    query = parse_qs(urlparse(confirmed.headers.get("location", "")).query)
    code = (query.get("code") or [None])[0]
    if not code:
        detail = (query.get("error_description") or ["no code in redirect"])[0]
        raise SogedoAuthError(f"Sogedo sign-in failed: {detail}")
    return exchange_code(code, verifier, session)


class SogedoClient:
    """Thin client over the Sogedo API with refresh-token auth."""

    def __init__(
        self,
        email: str,
        password: str,
        refresh_token: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._email = email
        self._password = password
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._access_expires_at = 0.0
        self._session = session or requests.Session()

    # -- token handling ----------------------------------------------------

    def _ensure_access_token(self) -> str:
        if self._access_token and time.time() < self._access_expires_at - 60:
            return self._access_token
        if self._refresh_token and self._refresh():
            return self._access_token
        self._sign_in()
        return self._access_token

    def _refresh(self) -> bool:
        """Try the refresh grant; return False when the token has lapsed."""
        data = {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "scope": SCOPE,
            "refresh_token": self._refresh_token,
        }
        resp = self._session.post(
            TOKEN_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        body = resp.json()
        if "access_token" not in body:
            _LOGGER.debug("Sogedo refresh token rejected; signing in again")
            return False
        self._store_tokens(body)
        return True

    def _sign_in(self) -> None:
        self._store_tokens(login(self._email, self._password, self._session))

    def _store_tokens(self, body: dict[str, Any]) -> None:
        self._access_token = body["access_token"]
        self._access_expires_at = time.time() + int(body.get("expires_in", 3600))
        if body.get("refresh_token"):
            self._refresh_token = body["refresh_token"]

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    # -- API calls ----------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = self._ensure_access_token()
        resp = self._session.get(
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params,
            timeout=30,
        )
        if resp.status_code == 401:
            # Force a fresh token once on auth errors.
            self._access_token = None
            token = self._ensure_access_token()
            resp = self._session.get(
                f"{API_BASE}{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                params=params,
                timeout=30,
            )
        resp.raise_for_status()
        return resp.json()

    def get_subscriptions(self) -> list[dict[str, Any]]:
        """Return the subscriptions for the logged-in contact."""
        # Contact id is present in the JWT as extension_HermesID.
        contact_id = self._jwt_claim("extension_HermesID")
        return self._get(f"/Contacts/getSubscriptions/{contact_id}")

    def get_daily_consumption(
        self, subscription_id: str, start: str, end: str
    ) -> list[dict[str, Any]]:
        """Return daily consumption between ISO dates (YYYY-MM-DD)."""
        s = _to_b2c_date(start)
        e = _to_b2c_date(end)
        return self._get(
            f"/Consumption/GetDailyMeterConsumption/{subscription_id}",
            params={"startDate": s, "endDate": e},
        )

    def _jwt_claim(self, name: str) -> str | None:
        token = self._ensure_access_token()
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload))
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not decode access token claims")
            return None
        return claims.get(name)


def _to_b2c_date(iso_date: str) -> str:
    """Convert 'YYYY-MM-DD' to the B2C date format 'Y, M, D'."""
    year, month, day = iso_date.split("-")
    return f"{year}, {month}, {day.lstrip('0') or '0'}"


def select_latest(entries: list[dict]) -> dict | None:
    """Return the most recent day with an actual consumption reading.

    Skips days where no index is available yet (future days) or where the
    consumption is still zero/not published.
    """
    for e in reversed(entries):
        if e.get("isIndexValueAvailable") and e.get("consumptionValue"):
            return e
    return entries[-1] if entries else None
