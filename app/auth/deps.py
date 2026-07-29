"""
FastAPI dependency that turns an Authorization header into a user id.

No database lookup: the token is verified mathematically with JWT_SECRET, so any
worker on any machine can authenticate a request independently — stateless auth.
"""
# --- Imports ---
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


# --- Dependency ---
async def get_current_user_id(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Return the caller's user id, or raise 401. Add to any endpoint to protect it."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_access_token(creds.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id