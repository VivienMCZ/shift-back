"""Tests du parsing de configuration (``app.config``).

Une variable d'environnement mal formée ne doit jamais faire tomber le
démarrage : elle retombe sur la valeur par défaut avec un avertissement.
"""

import pytest

from app.config import (
    get_env_bool,
    get_env_float,
    get_env_int,
    get_env_list,
    mask_database_url,
)

VARIABLE = "UNE_VARIABLE_DE_TEST"


# --------------------------------------------------------------------------- #
# get_env_bool
# --------------------------------------------------------------------------- #


def test_bool_valeur_par_defaut(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)
    assert get_env_bool(VARIABLE, True) is True
    assert get_env_bool(VARIABLE, False) is False


@pytest.mark.parametrize("valeur", ["1", "true", "TRUE", "yes", "on", "oui", " True "])
def test_bool_valeurs_vraies(monkeypatch, valeur):
    monkeypatch.setenv(VARIABLE, valeur)
    assert get_env_bool(VARIABLE, False) is True


@pytest.mark.parametrize("valeur", ["0", "false", "FALSE", "no", "off", "non"])
def test_bool_valeurs_fausses(monkeypatch, valeur):
    monkeypatch.setenv(VARIABLE, valeur)
    assert get_env_bool(VARIABLE, True) is False


@pytest.mark.parametrize("valeur", ["peut-etre", "", "2"])
def test_bool_valeur_incomprehensible_retombe_sur_le_defaut(monkeypatch, valeur):
    monkeypatch.setenv(VARIABLE, valeur)
    assert get_env_bool(VARIABLE, True) is True
    assert get_env_bool(VARIABLE, False) is False


# --------------------------------------------------------------------------- #
# get_env_list
# --------------------------------------------------------------------------- #


def test_liste_valeur_par_defaut(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)
    assert get_env_list(VARIABLE, ["a", "b"]) == ["a", "b"]


def test_liste_valeur_par_defaut_est_copiee(monkeypatch):
    """Le défaut ne doit pas pouvoir être muté par l'appelant."""
    monkeypatch.delenv(VARIABLE, raising=False)
    defaut = ["a"]
    resultat = get_env_list(VARIABLE, defaut)
    resultat.append("b")
    assert defaut == ["a"]


def test_liste_separee_par_des_virgules(monkeypatch):
    monkeypatch.setenv(VARIABLE, "https://a.fr,https://b.fr")
    assert get_env_list(VARIABLE, []) == ["https://a.fr", "https://b.fr"]


def test_liste_ignore_les_espaces_et_les_entrees_vides(monkeypatch):
    monkeypatch.setenv(VARIABLE, " https://a.fr , , https://b.fr ,")
    assert get_env_list(VARIABLE, []) == ["https://a.fr", "https://b.fr"]


def test_liste_vide(monkeypatch):
    monkeypatch.setenv(VARIABLE, "")
    assert get_env_list(VARIABLE, ["defaut"]) == []


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
