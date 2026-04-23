"""
Authentication — Two-tier (admin/viewer) HMAC-based auth.
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

from fastapi import HTTPException, Request, WebSocket, status

from backend.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_SECONDS = 86400  # 24 hours
VIEWER_MESSAGE_LIMIT = 10


def _generate_token(username: str, role: str, password: str) -> str:
    """Sign a token encoding username and role using HMAC-SHA256."""
    timestamp = str(int(time.time()))
    payload = json.dumps({"ts": timestamp, "v": 2, "role": role, "username": username},
                         separators=(",", ":"))
    signature = hmac.new(password.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + signature


def _verify_token(token: str) -> Optional[dict]:
    """
    Verify token signature + expiry.
    Returns the decoded payload dict on success, None otherwise.
    """
    settings = get_settings()
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None

        payload_b64, signature = parts
        payload = base64.urlsafe_b64decode(payload_b64).decode()
        data = json.loads(payload)

        role = data.get("role", "")
        username = data.get("username", "")

        # Look up the expected password for this user
        if role == "admin" and username == settings.admin_username:
            password = settings.admin_password
        elif role == "viewer" and username == settings.viewer_username:
            password = settings.viewer_password
        else:
            return None

        expected_sig = hmac.new(
            password.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None

        ts = int(data.get("ts", 0))
        if time.time() - ts > TOKEN_EXPIRY_SECONDS:
            return None

        return data
    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return None


def verify_credentials(username: str, password: str) -> Optional[str]:
    """
    Verify username + password. Returns a signed token string on success, None otherwise.
    """
    settings = get_settings()

    if username == settings.admin_username and password == settings.admin_password:
        token = _generate_token(username, "admin", password)
        logger.info(f"Admin login: {username}")
        return token

    if username == settings.viewer_username and password == settings.viewer_password:
        token = _generate_token(username, "viewer", password)
        logger.info(f"Viewer login: {username}")
        return token

    logger.warning(f"Failed login attempt for username: {username!r}")
    return None


def _extract_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.query_params.get("token") or None


async def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency — verifies any valid token (admin or viewer).
    Returns the decoded payload dict. Raises 401 on failure.
    """
    token = _extract_token(request)
    payload = _verify_token(token) if token else None
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def require_admin(request: Request) -> dict:
    """
    FastAPI dependency — requires admin role.
    Raises 403 for valid viewer tokens.
    """
    payload = await get_current_user(request)
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return payload


async def verify_ws_token(websocket: WebSocket) -> Optional[dict]:
    """
    Verify a WebSocket connection's token from the query parameter.
    Returns the decoded payload dict, or None if invalid.
    """
    token = websocket.query_params.get("token", "")
    if not token:
        return None
    return _verify_token(token)
