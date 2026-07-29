"""
Signup / login / me endpoints.

bcrypt is CPU-bound and deliberately slow (~250ms), so every hash and verify goes
through asyncio.to_thread to keep the event loop free.
"""
# --- Imports: standard library ---
import asyncio

# --- Imports: third-party ---
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

# --- Imports: local application ---
from app import db
from app.auth.deps import get_current_user_id
from app.auth.security import create_access_token, hash_password, verify_password

# --- Router setup ---
router = APIRouter(prefix="/auth", tags=["auth"])


# --- Request/response models ---
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)   # bcrypt only reads 72 bytes
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    avatar_url: str | None = None


# --- Routes ---
@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest):
    pool = db.get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT id FROM users WHERE email = %s", (body.email,))
        if await cur.fetchone():
            raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")

        hashed = await asyncio.to_thread(hash_password, body.password)

        cur = await conn.execute(
            """INSERT INTO users (email, password_hash, display_name)
               VALUES (%s, %s, %s) RETURNING id""",
            (body.email, hashed, body.display_name),
        )
        user = await cur.fetchone()

    return TokenResponse(access_token=create_access_token(user["id"]))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    pool = db.get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, password_hash FROM users WHERE email = %s", (body.email,)
        )
        user = await cur.fetchone()

    # Same message whether the email is unknown or the password is wrong —
    # never reveal which emails have accounts.
    if user is None or not user["password_hash"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")

    ok = await asyncio.to_thread(verify_password, body.password, user["password_hash"])
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")

    return TokenResponse(access_token=create_access_token(user["id"]))


@router.get("/me", response_model=UserResponse)
async def me(user_id: str = Depends(get_current_user_id)):
    pool = db.get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, email, display_name, avatar_url FROM users WHERE id = %s",
            (user_id,),
        )
        user = await cur.fetchone()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists.")
    return UserResponse(
        id=str(user["id"]),
        email=user["email"],
        display_name=user["display_name"],
        avatar_url=user["avatar_url"],
    )