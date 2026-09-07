"""Authentification par code à usage unique (OTP) et session par cookie JWT.

Durcissements OWASP appliqués ici — voir aussi ``app/security.py`` :

* **A02** : secret JWT obligatoire et d'une longueur minimale, OTP tiré de
  ``secrets`` et stocké sous forme de HMAC, cookie ``Secure``/``SameSite``
  pilotés par l'environnement.
* **A04 / A07** : plafonnement du nombre d'essais d'OTP par compte et de la
  cadence de demandes par adresse IP.
* **A09** : plus aucune journalisation de cookie, de jeton ou de code OTP.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_env_bool, get_env_int
from app.database import get_db
from app.models import User
from app.schemas import (
    AuthRequest,
    RegisterRequest,
    UserResponse,
    UserUpdateRequest,
    VerifyOTPRequest,
)
from app.security import RateLimiter, client_ip, generate_otp, hash_otp, verify_otp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

MIN_SECRET_LENGTH = 32

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable must be set")
if len(JWT_SECRET) < MIN_SECRET_LENGTH:
    # HS256 dérive une clé HMAC-SHA256 : en dessous de 32 octets, la marge de
    # sécurité tombe sous celle de l'algorithme (RFC 7518, section 3.2).
    raise RuntimeError(
        f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters long "
        f"(got {len(JWT_SECRET)})."
    )

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = get_env_int("JWT_EXPIRATION_DAYS", 7)

COOKIE_NAME = "access_token"
COOKIE_SECURE = get_env_bool("COOKIE_SECURE", False)
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").lower()
if COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    COOKIE_SAMESITE = "lax"

OTP_TTL_MINUTES = get_env_int("OTP_TTL_MINUTES", 10)
OTP_MAX_ATTEMPTS = get_env_int("OTP_MAX_ATTEMPTS", 5)
OTP_REQUEST_MAX = get_env_int("OTP_REQUEST_MAX", 10)
OTP_REQUEST_WINDOW_SECONDS = get_env_int("OTP_REQUEST_WINDOW_SECONDS", 900)

# Essais de vérification, par compte.
otp_attempt_limiter = RateLimiter(OTP_MAX_ATTEMPTS, OTP_TTL_MINUTES * 60)
# Demandes d'envoi de code, par adresse IP.
otp_request_limiter = RateLimiter(OTP_REQUEST_MAX, OTP_REQUEST_WINDOW_SECONDS)


def utcnow() -> datetime:
    """Instant courant, naïf en UTC (les colonnes DateTime sont sans fuseau)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def deliver_otp(destination: str, otp_code: str) -> None:
    """Achemine le code vers l'utilisateur.

    L'envoi réel (e-mail/SMS) n'est pas encore branché. Le code n'est affiché en
    console que si ``OTP_DEBUG_DELIVERY`` est explicitement activé : il ne doit
    jamais apparaître dans les journaux d'un environnement partagé.
    """
    if get_env_bool("OTP_DEBUG_DELIVERY", False):
        print(f"\n{'=' * 40}\n SIMULATED EMAIL/SMS SENDING \n To: {destination}\n CODE OTP: {otp_code}\n{'=' * 40}\n")
    else:
        logger.info("Code OTP envoyé (destinataire masqué).")


def issue_otp(user: User) -> str:
    """Génère un code, stocke son empreinte et remet les compteurs à zéro."""
    otp_code = generate_otp()
    user.otp_code = hash_otp(otp_code, JWT_SECRET)
    user.otp_expires_at = utcnow() + timedelta(minutes=OTP_TTL_MINUTES)
    otp_attempt_limiter.reset(user.email)
    return otp_code


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated (no token)")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        # Le détail de l'erreur reste côté serveur : le renvoyer au client
        # aiderait à distinguer un jeton expiré d'un jeton mal signé.
        logger.info("Jeton de session rejeté.")
        raise HTTPException(status_code=401, detail="Invalid token (decode error)")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token (no sub)")

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token (bad sub)")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.post("/request-otp")
def request_otp(payload: AuthRequest, request: Request, db: Session = Depends(get_db)):
    if otp_request_limiter.hit(client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de demandes de code. Réessayez dans quelques minutes.",
        )

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        # Comportement conservé volontairement : le parcours du front bascule
        # sur l'écran d'inscription à partir de ce 404. Cela expose l'existence
        # d'un compte — limitation documentée dans le README (A04).
        raise HTTPException(status_code=404, detail="User not found")

    otp_code = issue_otp(user)
    db.commit()
    deliver_otp(user.email, otp_code)

    return {"message": "OTP sent successfully"}


@router.post("/register")
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    if otp_request_limiter.hit(client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de demandes de code. Réessayez dans quelques minutes.",
        )

    user = db.query(User).filter(User.email == payload.email).first()
    if user:
        raise HTTPException(status_code=400, detail="Email already registered")

    if payload.phone:
        existing_phone_user = db.query(User).filter(User.phone == payload.phone).first()
        if existing_phone_user:
            raise HTTPException(status_code=400, detail="Phone already registered")

    new_user = User(
        email=payload.email,
        phone=payload.phone,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    otp_code = issue_otp(new_user)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    deliver_otp(new_user.email, otp_code)

    return {"message": "User created and OTP sent"}


@router.post("/verify-otp", response_model=UserResponse)
def verify_otp_endpoint(
    payload: VerifyOTPRequest, response: Response, db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if otp_attempt_limiter.is_blocked(user.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives. Demandez un nouveau code.",
        )

    expire = not user.otp_expires_at or user.otp_expires_at < utcnow()
    if expire or not verify_otp(payload.otp_code, user.otp_code, JWT_SECRET):
        otp_attempt_limiter.hit(user.email)
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    user.otp_code = None
    user.otp_expires_at = None
    db.commit()
    otp_attempt_limiter.reset(user.email)

    expiration = utcnow() + timedelta(days=JWT_EXPIRATION_DAYS)
    token = jwt.encode(
        {"sub": str(user.id), "exp": expiration, "iat": utcnow()},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
        max_age=JWT_EXPIRATION_DAYS * 24 * 60 * 60,
    )

    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )
    return {"message": "Logged out successfully"}


@router.put("/me", response_model=UserResponse)
def update_current_user(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.age is not None:
        current_user.age = payload.age
    if payload.statut is not None:
        current_user.statut = payload.statut
    if payload.postal_code is not None:
        current_user.postal_code = payload.postal_code

    db.commit()
    db.refresh(current_user)
    return current_user
