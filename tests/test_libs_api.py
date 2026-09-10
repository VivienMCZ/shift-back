"""Tests d'intégration du routeur ``/api/v1/libs`` (libellés et traductions)."""

import pytest


BASE = "/api/v1/libs"


# --------------------------------------------------------------------------- #
# Lecture
# --------------------------------------------------------------------------- #


def test_liste_vide(client):
    response = client.get(f"{BASE}/")
    assert response.status_code == 200
    assert response.json() == []


def test_liste_des_libelles(client, make_lib):
    make_lib(key="a.b", fr="Bonjour", en="Hello")
    make_lib(key="c.d", fr="Au revoir", en="Goodbye")
    response = client.get(f"{BASE}/")
    assert response.status_code == 200
    assert {item["key"] for item in response.json()} == {"a.b", "c.d"}


def test_detail_par_cle(client, make_lib):
    make_lib(key="home.title", fr="Accueil", en="Home")
    response = client.get(f"{BASE}/home.title")
    assert response.status_code == 200
    assert response.json()["fr"] == "Accueil"
    assert response.json()["en"] == "Home"


def test_detail_cle_inconnue(client):
    response = client.get(f"{BASE}/cle.inconnue")
    assert response.status_code == 404
    assert response.json()["detail"] == "Lib not found"


# --------------------------------------------------------------------------- #
# Dictionnaire complet
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "lang,attendu",
    [("fr", {"home.title": "Accueil", "nav.back": "Retour"}),
     ("en", {"home.title": "Home", "nav.back": "Back"})],
)
def test_dictionnaire_complet(client, make_lib, lang, attendu):
    make_lib(key="home.title", fr="Accueil", en="Home")
    make_lib(key="nav.back", fr="Retour", en="Back")
    response = client.get(f"{BASE}/dictionary", params={"lang": lang})
    assert response.status_code == 200
    assert response.json() == attendu


def test_dictionnaire_langue_par_defaut_est_langlais(client, make_lib):
    make_lib(key="home.title", fr="Accueil", en="Home")
    assert client.get(f"{BASE}/dictionary").json() == {"home.title": "Home"}


@pytest.mark.parametrize("lang", ["de", "id", "created_at", "FR"])
def test_dictionnaire_langue_non_supportee(client, make_lib, lang):
    """``lang`` sert d'attribut de colonne : la liste blanche est le garde-fou."""
    make_lib(key="home.title")
    response = client.get(f"{BASE}/dictionary", params={"lang": lang})
    assert response.status_code == 400
    assert response.json()["detail"] == "Langue non supportée"


def test_dictionnaire_vide(client):
    response = client.get(f"{BASE}/dictionary")
    assert response.status_code == 200
    assert response.json() == {}


def test_dictionnaire_revalide_en_304(client, make_lib):
    make_lib(key="home.title", fr="Accueil", en="Home")
    premiere = client.get(f"{BASE}/dictionary", params={"lang": "fr"})
    etag = premiere.headers["etag"]
    assert "max-age" in premiere.headers["cache-control"]

    seconde = client.get(
        f"{BASE}/dictionary", params={"lang": "fr"}, headers={"If-None-Match": etag}
    )
    assert seconde.status_code == 304
    assert seconde.content == b""
    assert seconde.headers["etag"] == etag


def test_dictionnaire_etag_change_quand_le_texte_change(client, make_lib, admin_headers):
    make_lib(key="home.title", fr="Accueil", en="Home")
    etag = client.get(f"{BASE}/dictionary", params={"lang": "fr"}).headers["etag"]

    client.put(
        f"{BASE}/home.title",
        json={"fr": "Bienvenue"},
        headers=admin_headers,
    )

    apres = client.get(
        f"{BASE}/dictionary", params={"lang": "fr"}, headers={"If-None-Match": etag}
    )
    assert apres.status_code == 200
    assert apres.json() == {"home.title": "Bienvenue"}
    assert apres.headers["etag"] != etag


def test_dictionnaire_etag_differe_selon_la_langue(client, make_lib):
    make_lib(key="home.title", fr="Accueil", en="Home")
    fr = client.get(f"{BASE}/dictionary", params={"lang": "fr"})
    en = client.get(
        f"{BASE}/dictionary",
        params={"lang": "en"},
        headers={"If-None-Match": fr.headers["etag"]},
    )
    assert en.status_code == 200
    assert en.json() == {"home.title": "Home"}


# --------------------------------------------------------------------------- #
# Traduction
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("lang,attendu", [("fr", "Accueil"), ("en", "Home")])
def test_traduction(client, make_lib, lang, attendu):
    make_lib(key="home.title", fr="Accueil", en="Home")
    response = client.get(f"{BASE}/home.title/translate", params={"lang": lang})
    assert response.status_code == 200
    assert response.json() == {"text": attendu}


def test_traduction_langue_par_defaut_est_langlais(client, make_lib):
    make_lib(key="home.title", fr="Accueil", en="Home")
    response = client.get(f"{BASE}/home.title/translate")
    assert response.json() == {"text": "Home"}


@pytest.mark.parametrize("lang", ["de", "es", "id", "", "FR"])
def test_traduction_langue_non_supportee(client, make_lib, lang):
    make_lib(key="home.title")
    response = client.get(f"{BASE}/home.title/translate", params={"lang": lang})
    assert response.status_code == 400
    assert response.json()["detail"] == "Langue non supportée"


def test_traduction_langue_non_supportee_ne_lit_pas_une_colonne_arbitraire(client, make_lib):
    """Garde-fou : ``lang`` sert d'attribut de colonne, il doit rester restreint."""
    make_lib(key="home.title")
    response = client.get(f"{BASE}/home.title/translate", params={"lang": "created_at"})
    assert response.status_code == 400


def test_traduction_cle_inconnue(client):
    response = client.get(f"{BASE}/cle.inconnue/translate", params={"lang": "fr"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Libellé introuvable"


# --------------------------------------------------------------------------- #
# Création
# --------------------------------------------------------------------------- #


def test_creation(client, admin_headers):
    response = client.post(f"{BASE}/", json={"key": "new.key", "fr": "Nouveau", "en": "New"}, headers=admin_headers)
    assert response.status_code == 201
    corps = response.json()
    assert corps["key"] == "new.key"
    assert corps["id"] > 0
    assert client.get(f"{BASE}/new.key").status_code == 200


def test_creation_cle_deja_existante(client, make_lib, admin_headers):
    make_lib(key="doublon")
    response = client.post(f"{BASE}/", json={"key": "doublon", "fr": "A", "en": "B"}, headers=admin_headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "Key already registered"


@pytest.mark.parametrize(
    "charge",
    [
        {"fr": "A", "en": "B"},
        {"key": "k", "en": "B"},
        {"key": "k", "fr": "A"},
        {},
    ],
)
def test_creation_champs_manquants(client, charge, admin_headers):
    assert client.post(f"{BASE}/", json=charge, headers=admin_headers).status_code == 422


# --------------------------------------------------------------------------- #
# Mise à jour
# --------------------------------------------------------------------------- #


def test_mise_a_jour_complete(client, make_lib, admin_headers):
    make_lib(key="maj", fr="Ancien", en="Old")
    response = client.put(f"{BASE}/maj", json={"fr": "Nouveau", "en": "New"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["fr"] == "Nouveau"
    assert response.json()["en"] == "New"


def test_mise_a_jour_partielle(client, make_lib, admin_headers):
    make_lib(key="maj", fr="Ancien", en="Old")
    response = client.put(f"{BASE}/maj", json={"fr": "Nouveau"}, headers=admin_headers)
    assert response.json()["fr"] == "Nouveau"
    assert response.json()["en"] == "Old"


def test_mise_a_jour_vide_ne_change_rien(client, make_lib, admin_headers):
    make_lib(key="maj", fr="Ancien", en="Old")
    response = client.put(f"{BASE}/maj", json={}, headers=admin_headers)
    assert response.json()["fr"] == "Ancien"


def test_mise_a_jour_cle_inconnue(client, admin_headers):
    response = client.put(f"{BASE}/inconnue", json={"fr": "X"}, headers=admin_headers)
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Suppression
# --------------------------------------------------------------------------- #


def test_suppression(client, make_lib, admin_headers):
    make_lib(key="a.supprimer")
    response = client.delete(f"{BASE}/a.supprimer", headers=admin_headers)
    assert response.status_code == 204
    assert client.get(f"{BASE}/a.supprimer").status_code == 404


def test_suppression_cle_inconnue(client, admin_headers):
    assert client.delete(f"{BASE}/inconnue", headers=admin_headers).status_code == 404


# --------------------------------------------------------------------------- #
# Contrôle d'accès
# --------------------------------------------------------------------------- #


ECRITURES = [
    ("post", f"{BASE}/", {"key": "anon.key", "fr": "A", "en": "B"}),
    ("put", f"{BASE}/existante", {"fr": "Modifié"}),
    ("delete", f"{BASE}/existante", None),
]


def appeler(client, methode, chemin, charge, headers=None):
    appel = getattr(client, methode)
    if charge is None:
        return appel(chemin, headers=headers)
    return appel(chemin, json=charge, headers=headers)


@pytest.mark.parametrize("methode,chemin,charge", ECRITURES)
def test_ecriture_refusee_sans_jeton(client, make_lib, methode, chemin, charge):
    """A01 — ces routes pilotent le texte vu par tous les visiteurs."""
    make_lib(key="existante")
    response = appeler(client, methode, chemin, charge)
    assert response.status_code == 401


@pytest.mark.parametrize("methode,chemin,charge", ECRITURES)
def test_ecriture_refusee_avec_un_mauvais_jeton(client, make_lib, methode, chemin, charge):
    make_lib(key="existante")
    response = appeler(
        client, methode, chemin, charge, headers={"X-Admin-Token": "mauvais-jeton"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("methode,chemin,charge", ECRITURES)
def test_ecriture_refusee_si_ladministration_nest_pas_configuree(
    client, make_lib, monkeypatch, methode, chemin, charge
):
    """Échec en position fermée : sans ADMIN_API_TOKEN, aucune écriture."""
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    make_lib(key="existante")
    response = appeler(
        client, methode, chemin, charge, headers={"X-Admin-Token": "n-importe-quoi"}
    )
    assert response.status_code == 503


def test_ecriture_ne_modifie_rien_sans_jeton(client, make_lib):
    make_lib(key="existante", fr="Intact", en="Untouched")
    client.put(f"{BASE}/existante", json={"fr": "Piraté"})
    client.delete(f"{BASE}/existante")
    assert client.get(f"{BASE}/existante").json()["fr"] == "Intact"


def test_lecture_reste_publique(client, make_lib):
    """Le front consomme les libellés sans session : la lecture doit rester ouverte."""
    make_lib(key="public.key", fr="Bonjour", en="Hello")
    assert client.get(f"{BASE}/").status_code == 200
    assert client.get(f"{BASE}/public.key").status_code == 200
    assert client.get(f"{BASE}/public.key/translate").status_code == 200
