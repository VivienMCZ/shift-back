"""Tests unitaires du moteur d'éligibilité aux aides (``CalculateurAides``).

Logique métier pure : aucun accès base de données, les aides sont des objets
factices exposant les mêmes attributs que ``AideDB``.
"""

import pytest

from app.api.aide_calculator import CalculateurAides
from app.api.models.user_profile import UserProfile


class FakeAide:
    """Aide en mémoire, avec les mêmes attributs que ``AideDB``."""

    def __init__(self, nom="Aide", montant=None, **criteres):
        self.nom = nom
        self.montant = montant
        self.age_min = criteres.get("age_min")
        self.age_max = criteres.get("age_max")
        self.region = criteres.get("region")
        self.departement = criteres.get("departement")
        self.commune = criteres.get("commune")
        self.statut_requis = criteres.get("statut_requis")
        self.handicap_requis = criteres.get("handicap_requis", False)
        self.boursier_requis = criteres.get("boursier_requis", False)
        self.inscrit_france_travail_requis = criteres.get(
            "inscrit_france_travail_requis", False
        )
        self.rsa_requis = criteres.get("rsa_requis", False)
        self.formation_qualifiante_requise = criteres.get(
            "formation_qualifiante_requise", False
        )


def profil(**overrides):
    base = {"age": 22, "statut": "etudiant"}
    base.update(overrides)
    return UserProfile(**base)


def executer(user, aides):
    return CalculateurAides(user, aides).executer()


# --------------------------------------------------------------------------- #
# Cas de base
# --------------------------------------------------------------------------- #


def test_aucune_aide_disponible():
    resultat = executer(profil(), [])
    assert resultat == {"aides": [], "total_potentiel": 0}


def test_aide_sans_critere_est_toujours_eligible():
    aide = FakeAide(montant=500.0)
    resultat = executer(profil(), [aide])
    assert resultat["aides"] == [aide]
    assert resultat["total_potentiel"] == 500.0


def test_total_additionne_les_montants_des_aides_eligibles():
    aides = [FakeAide(nom="A", montant=600.0), FakeAide(nom="B", montant=900.0)]
    assert executer(profil(), aides)["total_potentiel"] == 1500.0


def test_montant_none_nest_pas_compte_dans_le_total():
    aides = [FakeAide(nom="A", montant=None), FakeAide(nom="B", montant=200.0)]
    resultat = executer(profil(), aides)
    assert len(resultat["aides"]) == 2
    assert resultat["total_potentiel"] == 200.0


def test_aide_non_eligible_est_exclue_du_total():
    aides = [FakeAide(nom="ok", montant=100.0), FakeAide(nom="ko", montant=999.0, age_max=18)]
    resultat = executer(profil(age=30), aides)
    assert [a.nom for a in resultat["aides"]] == ["ok"]
    assert resultat["total_potentiel"] == 100.0


# --------------------------------------------------------------------------- #
# Critères d'âge
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "age,eligible",
    [(14, False), (15, True), (20, True), (25, True), (26, False)],
)
def test_bornes_age_incluses(age, eligible):
    aide = FakeAide(age_min=15, age_max=25)
    resultat = executer(profil(age=age), [aide])
    assert bool(resultat["aides"]) is eligible


def test_age_min_seul():
    aide = FakeAide(age_min=18)
    assert executer(profil(age=17), [aide])["aides"] == []
    assert len(executer(profil(age=18), [aide])["aides"]) == 1


def test_age_max_seul():
    aide = FakeAide(age_max=25)
    assert len(executer(profil(age=25), [aide])["aides"]) == 1
    assert executer(profil(age=26), [aide])["aides"] == []


# --------------------------------------------------------------------------- #
# Critères géographiques
# --------------------------------------------------------------------------- #


def test_region_doit_correspondre():
    aide = FakeAide(region="Occitanie")
    assert executer(profil(region="Île-de-France"), [aide])["aides"] == []
    assert len(executer(profil(region="Occitanie"), [aide])["aides"]) == 1


def test_region_absente_du_profil_exclut_une_aide_regionale():
    aide = FakeAide(region="Occitanie")
    assert executer(profil(region=None), [aide])["aides"] == []


def test_departement_doit_correspondre():
    aide = FakeAide(departement="31")
    assert executer(profil(departement="75"), [aide])["aides"] == []
    assert len(executer(profil(departement="31"), [aide])["aides"]) == 1


def test_commune_doit_correspondre():
    aide = FakeAide(commune="Toulouse")
    assert executer(profil(commune="Paris"), [aide])["aides"] == []
    assert len(executer(profil(commune="Toulouse"), [aide])["aides"]) == 1


def test_aide_nationale_eligible_quelle_que_soit_la_localisation():
    aide = FakeAide()
    profil_local = profil(region="Bretagne", departement="35", commune="Rennes")
    assert len(executer(profil_local, [aide])["aides"]) == 1


# --------------------------------------------------------------------------- #
# Critère de statut
# --------------------------------------------------------------------------- #


def test_statut_present_dans_la_liste_requise():
    aide = FakeAide(statut_requis=["salarie", "demandeur_emploi"])
    assert len(executer(profil(statut="demandeur_emploi"), [aide])["aides"]) == 1


def test_statut_absent_de_la_liste_requise():
    aide = FakeAide(statut_requis=["salarie", "demandeur_emploi"])
    assert executer(profil(statut="etudiant"), [aide])["aides"] == []


def test_statut_requis_vide_nexclut_personne():
    aide = FakeAide(statut_requis=[])
    assert len(executer(profil(statut="etudiant"), [aide])["aides"]) == 1


def test_statut_requis_none_nexclut_personne():
    aide = FakeAide(statut_requis=None)
    assert len(executer(profil(statut="apprenti"), [aide])["aides"]) == 1


# --------------------------------------------------------------------------- #
# Critères booléens
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "critere,champ_profil",
    [
        ("handicap_requis", "has_rqth"),
        ("boursier_requis", "is_boursier"),
        ("inscrit_france_travail_requis", "inscrit_france_travail"),
        ("rsa_requis", "beneficiaire_rsa"),
        ("formation_qualifiante_requise", "en_formation_qualifiante"),
    ],
)
def test_critere_booleen_exige_le_champ_correspondant(critere, champ_profil):
    aide = FakeAide(**{critere: True})

    sans = profil(**{champ_profil: False})
    assert executer(sans, [aide])["aides"] == []

    avec = profil(**{champ_profil: True})
    assert len(executer(avec, [aide])["aides"]) == 1


def test_criteres_booleens_desactives_nexcluent_pas():
    aide = FakeAide(
        handicap_requis=False,
        boursier_requis=False,
        inscrit_france_travail_requis=False,
        rsa_requis=False,
        formation_qualifiante_requise=False,
    )
    assert len(executer(profil(), [aide])["aides"]) == 1


# --------------------------------------------------------------------------- #
# Combinaisons
# --------------------------------------------------------------------------- #


def test_tous_les_criteres_doivent_etre_satisfaits():
    aide = FakeAide(
        montant=1000.0,
        age_min=18,
        age_max=25,
        region="Île-de-France",
        statut_requis=["etudiant"],
        boursier_requis=True,
    )
    conforme = profil(age=20, region="Île-de-France", statut="etudiant", is_boursier=True)
    assert len(executer(conforme, [aide])["aides"]) == 1

    # Un seul critère qui diverge suffit à exclure l'aide.
    conforme_kwargs = {
        "age": 20,
        "region": "Île-de-France",
        "statut": "etudiant",
        "is_boursier": True,
    }
    for divergence in (
        {"age": 30},
        {"region": "Occitanie"},
        {"statut": "salarie"},
        {"is_boursier": False},
    ):
        profil_ko = profil(**{**conforme_kwargs, **divergence})
        assert executer(profil_ko, [aide])["aides"] == [], divergence


def test_selection_parmi_un_catalogue_mixte():
    catalogue = [
        FakeAide(nom="Permis à 1 €", montant=1200.0, age_min=15, age_max=25),
        FakeAide(nom="CPF", montant=900.0, statut_requis=["salarie", "demandeur_emploi"]),
        FakeAide(nom="Aide RQTH", montant=500.0, handicap_requis=True),
        FakeAide(nom="Aide régionale", montant=300.0, region="Occitanie"),
    ]
    user = profil(age=20, statut="demandeur_emploi", region="Île-de-France")
    resultat = executer(user, catalogue)

    assert sorted(a.nom for a in resultat["aides"]) == ["CPF", "Permis à 1 €"]
    assert resultat["total_potentiel"] == 2100.0
