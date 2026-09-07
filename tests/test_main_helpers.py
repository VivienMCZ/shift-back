"""Tests des utilitaires de démarrage (``app.main``) et de la sonde /health."""

import pytest

from app.main import get_env_float, get_env_int, mask_database_url


# --------------------------------------------------------------------------- #
# get_env_int
# --------------------------------------------------------------------------- #


def test_get_env_int_valeur_par_defaut_si_variable_absente(monkeypatch):
    monkeypatch.delenv("UNE_VARIABLE_ABSENTE", raising=False)
    assert get_env_int("UNE_VARIABLE_ABSENTE", 5) == 5


def test_get_env_int_lit_une_valeur_valide(monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRIES", "12")
    assert get_env_int("DB_INIT_RETRIES", 5) == 12


def test_get_env_int_retombe_sur_le_defaut_si_non_numerique(monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRIES", "beaucoup")
    assert get_env_int("DB_INIT_RETRIES", 5) == 5


@pytest.mark.parametrize("valeur", ["0", "-3"])
def test_get_env_int_refuse_les_valeurs_inferieures_a_un(monkeypatch, valeur):
    monkeypatch.setenv("DB_INIT_RETRIES", valeur)
    assert get_env_int("DB_INIT_RETRIES", 5) == 5


def test_get_env_int_accepte_la_borne_basse(monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRIES", "1")
    assert get_env_int("DB_INIT_RETRIES", 5) == 1


def test_get_env_int_chaine_vide_retombe_sur_le_defaut(monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRIES", "")
    assert get_env_int("DB_INIT_RETRIES", 5) == 5


# --------------------------------------------------------------------------- #
# get_env_float
# --------------------------------------------------------------------------- #


def test_get_env_float_valeur_par_defaut_si_variable_absente(monkeypatch):
    monkeypatch.delenv("UNE_VARIABLE_ABSENTE", raising=False)
    assert get_env_float("UNE_VARIABLE_ABSENTE", 2.0) == 2.0


def test_get_env_float_lit_une_valeur_valide(monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRY_DELAY_SECONDS", "0.5")
    assert get_env_float("DB_INIT_RETRY_DELAY_SECONDS", 2.0) == 0.5


def test_get_env_float_accepte_zero(monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRY_DELAY_SECONDS", "0")
    assert get_env_float("DB_INIT_RETRY_DELAY_SECONDS", 2.0) == 0.0


def test_get_env_float_refuse_une_valeur_negative(monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRY_DELAY_SECONDS", "-1.5")
    assert get_env_float("DB_INIT_RETRY_DELAY_SECONDS", 2.0) == 2.0


def test_get_env_float_retombe_sur_le_defaut_si_non_numerique(monkeypatch):
    monkeypatch.setenv("DB_INIT_RETRY_DELAY_SECONDS", "lent")
    assert get_env_float("DB_INIT_RETRY_DELAY_SECONDS", 2.0) == 2.0


# --------------------------------------------------------------------------- #
# mask_database_url
# --------------------------------------------------------------------------- #


def test_mask_database_url_masque_le_mot_de_passe():
    masked, host = mask_database_url("postgresql://admin:s3cr3t@db.internal:5432/shift")
    assert "s3cr3t" not in masked
    assert masked == "postgresql://admin:***@db.internal:5432/shift"
    assert host == "db.internal"


def test_mask_database_url_sans_identifiants():
    masked, host = mask_database_url("postgresql://db:5432/shift")
    assert masked == "postgresql://db:5432/shift"
    assert host == "db"


def test_mask_database_url_sans_port():
    masked, host = mask_database_url("postgresql://user:pw@localhost/shift")
    assert masked == "postgresql://user:***@localhost/shift"
    assert host == "localhost"


def test_mask_database_url_host_inconnu():
    masked, host = mask_database_url("sqlite:///./shift.db")
    assert host == "inconnu"
    assert "inconnu" in masked


# --------------------------------------------------------------------------- #
# /health
# --------------------------------------------------------------------------- #


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "shift-back"}


def test_openapi_est_genere(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Shift API"
