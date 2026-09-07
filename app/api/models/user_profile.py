from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class UserProfile:
    """
    Représente le profil d'un utilisateur pour calculer les aides au permis.
    """
    age: int
    statut: str  # e.g., "salarie", "apprenti", "etudiant", "demandeur_emploi", "jeune_insertion", "interimaire", "salarie_hcr", "salarie_btp", "reserve_militaire", "snu", "autre"
    region: Optional[str] = None
    departement: Optional[str] = None
    commune: Optional[str] = None
    has_rqth: bool = False
    is_boursier: bool = False
    inscrit_france_travail: bool = False
    beneficiaire_rsa: bool = False
    en_formation_qualifiante: bool = False
