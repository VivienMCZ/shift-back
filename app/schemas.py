"""Schémas d'entrée/sortie de l'API.

**A03 — Injection** et **A04 — Insecure Design** : toute donnée entrante est
bornée en longueur et en format. Sans ces contraintes, un client peut envoyer
des chaînes arbitrairement longues (charge inutile en base et en mémoire) ou des
adresses e-mail qui n'en sont pas.
"""

from typing import Any, List, Optional

from pydantic import BaseModel, Field

# Validation pragmatique : présence d'un « @ », d'un domaine et d'une extension.
# Volontairement plus permissif que la RFC 5322, dont l'implémentation complète
# rejette des adresses réelles.
EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$"
# E.164 ou format national, avec séparateurs usuels.
PHONE_PATTERN = r"^\+?[0-9][0-9 .\-]{6,19}$"
POSTAL_CODE_PATTERN = r"^[0-9A-Za-z][0-9A-Za-z \-]{2,9}$"


class TagSchema(BaseModel):
    label: str = Field(max_length=100)
    color: str = Field(default="blue", max_length=32)


class AutoEcoleResponse(BaseModel):
    id: int
    name: str
    city: str
    postal_code: Optional[str] = None
    address: Optional[str] = None
    lat: float
    lng: float
    rating: float
    price: Optional[int] = None
    price_label: Optional[str] = None
    speed_level: Optional[str] = None
    speed_label: Optional[str] = None
    permis_type: Optional[str] = None
    tags: List[Any] = Field(default_factory=list)
    image_url: Optional[str] = None
    distance: Optional[float] = None
    match_score: Optional[int] = None
    match_label: Optional[str] = None
    match_reasons: List[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class FavoriteCreate(BaseModel):
    auto_ecole_id: int = Field(gt=0)


class AuthRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)
    phone: Optional[str] = Field(default=None, max_length=20, pattern=PHONE_PATTERN)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class VerifyOTPRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)
    otp_code: str = Field(min_length=4, max_length=10, pattern=r"^[0-9]+$")


class UserResponse(BaseModel):
    """Représentation publique d'un utilisateur.

    N'expose ni ``otp_code`` ni ``otp_expires_at`` : ce sont des secrets
    d'authentification (A02).
    """

    id: int
    email: str
    phone: Optional[str] = None
    first_name: str
    last_name: str
    age: Optional[int] = None
    statut: Optional[str] = None
    postal_code: Optional[str] = None

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    """Champs modifiables du profil (RGPD, droit de rectification).

    ``None`` laisse un champ inchangé. L'e-mail n'y figure pas : il sert
    d'identifiant de connexion, le changer exigerait de vérifier la nouvelle
    adresse.
    """

    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    # Chaîne vide acceptée : c'est la seule façon de retirer un numéro, ``None``
    # signifiant « inchangé ».
    phone: Optional[str] = Field(default=None, max_length=20, pattern=rf"^$|{PHONE_PATTERN}")
    age: Optional[int] = Field(default=None, ge=14, le=120)
    statut: Optional[str] = Field(default=None, max_length=50)
    postal_code: Optional[str] = Field(
        default=None, max_length=10, pattern=POSTAL_CODE_PATTERN
    )


class LibBase(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    fr: str = Field(min_length=1, max_length=2000)
    en: str = Field(min_length=1, max_length=2000)


class LibCreate(LibBase):
    pass


class LibUpdate(BaseModel):
    fr: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    en: Optional[str] = Field(default=None, min_length=1, max_length=2000)


class LibResponse(LibBase):
    id: int

    model_config = {"from_attributes": True}
