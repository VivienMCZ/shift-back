"""Tests d'intégration du routeur ``/api/v1/aides`` (calcul et historique)."""

import pytest

from app.api.models.aide import AideSave

BASE = "/api/v1/aides"

PROFIL_ETUDIANT = {
    "age": 20,
    "statut": "etudiant",
    "region": "Île-de-France",
    "is_boursier": True,
}


# --------------------------------------------------------------------------- #
# Calcul
# --------------------------------------------------------------------------- #


def test_calcul_sans_aide_en_base(client):
    response = client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT)
    assert response.status_code == 200
    assert response.json() == {"aides": [], "total_potentiel": 0.0, "total_prets": 0.0}


def test_calcul_retourne_les_aides_eligibles(client, make_aide):
    make_aide(nom="Permis à 1 €", age_min=15, age_max=25, montant=1200.0)
    make_aide(nom="Aide seniors", age_min=60, montant=500.0)

    response = client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT)
    assert response.status_code == 200
    corps = response.json()
    assert [a["nom"] for a in corps["aides"]] == ["Permis à 1 €"]
    assert corps["total_potentiel"] == 1200.0


def test_calcul_additionne_plusieurs_aides(client, make_aide):
    make_aide(nom="A", montant=600.0)
    make_aide(nom="B", montant=900.0)
    corps = client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT).json()
    assert len(corps["aides"]) == 2
    assert corps["total_potentiel"] == 1500.0


def test_calcul_respecte_le_critere_de_statut(client, make_aide):
    make_aide(nom="CPF", statut_requis=["salarie", "demandeur_emploi"], montant=900.0)

    etudiant = client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT).json()
    assert etudiant["aides"] == []

    salarie = client.post(
        f"{BASE}/calculate", json={**PROFIL_ETUDIANT, "statut": "salarie"}
    ).json()
    assert len(salarie["aides"]) == 1


def test_calcul_respecte_le_critere_regional(client, make_aide):
    make_aide(nom="Aide Occitanie", region="Occitanie", montant=300.0)
    corps = client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT).json()
    assert corps["aides"] == []

    corps = client.post(
        f"{BASE}/calculate", json={**PROFIL_ETUDIANT, "region": "Occitanie"}
    ).json()
    assert len(corps["aides"]) == 1


def test_calcul_expose_le_detail_de_laide(client, make_aide):
    make_aide(
        nom="Aide détaillée",
        description="Une description",
        url_demande="https://exemple.fr",
        montant=750.0,
    )
    aide = client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT).json()["aides"][0]
    assert aide["description"] == "Une description"
    assert aide["url_demande"] == "https://exemple.fr"
    assert aide["montant"] == 750.0
    assert aide["categorie"] == "Nationale"


@pytest.mark.parametrize("age", [0, -5])
def test_calcul_refuse_un_age_non_positif(client, age):
    response = client.post(f"{BASE}/calculate", json={**PROFIL_ETUDIANT, "age": age})
    assert response.status_code == 422


def test_calcul_champs_obligatoires_manquants(client):
    assert client.post(f"{BASE}/calculate", json={"age": 20}).status_code == 422
    assert client.post(f"{BASE}/calculate", json={"statut": "etudiant"}).status_code == 422


def test_calcul_valeurs_booleennes_par_defaut(client, make_aide):
    make_aide(nom="RQTH", handicap_requis=True, montant=500.0)
    # has_rqth non fourni -> False par défaut -> aide non éligible.
    corps = client.post(
        f"{BASE}/calculate", json={"age": 20, "statut": "etudiant"}
    ).json()
    assert corps["aides"] == []


# --------------------------------------------------------------------------- #
# Localisation déduite du code postal
# --------------------------------------------------------------------------- #


def test_le_code_postal_ouvre_les_aides_regionales(client, make_aide):
    """Le front n'envoie que le code postal : la région doit en être déduite."""
    make_aide(nom="Aide Île-de-France", region="Île-de-France", montant=300.0)
    profil = {"age": 20, "statut": "etudiant", "code_postal": "93200"}

    corps = client.post(f"{BASE}/calculate", json=profil).json()
    assert [a["nom"] for a in corps["aides"]] == ["Aide Île-de-France"]

    ailleurs = client.post(f"{BASE}/calculate", json={**profil, "code_postal": "31000"}).json()
    assert ailleurs["aides"] == []


def test_le_code_postal_ouvre_les_aides_departementales(client, make_aide):
    make_aide(nom="Aide Guadeloupe", departement="971", montant=400.0)
    corps = client.post(
        f"{BASE}/calculate", json={"age": 20, "statut": "etudiant", "code_postal": "97110"}
    ).json()
    assert [a["nom"] for a in corps["aides"]] == ["Aide Guadeloupe"]


def test_une_region_explicite_prime_sur_le_code_postal(client, make_aide):
    make_aide(nom="Aide Occitanie", region="Occitanie", montant=300.0)
    corps = client.post(
        f"{BASE}/calculate",
        json={"age": 20, "statut": "etudiant", "code_postal": "75001", "region": "Occitanie"},
    ).json()
    assert len(corps["aides"]) == 1


@pytest.mark.parametrize("code_postal", ["7500", "750011", "75A01"])
def test_code_postal_mal_forme_refuse(client, code_postal):
    response = client.post(
        f"{BASE}/calculate", json={"age": 20, "statut": "etudiant", "code_postal": code_postal}
    )
    assert response.status_code == 422


def test_le_statut_chomeur_obtient_les_aides_des_demandeurs_demploi(client, make_aide):
    make_aide(nom="CPF", statut_requis=["salarie", "demandeur_emploi"], montant=900.0)
    corps = client.post(f"{BASE}/calculate", json={"age": 30, "statut": "chomeur"}).json()
    assert [a["nom"] for a in corps["aides"]] == ["CPF"]


def test_les_prets_sont_totalises_a_part(client, make_aide):
    make_aide(nom="Aide", montant=500.0)
    make_aide(nom="Prêt", categorie="Prêt", montant=1200.0)
    corps = client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT).json()
    assert corps["total_potentiel"] == 500.0
    assert corps["total_prets"] == 1200.0


# --------------------------------------------------------------------------- #
# Sauvegarde automatique de la recherche
# --------------------------------------------------------------------------- #


def test_calcul_anonyme_ne_sauvegarde_rien(client, make_aide, db):
    make_aide(montant=1200.0)
    client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT)
    with db() as session:
        assert session.query(AideSave).count() == 0


def test_calcul_connecte_sauvegarde_la_recherche(client, login, make_aide, db):
    user_id = login()
    make_aide(nom="Permis à 1 €", montant=1200.0)

    client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT)

    with db() as session:
        sauvegarde = session.query(AideSave).one()
        assert sauvegarde.user_id == user_id
        assert sauvegarde.profile["statut"] == "etudiant"
        assert sauvegarde.total_potentiel == 1200.0
        assert [a["nom"] for a in sauvegarde.aides] == ["Permis à 1 €"]


def test_calcul_connecte_avec_un_cookie_invalide_ne_sauvegarde_pas(client, make_aide, db):
    make_aide(montant=1200.0)
    client.cookies.set("access_token", "jeton-invalide")
    response = client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT)
    assert response.status_code == 200
    with db() as session:
        assert session.query(AideSave).count() == 0


def test_chaque_calcul_cree_une_entree(client, login, make_aide, db):
    login()
    make_aide(montant=1200.0)
    client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT)
    client.post(f"{BASE}/calculate", json={**PROFIL_ETUDIANT, "age": 21})
    with db() as session:
        assert session.query(AideSave).count() == 2


# --------------------------------------------------------------------------- #
# Historique
# --------------------------------------------------------------------------- #


def test_historique_exige_une_authentification(client):
    response = client.get(f"{BASE}/saves")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_historique_vide(client, login):
    login()
    response = client.get(f"{BASE}/saves")
    assert response.status_code == 200
    assert response.json() == []


def test_historique_retourne_les_recherches(client, login, make_aide):
    login()
    make_aide(nom="Permis à 1 €", montant=1200.0)
    client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT)

    response = client.get(f"{BASE}/saves")
    assert response.status_code == 200
    entree = response.json()[0]
    assert entree["total_potentiel"] == 1200.0
    assert entree["profile"]["age"] == 20
    assert [a["nom"] for a in entree["aides"]] == ["Permis à 1 €"]
    assert entree["created_at"]


def test_historique_est_cloisonne_par_utilisateur(client, login, make_aide):
    make_aide(montant=1200.0)

    login(email="alice@example.com")
    client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT)
    assert len(client.get(f"{BASE}/saves").json()) == 1

    client.cookies.clear()
    login(email="bob@example.com")
    assert client.get(f"{BASE}/saves").json() == []


def test_historique_fige_le_resultat_meme_si_laide_change(client, login, make_aide, db):
    """Le détail sauvegardé est un instantané : il ne suit pas les évolutions."""
    from app.api.models.aide import AideDB

    login()
    aide_id = make_aide(nom="Aide d'origine", montant=1200.0)
    client.post(f"{BASE}/calculate", json=PROFIL_ETUDIANT)

    with db() as session:
        aide = session.query(AideDB).filter(AideDB.id == aide_id).one()
        aide.nom = "Aide renommée"
        aide.montant = 10.0
        session.commit()

    entree = client.get(f"{BASE}/saves").json()[0]
    assert entree["aides"][0]["nom"] == "Aide d'origine"
    assert entree["total_potentiel"] == 1200.0
