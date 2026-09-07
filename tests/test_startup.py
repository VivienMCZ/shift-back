"""Tests du démarrage de l'application : initialisation de la base et garde-fous.

``init_db`` réessaie tant que PostgreSQL n'est pas prêt (cas classique en
``docker compose``, où l'API démarre avant la base). Rien n'est écrit ici sur
une base réelle : ``create_all`` et ``seed`` sont simulés.
"""

import importlib
import os

import pytest
from sqlalchemy.exc import OperationalError

from app import main as main_module
from app.database import Base


def erreur_base():
    return OperationalError("SELECT 1", {}, Exception("connexion refusée"))


@pytest.fixture
def init_db_simule(monkeypatch):
    """Simule ``create_all``/``seed`` et neutralise les temporisations.

    Renvoie le journal des appels ; ``programme`` liste les exceptions à lever
    successivement (``None`` = succès).
    """
    journal = {"create_all": 0, "seed": 0, "sleep": []}

    def installer(programme):
        restant = list(programme)

        def fake_create_all(bind=None, **kwargs):
            journal["create_all"] += 1
            erreur = restant.pop(0) if restant else None
            if erreur is not None:
                raise erreur

        def fake_seed():
            journal["seed"] += 1

        monkeypatch.setattr(Base.metadata, "create_all", fake_create_all)
        monkeypatch.setattr("app.seed.seed", fake_seed)
        monkeypatch.setattr(main_module.time, "sleep", lambda d: journal["sleep"].append(d))
        return journal

    return installer


# --------------------------------------------------------------------------- #
# init_db
# --------------------------------------------------------------------------- #


def test_init_db_succes_du_premier_coup(init_db_simule):
    journal = init_db_simule([None])
    main_module.init_db()
    assert journal["create_all"] == 1
    assert journal["seed"] == 1
    assert journal["sleep"] == []


def test_init_db_reessaie_puis_reussit(init_db_simule, monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRIES", "5")
    monkeypatch.setenv("DB_INIT_RETRY_DELAY_SECONDS", "0.1")
    journal = init_db_simule([erreur_base(), erreur_base(), None])

    main_module.init_db()

    assert journal["create_all"] == 3
    assert journal["seed"] == 1
    assert journal["sleep"] == [0.1, 0.1]


def test_init_db_abandonne_apres_le_nombre_max_de_tentatives(init_db_simule, monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRIES", "3")
    monkeypatch.setenv("DB_INIT_RETRY_DELAY_SECONDS", "0")
    journal = init_db_simule([erreur_base()] * 10)

    with pytest.raises(OperationalError):
        main_module.init_db()

    assert journal["create_all"] == 3
    assert journal["seed"] == 0
    # Pas de temporisation après la dernière tentative.
    assert len(journal["sleep"]) == 2


def test_init_db_une_seule_tentative_si_configure(init_db_simule, monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRIES", "1")
    journal = init_db_simule([erreur_base()])

    with pytest.raises(OperationalError):
        main_module.init_db()

    assert journal["create_all"] == 1
    assert journal["sleep"] == []


def test_init_db_ne_rattrape_pas_les_autres_erreurs(init_db_simule, monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRIES", "5")
    journal = init_db_simule([ValueError("schéma invalide")])

    with pytest.raises(ValueError):
        main_module.init_db()

    assert journal["create_all"] == 1


def test_init_db_ne_journalise_jamais_le_mot_de_passe(init_db_simule, caplog, monkeypatch):
    monkeypatch.setattr("app.database.DATABASE_URL", "postgresql://u:motdepasse@h:5432/d")
    init_db_simule([None])

    with caplog.at_level("INFO"):
        main_module.init_db()

    assert "motdepasse" not in caplog.text
    assert "***" in caplog.text


# --------------------------------------------------------------------------- #
# get_db
# --------------------------------------------------------------------------- #


def test_get_db_ferme_toujours_la_session(monkeypatch):
    from app import database

    fermetures = []

    class FakeSession:
        def close(self):
            fermetures.append(True)

    monkeypatch.setattr(database, "SessionLocal", lambda: FakeSession())

    generateur = database.get_db()
    session = next(generateur)
    assert isinstance(session, FakeSession)
    generateur.close()
    assert fermetures == [True]


# --------------------------------------------------------------------------- #
# Garde-fou JWT_SECRET
# --------------------------------------------------------------------------- #


def test_jwt_secret_est_obligatoire(monkeypatch):
    """Le module d'authentification doit refuser de se charger sans secret."""
    import app.routers.auth as auth_module

    secret_initial = os.environ["JWT_SECRET"]
    try:
        monkeypatch.delenv("JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            importlib.reload(auth_module)
    finally:
        os.environ["JWT_SECRET"] = secret_initial
        importlib.reload(auth_module)

    assert auth_module.JWT_SECRET == secret_initial


def test_le_lifespan_initialise_la_base(monkeypatch):
    """Le démarrage de l'application doit déclencher ``init_db`` une seule fois."""
    from fastapi.testclient import TestClient

    appels = []
    monkeypatch.setattr(main_module, "init_db", lambda: appels.append(True))

    with TestClient(main_module.app) as client:
        assert client.get("/health").status_code == 200

    assert appels == [True]


@pytest.mark.parametrize(
    "chemin",
    [
        "/health",
        "/api/ecoles",
        "/api/ecoles/{ecole_id}",
        "/api/ecoles/favorites",
        "/auth/me",
        "/auth/register",
        "/auth/request-otp",
        "/auth/verify-otp",
        "/auth/logout",
        "/api/v1/libs/",
        "/api/v1/libs/{key}",
        "/api/v1/libs/{key}/translate",
        "/api/v1/aides/calculate",
        "/api/v1/aides/saves",
        "/api/locations/search",
        "/api/locations/reverse",
    ],
)
def test_application_expose_les_routeurs_attendus(chemin):
    assert chemin in main_module.app.openapi()["paths"]


def test_cors_autorise_le_front_local(client):
    """Le front Next.js (localhost:3000) doit pouvoir appeler l'API avec cookie."""
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_refuse_une_origine_inconnue(client):
    response = client.get("/health", headers={"Origin": "https://site-malveillant.fr"})
    assert "access-control-allow-origin" not in response.headers
