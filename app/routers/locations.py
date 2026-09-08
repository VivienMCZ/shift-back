import asyncio

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/locations", tags=["locations"])

ADRESSE_API = "https://api-adresse.data.gouv.fr"
REQUEST_TIMEOUT = 5.0

_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def get_client() -> httpx.AsyncClient:
    """Client HTTP partagé vers l'API adresse de data.gouv.fr.

    Instancier un client par requête rouvre une connexion TCP **et** rejoue la
    poignée de main TLS à chaque appel, soit deux allers-retours vers un
    service distant avant même d'émettre la requête utile. L'autocomplétion
    d'adresse frappant cette route à chaque caractère saisi, c'est le poste de
    latence dominant du champ de recherche. Un client unique garde les
    connexions ouvertes (keep-alive) et réutilise la session TLS.

    Créé paresseusement : le module est importé au démarrage, hors boucle
    d'événements.
    """
    global _client
    if _client is None or _client.is_closed:
        async with _client_lock:
            if _client is None or _client.is_closed:
                _client = httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT,
                    limits=httpx.Limits(
                        max_connections=50,
                        max_keepalive_connections=20,
                        keepalive_expiry=60.0,
                    ),
                )
    return _client


async def close_client() -> None:
    """Referme le client partagé à l'arrêt de l'application."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


@router.get("/search")
async def search_location(q: str = Query(..., min_length=2)):
    """Proxy vers api-adresse.data.gouv.fr — recherche d'adresses complètes."""
    url = f"{ADRESSE_API}/search/"
    client = await get_client()
    try:
        res = await client.get(
            url,
            params={"q": q, "autocomplete": 1, "limit": 8},
            timeout=REQUEST_TIMEOUT,
        )
        res.raise_for_status()
        return res.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Service de géocodage indisponible.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Erreur géocodage.")


@router.get("/reverse")
async def reverse_location(lat: float, lng: float):
    """Proxy vers api-adresse.data.gouv.fr — géocodage inverse."""
    url = f"{ADRESSE_API}/reverse/"
    client = await get_client()
    try:
        res = await client.get(
            url, params={"lon": lng, "lat": lat}, timeout=REQUEST_TIMEOUT
        )
        res.raise_for_status()
        data = res.json()
        if not data.get("features"):
            raise HTTPException(status_code=404, detail="Aucune adresse trouvée pour ces coordonnées.")
        return data
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Service de géocodage indisponible.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Erreur géocodage inverse.")
