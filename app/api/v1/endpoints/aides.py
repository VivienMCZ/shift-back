from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.api.geo import departement_depuis_code_postal, region_depuis_departement
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

# Réponses propres à un utilisateur : jamais mises en cache (cf. ecoles.py).
CACHE_PRIVEE = "private, no-store"

def get_optional_user(request: Request, db: Session):
    """Renvoie l'utilisateur connecté, ou None si aucune session valide."""
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


def localiser(profile: UserProfileSchema) -> dict:
    """Champs du profil, complétés par la localisation déduite du code postal.

    Une région ou un département fournis explicitement priment : ils restent le
    moyen de préciser un cas que le code postal ne tranche pas.
    """
    donnees = profile.model_dump()
    departement = donnees["departement"] or departement_depuis_code_postal(donnees["code_postal"])
    donnees["departement"] = departement
    donnees["region"] = donnees["region"] or region_depuis_departement(departement)
    return donnees


@router.post("/calculate", response_model=CalculationResultSchema)
def calculate_aides(profile: UserProfileSchema, request: Request, db: Session = Depends(get_db)):
    """
    Calcule les aides éligibles pour un profil utilisateur donné.

    Si l'utilisateur est connecté, la recherche (saisie + résultat) est
    sauvegardée pour être retrouvée dans son profil.
    """
    # Conversion vers le dataclass de logique métier
    user_profile = UserProfile(**localiser(profile))

    # Récupération des aides en base
    all_aides = db.query(AideDB).all()

    # Calcul
    calculator = CalculateurAides(user_profile, all_aides)
    result = calculator.executer()

    # Sauvegarde de la recherche si l'utilisateur est connecté.
    #
    # RGPD, article 9 : une reconnaissance de handicap est une donnée de santé.
    # La conserver exigerait un consentement explicite ; on s'en dispense en ne
    # l'enregistrant pas. Retirer le seul champ ne suffirait pas : la liste des
    # aides obtenues (AGEFIPH, PCH…) la trahirait. La recherche entière n'est
    # donc pas sauvegardée — le résultat, lui, est renvoyé normalement.
    user = get_optional_user(request, db)
    if user and not profile.has_rqth:
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
def list_aide_saves(request: Request, response: Response, db: Session = Depends(get_db)):
    """Renvoie l'historique des recherches sauvegardées de l'utilisateur connecté."""
    user = get_optional_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    response.headers["Cache-Control"] = CACHE_PRIVEE
    return (
        db.query(AideSave)
        .filter(AideSave.user_id == user.id)
        .order_by(AideSave.created_at.desc())
        .all()
    )


@router.delete("/saves/{save_id}", status_code=204)
def delete_aide_save(
    save_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Efface une recherche de l'historique (RGPD, droit à l'effacement).

    Une recherche d'un autre compte répond 404, comme une recherche inexistante :
    un 403 confirmerait son existence (A01).
    """
    saved = (
        db.query(AideSave)
        .filter(AideSave.id == save_id, AideSave.user_id == user.id)
        .first()
    )
    if not saved:
        raise HTTPException(status_code=404, detail="Recherche introuvable.")
    db.delete(saved)
    db.commit()
