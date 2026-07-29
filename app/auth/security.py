"""
Password hashing (bcrypt) and JWT access tokens.
Pure functions: no database, no FastAPI.
"""
# --- Imports: standard library ---
from datetime import datetime, timedelta, timezone

# --- Imports: third-party ---
import bcrypt
import jwt

# --- Imports: local application ---
from app.config import settings

# --- Config ---
ALGORITHM = "HS256"
TOKEN_TTL = timedelta(days=7)


# --- Password hashing ---
def hash_password(plain: str) -> str:
    """One-way hash. bcrypt salts automatically, so equal passwords get different hashes."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Hash the attempt and compare — the stored password is never decrypted."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# --- JWT access tokens ---
def create_access_token(user_id: str) -> str:
    """Sign a token carrying the user id ('sub') and an expiry."""
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + TOKEN_TTL}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return the user id, or None if the token is invalid, tampered with, or expired."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None