import json
import math
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AutoEcole, User, Favorite
from app.schemas import AutoEcoleResponse, FavoriteCreate
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/ecoles", tags=["ecoles"])

PRICE_SORT_VALUES = {"asc", "desc"}
SPEED_VALUES = {"rapide", "moyen", "faible"}
PERMIS_VALUES = {"voiture", "moto", "poids_lourd"}
DEFAULT_SCORE_BUDGET_MIN = 500
DEFAULT_SCORE_BUDGET_MAX = 2000
SPEED_SCORE = {
    "rapide": 100,
    "moyen": 74,
    "faible": 48,
}
PERMIS_ALIASES = {
    "b": "voiture",
    "voiture": "voiture",
    "car": "voiture",
    "a": "moto",
    "moto": "moto",
    "c": "poids_lourd",
    "poids_lourd": "poids_lourd",
    "poids-lourd": "poids_lourd",
}


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Retourne la distance en km entre deux points (formule de Haversine)."""
    earth_radius_km = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlng / 2) ** 2
    return earth_radius_km * 2 * math.asin(math.sqrt(a))


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return min(max(value, lower), upper)


def score_label(score: int) -> str:
    if score >= 90:
        return "90+ Excellent"
    if score >= 80:
        return "80+ Très bon"
    if score >= 70:
        return "70+ Bon"
    return "À comparer"


def compute_price_score(price: Optional[int], budget_min: Optional[int], budget_max: Optional[int]) -> float:
    if price is None:
        return 50.0

    effective_min = budget_min if budget_min is not None else DEFAULT_SCORE_BUDGET_MIN
    effective_max = budget_max if budget_max is not None else DEFAULT_SCORE_BUDGET_MAX

    if effective_max <= effective_min:
        return 100.0 if price <= effective_min else 0.0

    return clamp(((effective_max - price) / (effective_max - effective_min)) * 100)


def compute_distance_score(distance: Optional[float], radius: float) -> float:
    if distance is None:
        return 75.0

    if radius <= 0:
        return 0.0

    return clamp((1 - (distance / radius)) * 100)


def compute_match(
    item: dict,
    *,
    radius: float,
    budget_min: Optional[int],
    budget_max: Optional[int],
) -> None:
    speed_value = item.get("speed_level")
    speed_score = SPEED_SCORE.get(str(speed_value) if speed_value else "", SPEED_SCORE["moyen"])
    rating_score = clamp((item.get("rating") or 0) / 5 * 100)
    price_score = compute_price_score(item.get("price"), budget_min, budget_max)
    distance_score = compute_distance_score(item.get("distance"), radius)

    score = round(
        (speed_score * 0.35)
        + (rating_score * 0.25)
        + (price_score * 0.25)
        + (distance_score * 0.15)
    )

    reasons = []
    rating = item.get("rating") or 0
    distance = item.get("distance")

    if speed_value == "rapide":
        reasons.append("Délai rapide")
    elif speed_value == "moyen":
        reasons.append("Délai maîtrisé")

    if rating >= 4.6:
        reasons.append("Très bien notée")
    elif rating >= 4.3:
        reasons.append("Bonne note")

    if price_score >= 80:
        reasons.append("Prix compétitif")
    elif price_score <= 45:
        reasons.append("Budget plus élevé")

    if distance is not None:
        if distance <= 3:
            reasons.append("Très proche")
        elif distance <= 10:
            reasons.append("Proche")

    item["match_score"] = int(clamp(score))
    item["match_label"] = score_label(item["match_score"])
    item["match_reasons"] = reasons[:3]


LIKE_ESCAPE_CHAR = "!"


def like_pattern(value: str) -> str:
    """Motif LIKE « contient », jokers SQL neutralisés."""
    for char in (LIKE_ESCAPE_CHAR, "%", "_"):
        value = value.replace(char, f"{LIKE_ESCAPE_CHAR}{char}")
    return f"%{value}%"


def tag_filter(tag_label: str):
    """Filtre sur la présence d'un libellé dans la colonne JSON ``tags``.

    Le contenu d'une colonne ``JSON`` est conservé tel que le sérialiseur l'a
    produit : avec ``json.dumps`` par défaut (``ensure_ascii=True``), « Boîte
    Auto » est stocké « Bo\\u00eete Auto ». Une recherche sur le libellé
    accentué seul ne remonte donc rien. On accepte les deux formes.

    ``escape`` est forcé sur ``!`` car PostgreSQL utilise ``\\`` comme caractère
    d'échappement LIKE par défaut, ce qui casserait la forme échappée.
    """
    colonne = cast(AutoEcole.tags, String)
    variantes = {tag_label, json.dumps(tag_label)[1:-1]}
    return or_(
        *(
            colonne.ilike(like_pattern(variante), escape=LIKE_ESCAPE_CHAR)
            for variante in variantes
        )
    )


def normalize_permis(raw_value: str) -> str:
    normalized = PERMIS_ALIASES.get(raw_value.lower(), raw_value.lower())
    if normalized not in PERMIS_VALUES:
        raise HTTPException(
            status_code=400,
            detail="permis invalide. Valeurs supportées: voiture, moto, poids_lourd.",
        )
    return normalized


# Colonnes réellement exposées par ``AutoEcoleResponse``, dans l'ordre de ses
# champs. Les projeter explicitement évite de matérialiser des entités ORM
# complètes (carte d'identité, instrumentation d'attributs, suivi des
# modifications) pour des lignes qui ne sont que lues et sérialisées.
ECOLE_COLUMNS = (
    AutoEcole.id,
    AutoEcole.name,
    AutoEcole.city,
    AutoEcole.postal_code,
    AutoEcole.address,
    AutoEcole.lat,
    AutoEcole.lng,
    AutoEcole.rating,
    AutoEcole.price,
    AutoEcole.price_label,
    AutoEcole.speed_level,
    AutoEcole.speed_label,
    AutoEcole.permis_type,
    AutoEcole.tags,
    AutoEcole.image_url,
)


@router.get("", response_model=List[AutoEcoleResponse])
def list_ecoles(
    lat: Optional[float] = Query(None, description="Latitude du point de référence"),
    lng: Optional[float] = Query(None, description="Longitude du point de référence"),
    radius: float = Query(10.0, ge=1, le=100, description="Rayon en km"),
    gear: Optional[str] = Query(None, description="Filtre boîte : 'auto' ou 'manuelle'"),
    budget_min: Optional[int] = Query(None, ge=0, description="Budget minimum en euros"),
    budget_max: Optional[int] = Query(None, ge=0, description="Budget maximum en euros"),
    price_sort: Optional[str] = Query(None, description="Tri prix: 'asc' ou 'desc'"),
    speed: Optional[str] = Query(
        None, description="Rapidité: 'rapide', 'moyen' ou 'faible'"
    ),
    min_score: Optional[int] = Query(None, ge=0, le=100, description="Score global minimum"),
    permis: Optional[str] = Query(
        None, description="Type de permis: voiture, moto, poids_lourd"
    ),
    db: Session = Depends(get_db),
):
    if (lat is None) != (lng is None):
        raise HTTPException(
            status_code=400, detail="Les paramètres lat et lng doivent être fournis ensemble."
        )

    if budget_min is not None and budget_max is not None and budget_min > budget_max:
        raise HTTPException(
            status_code=400, detail="budget_min doit être inférieur ou égal à budget_max."
        )

    normalized_price_sort = price_sort.lower() if price_sort else None
    if normalized_price_sort and normalized_price_sort not in PRICE_SORT_VALUES:
        raise HTTPException(
            status_code=400, detail="price_sort invalide. Valeurs supportées: asc, desc."
        )

    normalized_speed = speed.lower() if speed else None
    if normalized_speed and normalized_speed not in SPEED_VALUES:
        raise HTTPException(
            status_code=400,
            detail="speed invalide. Valeurs supportées: rapide, moyen, faible.",
        )

    normalized_permis = normalize_permis(permis) if permis else None

    query = db.query(*ECOLE_COLUMNS)

    # Pré-filtre bounding box en SQL avant le calcul Haversine.
    if lat is not None and lng is not None:
        lat_delta = radius / 111.0
        cos_lat = max(abs(math.cos(math.radians(lat))), 1e-12)
        lng_delta = radius / (111.0 * cos_lat)
        query = query.filter(
            AutoEcole.lat.between(lat - lat_delta, lat + lat_delta),
            AutoEcole.lng.between(lng - lng_delta, lng + lng_delta),
        )

    # Filtre boîte de vitesse via les tags JSONB.
    if gear:
        label_map = {"auto": "Boîte Auto", "manuelle": "Boîte Manuelle"}
        tag_label = label_map.get(gear.lower(), gear)
        query = query.filter(tag_filter(tag_label))

    if budget_min is not None:
        query = query.filter(AutoEcole.price.isnot(None), AutoEcole.price >= budget_min)

    if budget_max is not None:
        query = query.filter(AutoEcole.price.isnot(None), AutoEcole.price <= budget_max)

    if normalized_speed:
        query = query.filter(AutoEcole.speed_level == normalized_speed)

    if normalized_permis:
        query = query.filter(AutoEcole.permis_type == normalized_permis)

    ecoles = query.all()

    # Le pré-filtre SQL est une boîte englobante : une partie des lignes
    # remontées dépasse le rayon réel. On tranche la distance avant de
    # construire l'item, plutôt que d'assembler un dictionnaire jeté juste
    # après.
    geolocalise = lat is not None and lng is not None

    result = []
    for row in ecoles:
        distance = None
        if geolocalise:
            distance = haversine(lat, lng, row[5], row[6])
            if distance > radius:
                continue
            distance = round(distance, 2)

        # Construit directement la forme produite par
        # ``AutoEcoleResponse.model_dump()`` : mêmes clés, même ordre, mêmes
        # valeurs. ``response_model`` valide toujours le résultat en sortie,
        # ce qui garantit types et ordre des champs dans le JSON émis.
        item = {
            "id": row[0],
            "name": row[1],
            "city": row[2],
            "postal_code": row[3],
            "address": row[4],
            "lat": row[5],
            "lng": row[6],
            "rating": row[7],
            "price": row[8],
            "price_label": row[9],
            "speed_level": row[10],
            "speed_label": row[11],
            "permis_type": row[12],
            "tags": row[13],
            "image_url": row[14],
            "distance": distance,
            "match_score": None,
            "match_label": None,
            "match_reasons": [],
        }

        compute_match(
            item,
            radius=radius,
            budget_min=budget_min,
            budget_max=budget_max,
        )

        if min_score is not None and item["match_score"] < min_score:
            continue

        result.append(item)

    if normalized_price_sort == "asc":
        result.sort(
            key=lambda x: (
                x.get("price") is None,
                x.get("price") if x.get("price") is not None else 10**9,
                x.get("distance") if x.get("distance") is not None else 9999,
            )
        )
    elif normalized_price_sort == "desc":
        result.sort(
            key=lambda x: (
                x.get("price") is None,
                -(int(str(x.get("price"))) if x.get("price") is not None else 0),
                x.get("distance") if x.get("distance") is not None else 9999,
            )
        )
    else:
        result.sort(
            key=lambda x: (
                -(x.get("match_score") or 0),
                x.get("distance") if x.get("distance") is not None else 9999,
                x.get("price") if x.get("price") is not None else 10**9,
            )
        )

    return result


@router.get("/favorites", response_model=List[AutoEcoleResponse])
def list_favorites(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Liste des auto-écoles likées par l'utilisateur connecté (plus récentes d'abord)."""
    return (
        db.query(AutoEcole)
        .join(Favorite, Favorite.auto_ecole_id == AutoEcole.id)
        .filter(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
        .all()
    )


@router.post("/favorites", status_code=201)
def add_favorite(
    payload: FavoriteCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ajoute une auto-école aux favoris (idempotent)."""
    ecole = db.query(AutoEcole).filter(AutoEcole.id == payload.auto_ecole_id).first()
    if not ecole:
        raise HTTPException(status_code=404, detail="Auto-école non trouvée.")

    existing = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.auto_ecole_id == payload.auto_ecole_id)
        .first()
    )
    if not existing:
        db.add(Favorite(user_id=user.id, auto_ecole_id=payload.auto_ecole_id))
        db.commit()

    return {"status": "ok"}


@router.delete("/favorites/{auto_ecole_id}", status_code=204)
def remove_favorite(
    auto_ecole_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retire une auto-école des favoris."""
    favorite = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.auto_ecole_id == auto_ecole_id)
        .first()
    )
    if favorite:
        db.delete(favorite)
        db.commit()


@router.get("/{ecole_id}", response_model=AutoEcoleResponse)
def get_ecole(ecole_id: int, db: Session = Depends(get_db)):
    ecole = db.query(AutoEcole).filter(AutoEcole.id == ecole_id).first()
    if not ecole:
        raise HTTPException(status_code=404, detail="Auto-école non trouvée.")
    return ecole
