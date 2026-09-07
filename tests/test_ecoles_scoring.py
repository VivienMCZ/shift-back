"""Tests unitaires des fonctions de calcul du routeur ``ecoles``.

Distance, normalisation et score de correspondance : logique pure, sans base.
"""

import pytest
from fastapi import HTTPException

from app.routers.ecoles import (
    clamp,
    compute_distance_score,
    compute_match,
    compute_price_score,
    haversine,
    normalize_permis,
    score_label,
)


# --------------------------------------------------------------------------- #
# haversine
# --------------------------------------------------------------------------- #


def test_haversine_distance_nulle_pour_le_meme_point():
    assert haversine(48.8566, 2.3522, 48.8566, 2.3522) == pytest.approx(0.0, abs=1e-9)


def test_haversine_paris_lyon():
    # Distance orthodromique Paris — Lyon : environ 392 km.
    distance = haversine(48.8566, 2.3522, 45.7640, 4.8357)
    assert distance == pytest.approx(392, abs=5)


def test_haversine_est_symetrique():
    aller = haversine(48.85, 2.35, 43.60, 1.44)
    retour = haversine(43.60, 1.44, 48.85, 2.35)
    assert aller == pytest.approx(retour)


def test_haversine_un_degre_de_latitude_vaut_environ_111_km():
    assert haversine(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.19, abs=0.5)


# --------------------------------------------------------------------------- #
# clamp / score_label
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "valeur,attendu", [(-10, 0.0), (0, 0), (50, 50), (100, 100), (150, 100.0)]
)
def test_clamp_borne_entre_0_et_100(valeur, attendu):
    assert clamp(valeur) == attendu


def test_clamp_bornes_personnalisees():
    assert clamp(5, lower=10, upper=20) == 10
    assert clamp(25, lower=10, upper=20) == 20


@pytest.mark.parametrize(
    "score,label",
    [
        (100, "90+ Excellent"),
        (90, "90+ Excellent"),
        (89, "80+ Très bon"),
        (80, "80+ Très bon"),
        (79, "70+ Bon"),
        (70, "70+ Bon"),
        (69, "À comparer"),
        (0, "À comparer"),
    ],
)
def test_score_label_par_palier(score, label):
    assert score_label(score) == label


# --------------------------------------------------------------------------- #
# compute_price_score
# --------------------------------------------------------------------------- #


def test_price_score_neutre_quand_le_prix_est_inconnu():
    assert compute_price_score(None, 500, 2000) == 50.0


def test_price_score_maximal_au_budget_minimum():
    assert compute_price_score(500, 500, 2000) == 100.0


def test_price_score_nul_au_budget_maximum():
    assert compute_price_score(2000, 500, 2000) == 0.0


def test_price_score_interpole_au_milieu_de_la_fourchette():
    assert compute_price_score(1250, 500, 2000) == pytest.approx(50.0)


def test_price_score_borne_au_dela_de_la_fourchette():
    assert compute_price_score(5000, 500, 2000) == 0
    assert compute_price_score(100, 500, 2000) == 100


def test_price_score_utilise_les_bornes_par_defaut_sans_budget():
    # Bornes par défaut : 500 € — 2 000 €.
    assert compute_price_score(1250, None, None) == pytest.approx(50.0)


def test_price_score_fourchette_degeneree():
    # budget_max <= budget_min : tout ou rien, sur la borne basse.
    assert compute_price_score(800, 1000, 1000) == 100.0
    assert compute_price_score(1000, 1000, 1000) == 100.0
    assert compute_price_score(1200, 1000, 1000) == 0.0
    assert compute_price_score(900, 1000, 800) == 100.0
    assert compute_price_score(1100, 1000, 800) == 0.0


# --------------------------------------------------------------------------- #
# compute_distance_score
# --------------------------------------------------------------------------- #


def test_distance_score_neutre_sans_distance():
    assert compute_distance_score(None, 10) == 75.0


def test_distance_score_maximal_a_distance_nulle():
    assert compute_distance_score(0.0, 10) == 100


def test_distance_score_nul_au_rayon():
    assert compute_distance_score(10.0, 10) == 0


def test_distance_score_decroit_avec_la_distance():
    assert compute_distance_score(5.0, 10) == pytest.approx(50.0)


def test_distance_score_nul_si_rayon_invalide():
    assert compute_distance_score(3.0, 0) == 0.0
    assert compute_distance_score(3.0, -5) == 0.0


# --------------------------------------------------------------------------- #
# compute_match
# --------------------------------------------------------------------------- #


def item(**overrides):
    base = {"speed_level": "moyen", "rating": 4.0, "price": 1250, "distance": 5.0}
    base.update(overrides)
    return base


def test_compute_match_renseigne_les_trois_champs():
    donnees = item()
    compute_match(donnees, radius=10, budget_min=500, budget_max=2000)
    assert 0 <= donnees["match_score"] <= 100
    assert donnees["match_label"] in {
        "90+ Excellent",
        "80+ Très bon",
        "70+ Bon",
        "À comparer",
    }
    assert isinstance(donnees["match_reasons"], list)


def test_compute_match_profil_ideal_obtient_un_score_eleve():
    donnees = item(speed_level="rapide", rating=5.0, price=500, distance=0.5)
    compute_match(donnees, radius=10, budget_min=500, budget_max=2000)
    assert donnees["match_score"] >= 90
    assert donnees["match_label"] == "90+ Excellent"


def test_compute_match_profil_defavorable_obtient_un_score_faible():
    donnees = item(speed_level="faible", rating=1.0, price=2000, distance=10.0)
    compute_match(donnees, radius=10, budget_min=500, budget_max=2000)
    assert donnees["match_score"] < 40


def test_compute_match_vitesse_inconnue_traitee_comme_moyenne():
    connue = item(speed_level="moyen")
    inconnue = item(speed_level=None)
    compute_match(connue, radius=10, budget_min=None, budget_max=None)
    compute_match(inconnue, radius=10, budget_min=None, budget_max=None)
    assert connue["match_score"] == inconnue["match_score"]


def test_compute_match_raisons_delai():
    rapide = item(speed_level="rapide")
    compute_match(rapide, radius=10, budget_min=None, budget_max=None)
    assert "Délai rapide" in rapide["match_reasons"]

    moyen = item(speed_level="moyen", rating=1.0, price=2000)
    compute_match(moyen, radius=10, budget_min=None, budget_max=None)
    assert "Délai maîtrisé" in moyen["match_reasons"]


def test_compute_match_raisons_note():
    tres_bien = item(rating=4.8, speed_level="faible", price=2000, distance=None)
    compute_match(tres_bien, radius=10, budget_min=None, budget_max=None)
    assert "Très bien notée" in tres_bien["match_reasons"]

    bien = item(rating=4.4, speed_level="faible", price=2000, distance=None)
    compute_match(bien, radius=10, budget_min=None, budget_max=None)
    assert "Bonne note" in bien["match_reasons"]


def test_compute_match_raisons_prix():
    pas_cher = item(price=500, speed_level="faible", rating=1.0, distance=None)
    compute_match(pas_cher, radius=10, budget_min=500, budget_max=2000)
    assert "Prix compétitif" in pas_cher["match_reasons"]

    cher = item(price=2000, speed_level="faible", rating=1.0, distance=None)
    compute_match(cher, radius=10, budget_min=500, budget_max=2000)
    assert "Budget plus élevé" in cher["match_reasons"]


def test_compute_match_raisons_proximite():
    tres_proche = item(distance=2.0, speed_level="faible", rating=1.0, price=2000)
    compute_match(tres_proche, radius=10, budget_min=500, budget_max=2000)
    assert "Très proche" in tres_proche["match_reasons"]

    proche = item(distance=8.0, speed_level="faible", rating=1.0, price=2000)
    compute_match(proche, radius=10, budget_min=500, budget_max=2000)
    assert "Proche" in proche["match_reasons"]

    loin = item(distance=50.0, speed_level="faible", rating=1.0, price=2000)
    compute_match(loin, radius=100, budget_min=500, budget_max=2000)
    assert "Proche" not in loin["match_reasons"]
    assert "Très proche" not in loin["match_reasons"]


def test_compute_match_limite_a_trois_raisons():
    donnees = item(speed_level="rapide", rating=5.0, price=500, distance=1.0)
    compute_match(donnees, radius=10, budget_min=500, budget_max=2000)
    assert len(donnees["match_reasons"]) <= 3


def test_compute_match_note_absente_traitee_comme_zero():
    donnees = item(rating=None)
    compute_match(donnees, radius=10, budget_min=None, budget_max=None)
    assert isinstance(donnees["match_score"], int)


# --------------------------------------------------------------------------- #
# normalize_permis
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "entree,attendu",
    [
        ("b", "voiture"),
        ("B", "voiture"),
        ("voiture", "voiture"),
        ("car", "voiture"),
        ("a", "moto"),
        ("MOTO", "moto"),
        ("c", "poids_lourd"),
        ("poids_lourd", "poids_lourd"),
        ("poids-lourd", "poids_lourd"),
    ],
)
def test_normalize_permis_alias(entree, attendu):
    assert normalize_permis(entree) == attendu


@pytest.mark.parametrize("entree", ["bateau", "", "d", "voitures"])
def test_normalize_permis_rejette_les_valeurs_inconnues(entree):
    with pytest.raises(HTTPException) as exc:
        normalize_permis(entree)
    assert exc.value.status_code == 400
