from fastapi import APIRouter, Query, HTTPException
import httpx

router = APIRouter(prefix="/api/locations", tags=["locations"])

ADRESSE_API = "https://api-adresse.data.gouv.fr"


@router.get("/search")
async def search_location(q: str = Query(..., min_length=2)):
    """Proxy vers api-adresse.data.gouv.fr — recherche d'adresses complètes."""
    url = f"{ADRESSE_API}/search/"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(
                url,
                params={"q": q, "autocomplete": 1, "limit": 8},
                timeout=5.0,
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
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, params={"lon": lng, "lat": lat}, timeout=5.0)
            res.raise_for_status()
            data = res.json()
            if not data.get("features"):
                raise HTTPException(status_code=404, detail="Aucune adresse trouvée pour ces coordonnées.")
            return data
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Service de géocodage indisponible.")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail="Erreur géocodage inverse.")
