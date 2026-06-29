from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from config import settings
from database import get_connection

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: int, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + timedelta(days=settings.JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def register_user(username: str, password: str, secret: str = "") -> dict:
    username = username.strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="Benutzername und Passwort erforderlich.")
    if (secret or "").strip() != settings.REGISTER_SECRET:
        raise HTTPException(status_code=403, detail="Ungültiges Registrierungs-Geheimnis.")
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = %s", (username,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Benutzername bereits vergeben.")
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
            (username, hash_password(password)),
        )
        user_id = cur.fetchone()["id"]
    token = create_access_token(user_id, username)
    return {"token": token, "username": username}


def authenticate_user(username: str, password: str) -> dict:
    username = username.strip()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (username,),
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten.")
    token = create_access_token(row["id"], row["username"])
    return {"token": token, "username": row["username"]}


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nicht authentifiziert.",
        )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id = int(payload["sub"])
        username = payload.get("username", "")
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token ungültig oder abgelaufen.",
        )
    return {"id": user_id, "username": username}
