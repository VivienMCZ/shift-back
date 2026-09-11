from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from app.api.geo import CODE_POSTAL_PATTERN

# Schéma pour les données d'une aide individuelle dans la réponse
class AideSchema(BaseModel):
    id: int
    categorie: str
    nom: str
    description: str
    url_demande: Optional[str] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    region: Optional[str] = None
    departement: Optional[str] = None
    commune: Optional[str] = None
    statut_requis: Optional[List[str]] = None
    handicap_requis: bool
    boursier_requis: bool
    inscrit_france_travail_requis: bool
    rsa_requis: bool
    formation_qualifiante_requise: bool
    montant: Optional[float] = None

    class Config:
        from_attributes = True # Permet de mapper les objets SQLAlchemy directement

# Schéma pour le profil utilisateur en entrée de l'API
class UserProfileSchema(BaseModel):
    age: int = Field(..., gt=0, description="Âge de l'utilisateur")
    statut: str = Field(..., max_length=50, description="Statut de l'utilisateur (e.g., 'salarie', 'etudiant')")
    code_postal: Optional[str] = Field(
        None,
        pattern=CODE_POSTAL_PATTERN,
        description="Code postal de résidence. Sert à déduire région et département s'ils ne sont pas fournis.",
    )
    region: Optional[str] = Field(None, max_length=100, description="Région de résidence")
    departement: Optional[str] = Field(None, max_length=3, description="Code du département de résidence (ex. '75', '2A', '971')")
    commune: Optional[str] = Field(None, max_length=100, description="Commune de résidence")
    has_rqth: bool = Field(False, description="L'utilisateur a-t-il une RQTH ?")
    is_boursier: bool = Field(False, description="L'utilisateur est-il boursier ?")
    inscrit_france_travail: bool = Field(False, description="L'utilisateur est-il inscrit à France Travail ?")
    beneficiaire_rsa: bool = Field(False, description="L'utilisateur est-il bénéficiaire du RSA ?")
    en_formation_qualifiante: bool = Field(False, description="L'utilisateur est-il en formation qualifiante ?")
    reserviste: bool = Field(False, description="L'utilisateur est-il réserviste militaire ?")
    secteur_btp: bool = Field(False, description="L'utilisateur travaille-t-il dans le BTP ?")
    secteur_hcr: bool = Field(False, description="L'utilisateur travaille-t-il dans l'hôtellerie-restauration ?")

# Schéma pour le résultat du calcul des aides
class CalculationResultSchema(BaseModel):
    aides: List[AideSchema]
    # Aides non remboursables uniquement.
    total_potentiel: float
    # Prêts (catégorie « Prêt ») : présentés à part, ils se remboursent.
    total_prets: float = 0.0

# Schéma d'une recherche sauvegardée (renvoyée dans l'historique du profil)
class AideSaveResponse(BaseModel):
    id: int
    profile: dict
    aides: List[AideSchema]
    total_potentiel: float
    created_at: datetime

    class Config:
        from_attributes = True