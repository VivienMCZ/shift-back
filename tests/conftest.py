"""Fixtures partagées par toute la suite de tests.

Deux garde-fous importants :

1. ``DATABASE_URL`` et ``JWT_SECRET`` sont forcés **avant** le moindre import de
   ``app.*``. ``app.database`` construit son engine à l'import et
   ``app.routers.auth`` lève une ``RuntimeError`` si ``JWT_SECRET`` est absent.
   Forcer les variables (et non ``setdefault``) garantit qu'une suite de tests ne
   peut jamais toucher une base de données réelle, même si le poste de dev ou la
   CI exporte un ``DATABASE_URL`` de production.

2. Les tests tournent sur une base SQLite jetable, recréée pour chaque test via
   l'override de la dépendance ``get_db``.
"""

import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
# 32 caractères minimum : app.routers.auth refuse un secret plus court.
os.environ["JWT_SECRET"] = "test-secret-not-for-production-0123456789"
os.environ["ADMIN_API_TOKEN"] = "test-admin-token-0123456789"
os.environ["OTP_DEBUG_DELIVERY"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.api.models.aide import AideDB, AideSave  # noqa: E402,F401
from app.database import Base, get_db  # noqa: E402
from app.routers import auth as auth_module  # noqa: E402
from app.security import hash_otp  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AutoEcole, Favorite, Lib, User  # noqa: E402,F401

TEST_JWT_SECRET = os.environ["JWT_SECRET"]
TEST_ADMIN_TOKEN = os.environ["ADMIN_API_TOKEN"]
ADMIN_HEADERS = {"X-Admin-Token": TEST_ADMIN_TOKEN}


@pytest.fixture(scope="session")
def engine(tmp_path_factory):
    """Engine SQLite sur fichier temporaire, partagé par la session de tests.

    Un fichier plutôt que ``:memory:`` : chaque Session obtient sa propre
    connexion, ce qui évite qu'une transaction de lecture côté test bloque une
    écriture côté application.
    """
    db_path = tmp_path_factory.mktemp("db") / "test_shift.db"
    test_engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def clean_tables(engine):
    """Vide toutes les tables et les compteurs de limitation avant chaque test."""
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    # Les limiteurs sont des singletons de module : sans remise à zéro, un
    # test qui sature le quota ferait échouer les suivants.
    auth_module.otp_attempt_limiter.clear()
    auth_module.otp_request_limiter.clear()
    yield


@pytest.fixture
def admin_headers():
    """En-tête d'administration valide pour les écritures sur /api/v1/libs."""
    return dict(ADMIN_HEADERS)


@pytest.fixture
def otp_fixe(monkeypatch):
    """Fige le code OTP généré par l'application pour le rendre prévisible.

    Le code n'est plus stocké en clair : le lire en base ne suffit plus.
    """
    code = "123456"
    monkeypatch.setattr(auth_module, "generate_otp", lambda *a, **k: code)
    return code


@pytest.fixture
def db(session_factory):
    """Fabrique de sessions courtes.

    Utilisation : ``with db() as session: ...``. La session est systématiquement
    fermée en sortie, donc aucune transaction ne reste ouverte entre deux appels
    à l'API.
    """

    @contextmanager
    def _session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    return _session


@pytest.fixture
def client(session_factory):
    """Client HTTP de test.

    ``TestClient`` est instancié hors gestionnaire de contexte : le ``lifespan``
    de l'application (qui appelle ``init_db`` et le seed) n'est donc pas exécuté.
    """

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Fabriques de données
# --------------------------------------------------------------------------- #

ECOLE_DEFAULTS = {
    "name": "Auto-école Test",
    "address": "1 rue de Test",
    "city": "Paris",
    "postal_code": "75001",
    "lat": 48.8566,
    "lng": 2.3522,
    "rating": 4.5,
    "price": 1200,
    "price_label": "1 200 €",
    "speed_level": "moyen",
    "speed_label": "Délai moyen",
    "permis_type": "voiture",
    "tags": [],
    "image_url": None,
}


@pytest.fixture
def make_ecole(db):
    """Insère une auto-école et renvoie son id."""

    def _make(**overrides):
        data = {**ECOLE_DEFAULTS, **overrides}
        with db() as session:
            ecole = AutoEcole(**data)
            session.add(ecole)
            session.commit()
            return ecole.id

    return _make


@pytest.fixture
def make_user(db):
    """Insère un utilisateur et renvoie son id."""

    def _make(**overrides):
        data = {
            "email": "test@example.com",
            "first_name": "Jean",
            "last_name": "Dupont",
            **overrides,
        }
        with db() as session:
            user = User(**data)
            session.add(user)
            session.commit()
            return user.id

    return _make


@pytest.fixture
def make_aide(db):
    """Insère une aide et renvoie son id."""

    def _make(**overrides):
        data = {
            "categorie": "Nationale",
            "nom": "Aide de test",
            "description": "Description de test",
            "handicap_requis": False,
            "boursier_requis": False,
            "inscrit_france_travail_requis": False,
            "rsa_requis": False,
            "formation_qualifiante_requise": False,
            **overrides,
        }
        with db() as session:
            aide = AideDB(**data)
            session.add(aide)
            session.commit()
            return aide.id

    return _make


@pytest.fixture
def make_lib(db):
    """Insère un libellé et renvoie son id."""

    def _make(**overrides):
        data = {"key": "test.key", "fr": "Bonjour", "en": "Hello", **overrides}
        with db() as session:
            lib = Lib(**data)
            session.add(lib)
            session.commit()
            return lib.id

    return _make


@pytest.fixture
def login(client, db):
    """Authentifie un utilisateur et pose le cookie de session sur ``client``.

    Passe par le vrai parcours OTP afin que le cookie produit soit identique à
    celui de la production.
    """

    def _login(email="test@example.com", **overrides):
        with db() as session:
            user = session.query(User).filter(User.email == email).first()
            if user is None:
                user = User(
                    email=email,
                    first_name=overrides.pop("first_name", "Jean"),
                    last_name=overrides.pop("last_name", "Dupont"),
                    **overrides,
                )
                session.add(user)
            user.otp_code = hash_otp("123456", TEST_JWT_SECRET)
            user.otp_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
            session.commit()
            user_id = user.id

        response = client.post(
            "/auth/verify-otp", json={"email": email, "otp_code": "123456"}
        )
        assert response.status_code == 200, response.text
        return user_id

    return _login
