"""Libellés et traductions de l'interface.

**A01 — Broken Access Control.** La lecture reste publique (le front en a besoin
sans session), mais la création, la modification et la suppression exigent
désormais un jeton d'administration : ces routes pilotent le texte affiché à
tous les visiteurs et étaient ouvertes à n'importe quel appelant anonyme.

Le contrôle échoue en position fermée : si ``ADMIN_API_TOKEN`` n'est pas
configuré, aucune écriture n'est possible.
"""

import hmac
import logging
import os
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Lib
from app.schemas import LibCreate, LibResponse, LibUpdate

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/libs",
    tags=["Libs"],
    responses={404: {"description": "Not found"}},
)

SUPPORTED_LANGUAGES = ("fr", "en")


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Vérifie le jeton d'administration transmis dans l'en-tête ``X-Admin-Token``."""
    expected = os.getenv("ADMIN_API_TOKEN")
    if not expected:
        logger.warning("Écriture sur les libellés refusée : ADMIN_API_TOKEN non configuré.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Administration des libellés non configurée.",
        )

    # Comparaison à temps constant : une comparaison ordinaire laisse fuiter la
    # longueur du préfixe correct par le temps de réponse.
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton d'administration invalide ou manquant.",
        )


@router.get("/", response_model=List[LibResponse])
def get_libs(db: Session = Depends(get_db)):
    libs = db.query(Lib).all()
    return libs


@router.get("/{key}/translate")
def get_translation(key: str, lang: str = "en", db: Session = Depends(get_db)):
    """Renvoie la traduction d'une clé dans la langue demandée.

    ``lang`` sert à sélectionner une colonne : la liste blanche est donc
    indispensable, sans elle n'importe quelle colonne du modèle serait lisible.
    """
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Langue non supportée")

    column = getattr(Lib, lang)
    text = db.query(column).filter(Lib.key == key).scalar()

    if text is None:
        raise HTTPException(status_code=404, detail="Libellé introuvable")

    return {"text": text}


@router.get("/{key}", response_model=LibResponse)
def get_lib(key: str, db: Session = Depends(get_db)):
    lib = db.query(Lib).filter(Lib.key == key).first()
    if not lib:
        raise HTTPException(status_code=404, detail="Lib not found")
    return lib


@router.post(
    "/",
    response_model=LibResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_lib(lib: LibCreate, db: Session = Depends(get_db)):
    db_lib = db.query(Lib).filter(Lib.key == lib.key).first()
    if db_lib:
        raise HTTPException(status_code=400, detail="Key already registered")
    new_lib = Lib(**lib.model_dump())
    db.add(new_lib)
    db.commit()
    db.refresh(new_lib)
    return new_lib


@router.put("/{key}", response_model=LibResponse, dependencies=[Depends(require_admin)])
def update_lib(key: str, lib_update: LibUpdate, db: Session = Depends(get_db)):
    db_lib = db.query(Lib).filter(Lib.key == key).first()
    if not db_lib:
        raise HTTPException(status_code=404, detail="Lib not found")

    update_data = lib_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_lib, field, value)

    db.commit()
    db.refresh(db_lib)
    return db_lib


@router.delete(
    "/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def delete_lib(key: str, db: Session = Depends(get_db)):
    db_lib = db.query(Lib).filter(Lib.key == key).first()
    if not db_lib:
        raise HTTPException(status_code=404, detail="Lib not found")
    db.delete(db_lib)
    db.commit()
    return None
