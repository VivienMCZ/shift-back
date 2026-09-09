import asyncio
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.config import get_env_bool, get_env_int

router = APIRouter(prefix="/api/locations", tags=["locations"])

# Base Adresse Nationale, servie par la Géoplateforme de l'IGN.
#
# L'ancienne adresse ``https://api-adresse.data.gouv.fr`` répond encore, mais
# renvoie depuis le 31 janvier 2026 les en-têtes HTTP ``Deprecation`` et
# ``Sunset`` (RFC 8594) pointant vers cet hôte : elle peut être coupée sans
# préavis. Les deux services renvoient le même GeoJSON, aux mêmes champs, pour
# les mêmes paramètres.
#
# Surchargeable par l'environnement pour permettre un retour arrière immédiat
# sans redéploiement.
DEFAULT_ADRESSE_API = "https://data.geopf.fr/geocodage"
ADRESSE_API = os.environ.get("ADRESSE_API_URL", DEFAULT_ADRESSE_API).rstrip("/")
REQUEST_TIMEOUT = 5.0

# --------------------------------------------------------------------------- #
# Cache des réponses amont
# --------------------------------------------------------------------------- #

# La Géoplateforme annonce un quota de 1 requête/seconde (en-tête
# ``x-ratelimit-limit-second``). Comme l'API appelle le service *depuis le
# serveur*, ce quota n'est pas par visiteur : tous les utilisateurs du site le
# partagent via une seule adresse IP. Une autocomplétion qui interroge à chaque
# frappe le sature en quelques visiteurs simultanés, et l'amont répond alors 429.
#
# Les adresses ne bougent pas d'une minute à l'autre : mémoriser les réponses
# absorbe les frappes successives d'un même utilisateur (« rue », « rue d »,
# « rue de »… quand il revient en arrière) et les recherches identiques entre
# utilisateurs, sans changer une seule réponse rendue.
CACHE_ENABLED = get_env_bool("GEOCODE_CACHE_ENABLED", True)
CACHE_TTL_SECONDS = get_env_int("GEOCODE_CACHE_TTL_SECONDS", 600)
CACHE_MAX_ENTRIES = get_env_int("GEOCODE_CACHE_MAX_ENTRIES", 1000)


class ReponseCache:
    """Cache mémoire à expiration, borné en nombre d'entrées.

    La borne n'est pas cosmétique : la clé dérive d'une saisie utilisateur
    libre, donc sans plafond un appelant pourrait faire grossir le cache
    indéfiniment en variant sa requête. Au-delà de ``max_entries``, l'entrée la
    moins récemment lue est évincée.

    Même limite que les compteurs d'``app.security`` : le cache vit dans la
    mémoire du processus et n'est donc pas partagé entre plusieurs instances.
    """

    def __init__(self, max_entries: int, ttl_seconds: float):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, payload = entry
            if expires_at <= time.monotonic():
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return payload

    def set(self, key: str, payload: Any) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic() + self.ttl_seconds, payload)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


geocode_cache = ReponseCache(CACHE_MAX_ENTRIES, CACHE_TTL_SECONDS)


def _lire_cache(cle: str) -> Any | None:
    return geocode_cache.get(cle) if CACHE_ENABLED else None


def _ecrire_cache(cle: str, payload: Any) -> None:
    if CACHE_ENABLED:
        geocode_cache.set(cle, payload)


# --------------------------------------------------------------------------- #
# Client HTTP partagé
# --------------------------------------------------------------------------- #

_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def get_client() -> httpx.AsyncClient:
    """Client HTTP partagé vers l'API de géocodage de la Géoplateforme.

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
    """Proxy vers la Base Adresse Nationale — recherche d'adresses complètes."""
    # Clé sur la saisie brute : normaliser (casse, espaces) supposerait que
    # l'amont traite ces variantes à l'identique, ce qui n'est pas garanti.
    cle = f"search:{q}"
    en_cache = _lire_cache(cle)
    if en_cache is not None:
        return en_cache

    url = f"{ADRESSE_API}/search/"
    client = await get_client()
    try:
        res = await client.get(
            url,
            params={"q": q, "autocomplete": 1, "limit": 8},
            timeout=REQUEST_TIMEOUT,
        )
        res.raise_for_status()
        data = res.json()
        _ecrire_cache(cle, data)
        return data
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Service de géocodage indisponible.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Erreur géocodage.")


@router.get("/reverse")
async def reverse_location(lat: float, lng: float):
    """Proxy vers la Base Adresse Nationale — géocodage inverse."""
    cle = f"reverse:{lat}:{lng}"
    data = _lire_cache(cle)

    if data is None:
        url = f"{ADRESSE_API}/reverse/"
        client = await get_client()
        try:
            res = await client.get(
                url, params={"lon": lng, "lat": lat}, timeout=REQUEST_TIMEOUT
            )
            res.raise_for_status()
            data = res.json()
            _ecrire_cache(cle, data)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Service de géocodage indisponible.")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail="Erreur géocodage inverse.")

    # Vérifié après le cache : une réponse amont vide reste un 404, qu'elle
    # vienne du réseau ou de la mémoire.
    if not data.get("features"):
        raise HTTPException(status_code=404, detail="Aucune adresse trouvée pour ces coordonnées.")
    return data
