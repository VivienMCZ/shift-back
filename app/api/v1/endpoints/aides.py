from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.api.models.aide import AideDB, AideSave
from app.api.models.user_profile import UserProfile
from app.api.aide_calculator import CalculateurAides
from app.api.schemas.aide import (
    UserProfileSchema,
    CalculationResultSchema,
    AideSchema,
    AideSaveResponse,
)
from app.routers.auth import get_current_user

router = APIRouter()

def get_optional_user(request: Request, db: Session):
    """Renvoie l'utilisateur connecté, ou None si aucune session valide."""
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None

@router.post("/calculate", response_model=CalculationResultSchema)
def calculate_aides(profile: UserProfileSchema, request: Request, db: Session = Depends(get_db)):
    """
    Calcule les aides éligibles pour un profil utilisateur donné.

    Si l'utilisateur est connecté, la recherche (saisie + résultat) est
    sauvegardée pour être retrouvée dans son profil.
    """
    # Conversion vers le dataclass de logique métier
    user_profile = UserProfile(**profile.model_dump())

    # Récupération des aides en base
    all_aides = db.query(AideDB).all()

    # Calcul
    calculator = CalculateurAides(user_profile, all_aides)
    result = calculator.executer()

    # Sauvegarde de la recherche si l'utilisateur est connecté
    user = get_optional_user(request, db)
    if user:
        saved = AideSave(
            user_id=user.id,
            profile=profile.model_dump(),
            aides=[AideSchema.model_validate(a).model_dump() for a in result["aides"]],
            total_potentiel=result["total_potentiel"],
        )
        db.add(saved)
        db.commit()

    return result

@router.get("/saves", response_model=List[AideSaveResponse])
def list_aide_saves(request: Request, db: Session = Depends(get_db)):
    """Renvoie l'historique des recherches sauvegardées de l'utilisateur connecté."""
    user = get_optional_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return (
        db.query(AideSave)
        .filter(AideSave.user_id == user.id)
        .order_by(AideSave.created_at.desc())
        .all()
    )
