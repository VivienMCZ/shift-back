from dataclasses import dataclass
from typing import Optional

@dataclass
class UserProfile:
    """
    Représente le profil d'un utilisateur pour calculer les aides au permis.
    """
    age: int
    statut: str  # e.g., "salarie", "apprenti", "etudiant", "lyceen", "demandeur_emploi", "jeune_insertion", "interimaire", "autre"
    code_postal: Optional[str] = None
    region: Optional[str] = None
    departement: Optional[str] = None  # code : "75", "2A", "971"…
    commune: Optional[str] = None
    has_rqth: bool = False
    is_boursier: bool = False
    inscrit_france_travail: bool = False
    beneficiaire_rsa: bool = False
    en_formation_qualifiante: bool = False
    # Situations qui se cumulent avec le statut principal : on est réserviste
    # *et* étudiant, salarié *du BTP*. Le calculateur les traduit en statuts
    # complémentaires (voir ``CalculateurAides.statuts``).
    reserviste: bool = False
    secteur_btp: bool = False
    secteur_hcr: bool = False
