"""OSM OAuth 2.0 client + token management.

Two phases:

1. Connect flow (one-time): the admin clicks Connect OSM, we redirect
   them to OSM's authorize URL with our client_id + scope. OSM bounces
   them back to our /admin/osm/callback with ?code=... We exchange the
   code for an access_token + refresh_token and save the tokens to the
   single-row osm_credentials table. We also fetch /api/0.6/user/details
   so we can show "Connected as DispatchZero" in the admin UI.

2. Token refresh (every API call): access tokens expire (OSM issues
   them with ~2 hour TTLs). Before each publish we check expiry and
   refresh if we have <60s left, using the long-lived refresh_token.

CSRF protection on the connect flow: we generate a signed state token
(URLSafeTimedSerializer, same trick the session cookie uses) before
redirecting to OSM. On callback we verify the state matches what we
issued. Without this, an attacker could trick an admin into
authorizing a different account.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.config import Settings
from dispatchzero.crypto import decrypt_token, encrypt_token
from dispatchzero.models import OsmCredentials

log = logging.getLogger(__name__)

# OAuth scopes. Must match exactly what we ticked at app registration
# time. read_prefs lets us read /user/details (to confirm the connected
# account identity); write_api lets us create changesets and nodes.
_SCOPES = "read_prefs write_api"

# Refresh access tokens this many seconds before they're due to expire,
# so a publish never races a token expiry.
_REFRESH_LEAD_SECONDS = 60


class OsmAuthError(RuntimeError):
    """Raised when an OAuth or token operation fails. The route layer
    turns this into a 503 with the message."""


def _state_serializer(settings: Settings) -> URLSafeTimedSerializer:
    # Distinct salt so a leaked OAuth-state token can't be reused as a
    # session cookie or vice versa.
    return URLSafeTimedSerializer(settings.session_secret, salt="dz_osm_state_v1")


def build_authorize_url(settings: Settings) -> tuple[str, str]:
    """Construct the OSM authorize URL + a signed state token to set as
    a cookie. The callback verifies the cookie state matches the query
    state."""
    nonce = secrets.token_urlsafe(16)
    state = _state_serializer(settings).dumps(nonce)
    params = {
        "response_type": "code",
        "client_id": settings.osm_client_id,
        "redirect_uri": settings.osm_redirect_uri,
        "scope": _SCOPES,
        "state": state,
    }
    url = f"{settings.osm_oauth_base_url}/oauth2/authorize"
    qs = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
    return f"{url}?{qs}", state


def verify_state(settings: Settings, *, cookie_state: str, query_state: str) -> bool:
    """State token came back from OSM unmodified AND was issued by us
    within the last 10 minutes."""
    if not cookie_state or cookie_state != query_state:
        return False
    try:
        _state_serializer(settings).loads(cookie_state, max_age=600)
        return True
    except (BadSignature, SignatureExpired):
        return False


async def exchange_code_for_tokens(
    settings: Settings, *, code: str
) -> dict[str, Any]:
    """POST /oauth2/token with the authorization_code grant. OSM
    responds with { access_token, refresh_token, expires_in, ... }."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.osm_redirect_uri,
        "client_id": settings.osm_client_id,
        "client_secret": settings.osm_client_secret,
    }
    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": settings.osm_user_agent},
    ) as client:
        r = await client.post(
            f"{settings.osm_oauth_base_url}/oauth2/token", data=data,
        )
    if r.status_code != 200:
        log.error("OSM token exchange failed: %s %s", r.status_code, r.text)
        raise OsmAuthError(f"OSM token exchange failed ({r.status_code})")
    return r.json()


async def _refresh_tokens(
    settings: Settings, *, refresh_token: str,
) -> dict[str, Any]:
    """Trade a refresh_token for a fresh access_token (+ refresh_token).
    OSM rotates refresh tokens, so we always save the new one."""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.osm_client_id,
        "client_secret": settings.osm_client_secret,
    }
    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": settings.osm_user_agent},
    ) as client:
        r = await client.post(
            f"{settings.osm_oauth_base_url}/oauth2/token", data=data,
        )
    if r.status_code != 200:
        log.error("OSM token refresh failed: %s %s", r.status_code, r.text)
        raise OsmAuthError(
            f"OSM token refresh failed ({r.status_code}) — "
            "you may need to Connect OSM again."
        )
    return r.json()


async def _fetch_user_details(
    settings: Settings, *, access_token: str,
) -> tuple[int | None, str | None]:
    """Pull (osm_user_id, osm_username) from /api/0.6/user/details.json so
    we can show the connected identity in the admin UI. Best-effort —
    failure here doesn't break the connect flow."""
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={
                "User-Agent": settings.osm_user_agent,
                "Authorization": f"Bearer {access_token}",
            },
        ) as client:
            r = await client.get(f"{settings.osm_base_url}/api/0.6/user/details.json")
        if r.status_code != 200:
            log.warning("OSM user/details fetch failed: %s", r.status_code)
            return None, None
        body = r.json()
        user = body.get("user") or {}
        return user.get("id"), user.get("display_name")
    except (httpx.HTTPError, ValueError) as e:
        log.warning("OSM user/details fetch error: %s", e)
        return None, None


async def save_credentials(
    db: AsyncSession,
    settings: Settings,
    *,
    token_response: dict,
) -> OsmCredentials:
    """Persist (or replace) the singleton osm_credentials row from a
    fresh token-response payload. Also enriches with user-identity bits."""
    access_token = token_response["access_token"]
    refresh_token = token_response.get("refresh_token", "")
    expires_in = int(token_response.get("expires_in", 7200))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    osm_user_id, osm_username = await _fetch_user_details(
        settings, access_token=access_token,
    )

    # Encrypt both tokens before they touch the DB (see dispatchzero.crypto).
    enc_access = encrypt_token(access_token)
    enc_refresh = encrypt_token(refresh_token) if refresh_token else ""

    existing = (
        await db.execute(select(OsmCredentials).where(OsmCredentials.id == 1))
    ).scalar_one_or_none()
    if existing is None:
        creds = OsmCredentials(
            id=1,
            access_token=enc_access,
            refresh_token=enc_refresh,
            access_token_expires_at=expires_at,
            osm_user_id=osm_user_id,
            osm_username=osm_username,
        )
        db.add(creds)
    else:
        existing.access_token = enc_access
        # OSM rotates refresh_tokens. If they sent a new one, use it; if
        # they reused the old one (unusual), keep what we had.
        if enc_refresh:
            existing.refresh_token = enc_refresh
        existing.access_token_expires_at = expires_at
        existing.osm_user_id = osm_user_id
        existing.osm_username = osm_username
        existing.updated_at = datetime.now(timezone.utc)
        creds = existing
    await db.commit()
    await db.refresh(creds)
    return creds


async def get_credentials(db: AsyncSession) -> OsmCredentials | None:
    return (
        await db.execute(select(OsmCredentials).where(OsmCredentials.id == 1))
    ).scalar_one_or_none()


async def get_fresh_access_token(
    db: AsyncSession, settings: Settings,
) -> str:
    """Return a non-expired access token. Refreshes via refresh_token
    grant if the cached access_token has <60s left. Raises OsmAuthError
    if no credentials are stored at all."""
    creds = await get_credentials(db)
    if creds is None:
        raise OsmAuthError("OSM is not connected. Click Connect OSM first.")
    now = datetime.now(timezone.utc)
    expires_at = creds.access_token_expires_at
    if expires_at.tzinfo is None:
        # Defensive: PostgreSQL stores TZ but if a code path ever wrote
        # a naive datetime, treat it as UTC rather than crash on compare.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at - now > timedelta(seconds=_REFRESH_LEAD_SECONDS):
        return decrypt_token(creds.access_token)
    # Need to refresh. Decrypt the stored refresh token first.
    log.info("OSM access token expiring — refreshing")
    payload = await _refresh_tokens(
        settings, refresh_token=decrypt_token(creds.refresh_token),
    )
    creds_after = await save_credentials(db, settings, token_response=payload)
    return decrypt_token(creds_after.access_token)


async def clear_credentials(db: AsyncSession, settings: Settings | None = None) -> None:
    """Drop the stored credentials and best-effort revoke the token upstream
    so 'Disconnect' actually invalidates access at OSM rather than just
    making the local app forget. Revocation failure doesn't block the local
    delete — a stale-but-soon-expiring access token is acceptable."""
    creds = await get_credentials(db)
    if creds is None:
        return
    if settings is not None:
        try:
            await _revoke_token(settings, token=decrypt_token(creds.access_token))
        except Exception as e:  # noqa: BLE001 - revoke is best-effort
            log.warning("OSM token revoke failed (continuing with local delete): %s", e)
    await db.delete(creds)
    await db.commit()


async def _revoke_token(settings: Settings, *, token: str) -> None:
    """POST the OAuth2 token-revocation endpoint. OSM follows RFC 7009."""
    data = {
        "token": token,
        "client_id": settings.osm_client_id,
        "client_secret": settings.osm_client_secret,
    }
    async with httpx.AsyncClient(
        timeout=15.0, headers={"User-Agent": settings.osm_user_agent},
    ) as client:
        r = await client.post(
            f"{settings.osm_oauth_base_url}/oauth2/revoke", data=data,
        )
    if r.status_code not in (200, 204):
        log.warning("OSM token revoke returned %s", r.status_code)
