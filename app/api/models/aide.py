from typing import List, Optional
from sqlalchemy import Column, Integer, String, Date, JSON, Boolean, Float, DateTime, ForeignKey, func
from app.database import Base

class AideDB(Base):
    __tablename__ = 'aides'
    id = Column(Integer, primary_key=True, index=True)
    categorie = Column(String, index=True) # Nationale, Sectorielle, etc.
    nom = Column(String, index=True)
    description = Column(String)
    url_demande = Column(String, nullable=True)
    age_min = Column(Integer, nullable=True)
    age_max = Column(Integer, nullable=True)
    region = Column(String, nullable=True)
    departement = Column(String, nullable=True)
    commune = Column(String, nullable=True)
    statut_requis = Column(JSON, nullable=True) # List of statuses
    handicap_requis = Column(Boolean, default=False)
    boursier_requis = Column(Boolean, default=False)
    inscrit_france_travail_requis = Column(Boolean, default=False)
    rsa_requis = Column(Boolean, default=False)
    formation_qualifiante_requise = Column(Boolean, default=False)
    montant = Column(Float, nullable=True)


class AideSave(Base):
    """Sauvegarde d'une recherche du calculateur d'aides pour un utilisateur connecté.

    Conserve ce qui a été saisi (``profile``) et ce qui a été calculé par le
    script (``aides`` détaillées + ``total_potentiel``) afin de pouvoir les
    réafficher dans le profil ("Historique des recherches").
    """

    __tablename__ = 'aide_saves'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True, nullable=False)
    profile = Column(JSON, nullable=False)          # la saisie (UserProfileSchema)
    aides = Column(JSON, default=list)              # les aides calculées (détail figé)
    total_potentiel = Column(Float, default=0.0)    # montant total calculé
    created_at = Column(DateTime, server_default=func.now())
