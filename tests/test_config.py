"""Tests du parsing de configuration (``app.config``).

Une variable d'environnement mal formée ne doit jamais faire tomber le
démarrage : elle retombe sur la valeur par défaut avec un avertissement.
"""

import pytest

from app.config import get_env_bool, get_env_list

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
