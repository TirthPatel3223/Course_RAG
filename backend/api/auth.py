"""
Authentication — Simple password-based auth with JWT tokens.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Optional
from functools import wraps

from fastapi import HTTPException, Request, WebSocket, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.config import get_settings

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# Token validity: 24 hours
TOKEN_EXPIRY_SECONDS = 86400


def _generate_token(password: str) -> str:
    """Generate a simple HMAC-based token."""
    settings = get_settings()
    timestamp = str(int(time.time()))
    payload = json.dumps({"ts": timestamp, "v": 1})
    signature = hmac.new(
        password.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    # Base64-ish encoding: payload.signature
    import base64
    token = base64.urlsafe_b64encode(payload.encode()).decode() + "." + signature
    return token


def _verify_token(token: str) -> bool:
    """Verify a token's signature and expiry."""
    settings = get_settings()
    try:
        import base64
        parts = token.split(".")
        if len(parts) != 2:
            return False

        payload_b64, signature = parts
        payload = base64.urlsafe_b64decode(payload_b64).decode()
        data = json.loads(payload)

        # Verify signature
        expected_sig = hmac.new(
            settings.app_password.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return False

        # Check expiry
        ts = int(data.get("ts", 0))
        if time.time() - ts > TOKEN_EXPIRY_SECONDS:
            return False

        return True
    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return False


def verify_password(password: str) -> Optional[str]:
    """
    Verify the password and return a token if correct.

    Args:
        password: The password to verify.

    Returns:
        JWT token string if password is correct, None otherwise.
    """
    settings = get_settings()
    if password == settings.app_password:
        token = _generate_token(password)
        logger.info("Password verified — token issued")
        return token
    logger.warning("Invalid password attempt")
    return None


async def get_current_user(request: Request) -> bool:
    """
    FastAPI dependency: verify the auth token from the request.
    Raises HTTPException if not authenticated.
    """
    # Check Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if _verify_token(token):
            return True

    # Check query parameter (for WebSocket connections)
    token = request.query_params.get("token", "")
    if token and _verify_token(token):
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def verify_ws_token(websocket: WebSocket) -> bool:
    """
    Verify authentication for WebSocket connections.
    Token is passed as a query parameter.
    """
    token = websocket.query_params.get("token", "")
    if not token:
        # Also check first message for token
        return False

    return _verify_token(token)
