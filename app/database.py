import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_env_int

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/postgres",
)


def _engine_options(database_url: str) -> dict:
    """Options de pool adaptées au driver.

    Les routes sont synchrones : uvicorn les exécute dans un pool de threads
    (40 par défaut). Avec le pool par défaut de SQLAlchemy — 5 connexions plus
    10 de débordement — les threads au-delà du quinzième attendent une
    connexion, ce qui se traduit par des pics de latence sous charge alors même
    que la base est inactive. On aligne donc la capacité du pool sur le nombre
    de threads pouvant réellement émettre une requête.

    SQLite n'utilise pas ``QueuePool`` et rejette ces options : la suite de
    tests tourne sur SQLite, on les omet dans ce cas.
    """
    options: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        return options

    options.update(
        pool_size=get_env_int("DB_POOL_SIZE", 20),
        max_overflow=get_env_int("DB_MAX_OVERFLOW", 20),
        pool_timeout=get_env_int("DB_POOL_TIMEOUT_SECONDS", 30),
        # Referme les connexions dormantes avant qu'un pare-feu ou PostgreSQL
        # ne les coupe : évite un aller-retour perdu sur reconnexion.
        pool_recycle=get_env_int("DB_POOL_RECYCLE_SECONDS", 1800),
    )
    return options


engine = create_engine(DATABASE_URL, **_engine_options(DATABASE_URL))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
