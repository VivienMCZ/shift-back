"""Tests du proxy de géocodage ``/api/locations``.

L'API adresse de data.gouv.fr est simulée : aucun appel réseau n'est effectué,
la suite reste donc déterministe et exécutable hors ligne en CI.
"""

import asyncio

import httpx
import pytest

from app.routers import locations

BASE = "/api/locations"

REPONSE_SEARCH = {
    "type": "FeatureCollection",
    "features": [
        {
            "properties": {"label": "1 Rue de Rivoli 75001 Paris", "city": "Paris"},
            "geometry": {"type": "Point", "coordinates": [2.3522, 48.8566]},
        }
    ],
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api-adresse.data.gouv.fr/search/")
            raise httpx.HTTPStatusError(
                "erreur amont",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


class FakeAsyncClient:
    """Remplace le client partagé : enregistre l'appel et rejoue un scénario."""

    appels = []

    def __init__(self, comportement):
        self._comportement = comportement

    async def get(self, url, params=None, timeout=None):
        FakeAsyncClient.appels.append({"url": url, "params": params, "timeout": timeout})
        return self._comportement()


@pytest.fixture
def fake_httpx(monkeypatch):
    """Installe un faux client HTTP ; renvoie une fonction de configuration.

    Le routeur ne construit plus un client par requête : il en réclame un à
    ``locations.get_client``. C'est donc ce point d'accès qui est simulé.
    """
    FakeAsyncClient.appels = []

    def _installer(comportement):
        faux = FakeAsyncClient(comportement)

        async def _get_client():
            return faux

        monkeypatch.setattr(locations, "get_client", _get_client)
        return FakeAsyncClient.appels

    return _installer


def repond(payload, status_code=200):
    return lambda: FakeResponse(payload, status_code)


def leve(exception):
    def _lever():
        raise exception

    return _lever


# --------------------------------------------------------------------------- #
# /search
# --------------------------------------------------------------------------- #


def test_search_relaie_la_reponse_amont(client, fake_httpx):
    appels = fake_httpx(repond(REPONSE_SEARCH))
    response = client.get(f"{BASE}/search", params={"q": "rue de rivoli"})
    assert response.status_code == 200
    assert response.json() == REPONSE_SEARCH
    assert appels[0]["url"] == "https://api-adresse.data.gouv.fr/search/"
    assert appels[0]["params"]["q"] == "rue de rivoli"


def test_search_transmet_les_parametres_dautocompletion(client, fake_httpx):
    appels = fake_httpx(repond(REPONSE_SEARCH))
    client.get(f"{BASE}/search", params={"q": "paris"})
    assert appels[0]["params"] == {"q": "paris", "autocomplete": 1, "limit": 8}
    assert appels[0]["timeout"] == 5.0


@pytest.mark.parametrize("q", ["", "a"])
def test_search_refuse_une_requete_trop_courte(client, q):
    response = client.get(f"{BASE}/search", params={"q": q})
    assert response.status_code == 422


def test_search_sans_parametre(client):
    assert client.get(f"{BASE}/search").status_code == 422


def test_search_timeout_amont(client, fake_httpx):
    fake_httpx(leve(httpx.TimeoutException("trop lent")))
    response = client.get(f"{BASE}/search", params={"q": "paris"})
    assert response.status_code == 504
    assert response.json()["detail"] == "Service de géocodage indisponible."


@pytest.mark.parametrize("code", [400, 429, 500, 503])
def test_search_propage_le_code_derreur_amont(client, fake_httpx, code):
    fake_httpx(repond({}, status_code=code))
    response = client.get(f"{BASE}/search", params={"q": "paris"})
    assert response.status_code == code
    assert response.json()["detail"] == "Erreur géocodage."


# --------------------------------------------------------------------------- #
# /reverse
# --------------------------------------------------------------------------- #


def test_reverse_relaie_la_reponse_amont(client, fake_httpx):
    appels = fake_httpx(repond(REPONSE_SEARCH))
    response = client.get(f"{BASE}/reverse", params={"lat": 48.8566, "lng": 2.3522})
    assert response.status_code == 200
    assert response.json() == REPONSE_SEARCH
    assert appels[0]["url"] == "https://api-adresse.data.gouv.fr/reverse/"


def test_reverse_convertit_lng_en_lon_pour_lamont(client, fake_httpx):
    appels = fake_httpx(repond(REPONSE_SEARCH))
    client.get(f"{BASE}/reverse", params={"lat": 48.8566, "lng": 2.3522})
    assert appels[0]["params"] == {"lon": 2.3522, "lat": 48.8566}


def test_reverse_sans_resultat(client, fake_httpx):
    fake_httpx(repond({"type": "FeatureCollection", "features": []}))
    response = client.get(f"{BASE}/reverse", params={"lat": 0.0, "lng": 0.0})
    assert response.status_code == 404
    assert response.json()["detail"] == "Aucune adresse trouvée pour ces coordonnées."


def test_reverse_timeout_amont(client, fake_httpx):
    fake_httpx(leve(httpx.TimeoutException("trop lent")))
    response = client.get(f"{BASE}/reverse", params={"lat": 48.85, "lng": 2.35})
    assert response.status_code == 504


def test_reverse_propage_le_code_derreur_amont(client, fake_httpx):
    fake_httpx(repond({}, status_code=502))
    response = client.get(f"{BASE}/reverse", params={"lat": 48.85, "lng": 2.35})
    assert response.status_code == 502
    assert response.json()["detail"] == "Erreur géocodage inverse."


@pytest.mark.parametrize(
    "params", [{"lat": 48.85}, {"lng": 2.35}, {}, {"lat": "nord", "lng": 2.35}]
)
def test_reverse_parametres_invalides(client, params):
    assert client.get(f"{BASE}/reverse", params=params).status_code == 422


# --------------------------------------------------------------------------- #
# Client partagé
# --------------------------------------------------------------------------- #


@pytest.fixture
def client_partage_neuf():
    """Repart d'un client partagé non initialisé et le referme après le test."""
    locations._client = None
    yield
    asyncio.run(locations.close_client())


def test_get_client_reutilise_la_meme_connexion(client_partage_neuf):
    """La poignée de main TLS ne doit pas être rejouée à chaque frappe clavier."""

    async def scenario():
        premier = await locations.get_client()
        second = await locations.get_client()
        return premier, second

    premier, second = asyncio.run(scenario())
    assert premier is second
    assert not premier.is_closed


def test_close_client_referme_et_permet_un_nouveau_client(client_partage_neuf):
    """Après l'arrêt de l'application, un client neuf est reconstruit à la demande."""

    async def scenario():
        premier = await locations.get_client()
        await locations.close_client()
        second = await locations.get_client()
        return premier, second

    premier, second = asyncio.run(scenario())
    assert premier.is_closed
    assert second is not premier
    assert not second.is_closed


def test_close_client_est_idempotent(client_partage_neuf):
    """Un double arrêt ne doit pas lever."""
    asyncio.run(locations.close_client())
    asyncio.run(locations.close_client())

