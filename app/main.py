import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
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
    try:
        yield
    finally:
        # Le proxy de géocodage garde un client HTTP partagé ouvert.
        from app.routers.locations import close_client

        await close_client()


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


# En-têtes de durcissement du navigateur (A05 — Security Misconfiguration).
# Pré-encodés en octets : ils sont réinjectés tels quels dans chaque réponse.
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"geolocation=(self), camera=(), microphone=()"),
    # L'API ne sert que du JSON : aucune ressource externe n'a besoin d'être chargée.
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
)
HSTS_HEADER = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    """Ajoute les en-têtes de durcissement sans reconstruire la réponse.

    Écrit en ASGI pur plutôt qu'avec ``@app.middleware("http")`` :
    ``BaseHTTPMiddleware`` enveloppe chaque requête dans un groupe de tâches et
    un flux mémoire anyio, ce qui coûte plusieurs centaines de microsecondes par
    appel et sérialise le corps de la réponse en mémoire. Ici on se contente de
    compléter la liste d'en-têtes du message ``http.response.start``, ce qui
    produit exactement les mêmes en-têtes pour un coût négligeable.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                # ``setdefault`` d'origine : un en-tête déjà posé par la route
                # n'est jamais écrasé.
                deja_presents = {name.lower() for name, _ in headers}
                headers.extend(
                    (name, value)
                    for name, value in SECURITY_HEADERS
                    if name not in deja_presents
                )
                if (
                    HSTS_HEADER[0] not in deja_presents
                    and get_env_bool("COOKIE_SECURE", False)
                ):
                    headers.append(HSTS_HEADER)
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)



# Les origines autorisées sont configurables : la liste par défaut ne couvre que
# le développement local. En production, renseigner CORS_ORIGINS.
CORS_ORIGINS = get_env_list("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
CORS_ORIGIN_REGEX = os.environ.get("CORS_ORIGIN_REGEX", r"https?://.*\.orb\.local")

# Les listes d'auto-écoles sont du JSON très redondant : elles se compressent
# d'un facteur 8 à 10. C'est de loin le premier poste du temps de chargement
# côté client — la liste complète passe de 2,7 Mo à 256 Ko. Le niveau 6 est le
# compromis usuel pour du contenu dynamique ; au-delà de 128 Ko, Starlette
# compresse dans un thread et ne bloque pas la boucle d'événements.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

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
