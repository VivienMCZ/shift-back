import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from app.config import (
    get_env_bool,
    get_env_float,
    get_env_int,
    get_env_list,
    mask_database_url,
)

logger = logging.getLogger(__name__)

DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]


def init_db():
    from app.api.models.aide import AideDB  # noqa: F401
    from app.database import DATABASE_URL, engine
    from app.models import AutoEcole, Base, Lib  # noqa: F401
    from app.seed import seed

    max_retries = get_env_int("DB_INIT_RETRIES", 5)
    retry_delay = get_env_float("DB_INIT_RETRY_DELAY_SECONDS", 2.0)
    masked_url, host = mask_database_url(DATABASE_URL)

    logger.info("Initialisation de la base de données sur %s (host=%s)", masked_url, host)

    for attempt in range(1, max_retries + 1):
        try:
            Base.metadata.create_all(bind=engine)
            seed()
            logger.info("Base de données initialisée.")
            return
        except OperationalError as exc:
            if attempt < max_retries:
                logger.warning(
                    "Base de données non prête sur host=%s, nouvelle tentative (%s/%s): %s",
                    host,
                    attempt,
                    max_retries,
                    exc.orig if getattr(exc, "orig", None) else exc,
                )
                time.sleep(retry_delay)
            else:
                logger.exception(
                    "Impossible d'initialiser la base de données après %s tentative(s) sur host=%s.",
                    max_retries,
                    host,
                )
                raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# La documentation interactive décrit toute la surface d'attaque de l'API :
# elle est désactivable en production via ENABLE_DOCS=false (A05).
ENABLE_DOCS = get_env_bool("ENABLE_DOCS", True)

app = FastAPI(
    title="Shift API",
    description="API du comparateur d'auto-écoles et du calculateur d'aides Shift",
    version="1.0.0",
    redirect_slashes=False,
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """En-têtes de durcissement du navigateur (A05 — Security Misconfiguration)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(self), camera=(), microphone=()"
    )
    # L'API ne sert que du JSON : aucune ressource externe n'a besoin d'être chargée.
    response.headers.setdefault(
        "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
    )
    if get_env_bool("COOKIE_SECURE", False):
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# Les origines autorisées sont configurables : la liste par défaut ne couvre que
# le développement local. En production, renseigner CORS_ORIGINS.
CORS_ORIGINS = get_env_list("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
CORS_ORIGIN_REGEX = os.environ.get("CORS_ORIGIN_REGEX", r"https?://.*\.orb\.local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX or None,
    allow_credentials=True,
    # allow_credentials=True impose une liste explicite : un '*' serait ignoré
    # par les navigateurs et masquerait une mauvaise configuration.
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Token"],
    max_age=600,
)

from app.api.v1.endpoints.aides import router as aides_router  # noqa: E402
from app.routers import auth, ecoles, libs, locations  # noqa: E402

app.include_router(locations.router)
app.include_router(ecoles.router)
app.include_router(auth.router)
app.include_router(libs.router)
app.include_router(aides_router, prefix="/api/v1/aides", tags=["Aides"])


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "shift-back"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
