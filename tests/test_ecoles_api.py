"""Tests d'intégration du routeur ``/api/ecoles`` (filtres, tri, favoris)."""

import pytest

PARIS = (48.8566, 2.3522)


def noms(response):
    return [item["name"] for item in response.json()]


# --------------------------------------------------------------------------- #
# Listing et validation des paramètres
# --------------------------------------------------------------------------- #


def test_liste_vide(client):
    response = client.get("/api/ecoles")
    assert response.status_code == 200
    assert response.json() == []


def test_liste_retourne_les_ecoles_avec_le_score(client, make_ecole):
    make_ecole(name="École A")
    response = client.get("/api/ecoles")
    assert response.status_code == 200
    ecole = response.json()[0]
    assert ecole["name"] == "École A"
    assert ecole["match_score"] is not None
    assert ecole["match_label"]
    assert isinstance(ecole["match_reasons"], list)
    assert ecole["distance"] is None


def test_lat_sans_lng_est_rejete(client):
    response = client.get("/api/ecoles", params={"lat": PARIS[0]})
    assert response.status_code == 400
    assert "ensemble" in response.json()["detail"]


def test_lng_sans_lat_est_rejete(client):
    response = client.get("/api/ecoles", params={"lng": PARIS[1]})
    assert response.status_code == 400


def test_budget_min_superieur_a_budget_max_est_rejete(client):
    response = client.get("/api/ecoles", params={"budget_min": 2000, "budget_max": 1000})
    assert response.status_code == 400
    assert "budget_min" in response.json()["detail"]


def test_budget_min_egal_a_budget_max_est_accepte(client):
    response = client.get("/api/ecoles", params={"budget_min": 1000, "budget_max": 1000})
    assert response.status_code == 200


@pytest.mark.parametrize("radius", [0, 0.5, 101, 1000])
def test_rayon_hors_bornes_est_rejete(client, radius):
    response = client.get(
        "/api/ecoles", params={"lat": PARIS[0], "lng": PARIS[1], "radius": radius}
    )
    assert response.status_code == 422


def test_price_sort_invalide_est_rejete(client):
    response = client.get("/api/ecoles", params={"price_sort": "cheapest"})
    assert response.status_code == 400
    assert "price_sort" in response.json()["detail"]


def test_speed_invalide_est_rejete(client):
    response = client.get("/api/ecoles", params={"speed": "supersonique"})
    assert response.status_code == 400
    assert "speed" in response.json()["detail"]


def test_permis_invalide_est_rejete(client):
    response = client.get("/api/ecoles", params={"permis": "bateau"})
    assert response.status_code == 400
    assert "permis" in response.json()["detail"]


@pytest.mark.parametrize("min_score", [-1, 101])
def test_min_score_hors_bornes_est_rejete(client, min_score):
    response = client.get("/api/ecoles", params={"min_score": min_score})
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Filtres
# --------------------------------------------------------------------------- #


def test_filtre_geographique_exclut_les_ecoles_hors_rayon(client, make_ecole):
    make_ecole(name="Paris", lat=PARIS[0], lng=PARIS[1])
    make_ecole(name="Lyon", lat=45.7640, lng=4.8357)

    response = client.get(
        "/api/ecoles", params={"lat": PARIS[0], "lng": PARIS[1], "radius": 20}
    )
    assert noms(response) == ["Paris"]
    assert response.json()[0]["distance"] == pytest.approx(0.0, abs=0.1)


def test_filtre_geographique_exclut_les_coins_de_la_bounding_box(client, make_ecole):
    """Le pré-filtre SQL est un carré : le contrôle Haversine affine le cercle.

    L'école est dans le carré (±0,090° de latitude, ±0,137° de longitude pour
    10 km depuis Paris) mais à ~13 km en diagonale, donc hors du rayon.
    """
    make_ecole(name="Coin", lat=PARIS[0] + 0.08, lng=PARIS[1] + 0.13)
    make_ecole(name="Centre", lat=PARIS[0], lng=PARIS[1])

    response = client.get(
        "/api/ecoles", params={"lat": PARIS[0], "lng": PARIS[1], "radius": 10}
    )
    assert noms(response) == ["Centre"]


def test_filtre_geographique_calcule_la_distance(client, make_ecole):
    # ~11 km au nord de Paris.
    make_ecole(name="Nord", lat=PARIS[0] + 0.1, lng=PARIS[1])
    response = client.get(
        "/api/ecoles", params={"lat": PARIS[0], "lng": PARIS[1], "radius": 20}
    )
    assert response.json()[0]["distance"] == pytest.approx(11.1, abs=0.5)


def test_filtre_budget_min(client, make_ecole):
    make_ecole(name="Pas chère", price=900)
    make_ecole(name="Chère", price=1800)
    response = client.get("/api/ecoles", params={"budget_min": 1000})
    assert noms(response) == ["Chère"]


def test_filtre_budget_max(client, make_ecole):
    make_ecole(name="Pas chère", price=900)
    make_ecole(name="Chère", price=1800)
    response = client.get("/api/ecoles", params={"budget_max": 1000})
    assert noms(response) == ["Pas chère"]


def test_filtre_budget_exclut_les_prix_inconnus(client, make_ecole):
    make_ecole(name="Sans prix", price=None)
    make_ecole(name="Avec prix", price=1000)
    response = client.get("/api/ecoles", params={"budget_min": 0, "budget_max": 5000})
    assert noms(response) == ["Avec prix"]


def test_filtre_vitesse(client, make_ecole):
    make_ecole(name="Rapide", speed_level="rapide")
    make_ecole(name="Lente", speed_level="faible")
    response = client.get("/api/ecoles", params={"speed": "RAPIDE"})
    assert noms(response) == ["Rapide"]


def test_filtre_permis_avec_alias(client, make_ecole):
    make_ecole(name="Voiture", permis_type="voiture")
    make_ecole(name="Moto", permis_type="moto")
    response = client.get("/api/ecoles", params={"permis": "B"})
    assert noms(response) == ["Voiture"]


@pytest.mark.parametrize(
    "gear,attendu", [("auto", "Auto"), ("manuelle", "Manuelle"), ("AUTO", "Auto")]
)
def test_filtre_boite_de_vitesse_via_les_tags(client, make_ecole, gear, attendu):
    """Régression : le libellé contient un « î » non-ASCII.

    La colonne ``tags`` est de type ``JSON`` : PostgreSQL y conserve le texte
    tel quel, donc « Boîte Auto » y est stocké « Bo\\u00eete Auto ». Une simple
    recherche ``ilike('%Boîte Auto%')`` ne remontait donc jamais rien, et le
    filtre renvoyait 0 résultat pour toutes les valeurs de ``gear``.
    """
    make_ecole(name="Auto", tags=[{"label": "Boîte Auto", "color": "blue"}])
    make_ecole(name="Manuelle", tags=[{"label": "Boîte Manuelle", "color": "blue"}])
    make_ecole(name="Sans tag", tags=[])

    response = client.get("/api/ecoles", params={"gear": gear})
    assert response.status_code == 200
    assert noms(response) == [attendu]


def test_filtre_boite_gere_les_deux_encodages_json(client, make_ecole):
    """Les données déjà en base peuvent être dans l'une ou l'autre forme."""
    make_ecole(name="Échappée", tags=[{"label": "Boîte Auto"}])
    make_ecole(name="Littérale", tags=[{"label": "Boite Auto"}])
    response = client.get("/api/ecoles", params={"gear": "auto"})
    assert "Échappée" in noms(response)


def test_filtre_gear_libre_sur_un_tag_quelconque(client, make_ecole):
    make_ecole(name="Premium", tags=[{"label": "Premium", "color": "blue"}])
    make_ecole(name="Standard", tags=[{"label": "Standard", "color": "blue"}])
    response = client.get("/api/ecoles", params={"gear": "Premium"})
    assert noms(response) == ["Premium"]


def test_filtre_gear_neutralise_les_jokers_sql(client, make_ecole):
    """``%`` fourni par le client ne doit pas se comporter comme un joker."""
    make_ecole(name="Premium", tags=[{"label": "Premium", "color": "blue"}])
    response = client.get("/api/ecoles", params={"gear": "%"})
    assert response.status_code == 200
    assert noms(response) == []


def test_filtre_min_score(client, make_ecole):
    make_ecole(name="Excellente", speed_level="rapide", rating=5.0, price=500)
    make_ecole(name="Médiocre", speed_level="faible", rating=1.0, price=2000)
    response = client.get("/api/ecoles", params={"min_score": 80})
    assert noms(response) == ["Excellente"]


def test_filtres_combines(client, make_ecole):
    make_ecole(name="Cible", price=1000, speed_level="rapide", permis_type="voiture")
    make_ecole(name="Trop chère", price=3000, speed_level="rapide", permis_type="voiture")
    make_ecole(name="Trop lente", price=1000, speed_level="faible", permis_type="voiture")
    make_ecole(name="Mauvais permis", price=1000, speed_level="rapide", permis_type="moto")

    response = client.get(
        "/api/ecoles",
        params={"budget_max": 1500, "speed": "rapide", "permis": "voiture"},
    )
    assert noms(response) == ["Cible"]


# --------------------------------------------------------------------------- #
# Tri
# --------------------------------------------------------------------------- #


def test_tri_par_defaut_sur_le_score_decroissant(client, make_ecole):
    make_ecole(name="Faible", speed_level="faible", rating=2.0, price=2000)
    make_ecole(name="Fort", speed_level="rapide", rating=5.0, price=600)
    resultats = client.get("/api/ecoles").json()
    assert [e["name"] for e in resultats] == ["Fort", "Faible"]
    assert resultats[0]["match_score"] >= resultats[1]["match_score"]


def test_tri_prix_croissant(client, make_ecole):
    make_ecole(name="C", price=1800)
    make_ecole(name="A", price=800)
    make_ecole(name="B", price=1200)
    response = client.get("/api/ecoles", params={"price_sort": "asc"})
    assert noms(response) == ["A", "B", "C"]


def test_tri_prix_decroissant(client, make_ecole):
    make_ecole(name="C", price=1800)
    make_ecole(name="A", price=800)
    make_ecole(name="B", price=1200)
    response = client.get("/api/ecoles", params={"price_sort": "desc"})
    assert noms(response) == ["C", "B", "A"]


@pytest.mark.parametrize("sens", ["asc", "desc"])
def test_tri_prix_place_les_prix_inconnus_en_dernier(client, make_ecole, sens):
    make_ecole(name="Sans prix", price=None)
    make_ecole(name="Avec prix", price=1000)
    response = client.get("/api/ecoles", params={"price_sort": sens})
    assert noms(response)[-1] == "Sans prix"


def test_tri_prix_insensible_a_la_casse(client, make_ecole):
    make_ecole(name="A", price=800)
    make_ecole(name="B", price=1200)
    response = client.get("/api/ecoles", params={"price_sort": "ASC"})
    assert noms(response) == ["A", "B"]


# --------------------------------------------------------------------------- #
# Détail
# --------------------------------------------------------------------------- #


def test_detail_ecole(client, make_ecole):
    ecole_id = make_ecole(name="École détail", city="Lyon")
    response = client.get(f"/api/ecoles/{ecole_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "École détail"
    assert response.json()["city"] == "Lyon"


def test_detail_ecole_inconnue(client):
    response = client.get("/api/ecoles/99999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Auto-école non trouvée."


def test_detail_id_non_numerique(client):
    response = client.get("/api/ecoles/abc")
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Favoris
# --------------------------------------------------------------------------- #


def test_favoris_liste_exige_une_authentification(client):
    assert client.get("/api/ecoles/favorites").status_code == 401


def test_favoris_ajout_exige_une_authentification(client, make_ecole):
    ecole_id = make_ecole()
    response = client.post("/api/ecoles/favorites", json={"auto_ecole_id": ecole_id})
    assert response.status_code == 401


def test_favoris_suppression_exige_une_authentification(client):
    assert client.delete("/api/ecoles/favorites/1").status_code == 401


def test_favoris_ajout_et_liste(client, login, make_ecole):
    login()
    ecole_id = make_ecole(name="Favorite")

    ajout = client.post("/api/ecoles/favorites", json={"auto_ecole_id": ecole_id})
    assert ajout.status_code == 201
    assert ajout.json() == {"status": "ok"}

    liste = client.get("/api/ecoles/favorites")
    assert liste.status_code == 200
    assert noms(liste) == ["Favorite"]


def test_favoris_ajout_est_idempotent(client, login, make_ecole):
    login()
    ecole_id = make_ecole()

    client.post("/api/ecoles/favorites", json={"auto_ecole_id": ecole_id})
    second = client.post("/api/ecoles/favorites", json={"auto_ecole_id": ecole_id})

    assert second.status_code == 201
    assert len(client.get("/api/ecoles/favorites").json()) == 1


def test_favoris_ajout_ecole_inconnue(client, login):
    login()
    response = client.post("/api/ecoles/favorites", json={"auto_ecole_id": 99999})
    assert response.status_code == 404


def test_favoris_suppression(client, login, make_ecole):
    login()
    ecole_id = make_ecole()
    client.post("/api/ecoles/favorites", json={"auto_ecole_id": ecole_id})

    suppression = client.delete(f"/api/ecoles/favorites/{ecole_id}")
    assert suppression.status_code == 204
    assert client.get("/api/ecoles/favorites").json() == []


def test_favoris_suppression_inexistante_ne_casse_pas(client, login):
    login()
    assert client.delete("/api/ecoles/favorites/99999").status_code == 204


def test_favoris_sont_cloisonnes_par_utilisateur(client, login, make_ecole, db):
    from app.models import Favorite, User

    ecole_id = make_ecole(name="École d'Alice")
    login(email="alice@example.com")
    client.post("/api/ecoles/favorites", json={"auto_ecole_id": ecole_id})

    # Bob se connecte à son tour : il ne doit pas voir le favori d'Alice.
    client.cookies.clear()
    login(email="bob@example.com")
    assert client.get("/api/ecoles/favorites").json() == []

    with db() as session:
        alice = session.query(User).filter(User.email == "alice@example.com").one()
        assert session.query(Favorite).filter(Favorite.user_id == alice.id).count() == 1
