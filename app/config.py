"""Lecture et validation de la configuration issue de l'environnement.

Centralisé ici pour éviter que chaque module réinvente son propre parsing et
pour que les valeurs sensibles ne soient jamais journalisées telles quelles.
"""

import logging
import os
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

TRUTHY = {"1", "true", "yes", "on", "oui"}
FALSY = {"0", "false", "no", "off", "non"}


def get_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("%s invalide (%s), valeur par défaut utilisée: %s", name, raw_value, default)
        return default

    if value < 1:
        logger.warning("%s doit être supérieur ou égal à 1, valeur par défaut utilisée: %s", name, default)
        return default

    return value


def get_env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError:
        logger.warning("%s invalide (%s), valeur par défaut utilisée: %s", name, raw_value, default)
        return default

    if value < 0:
        logger.warning("%s doit être positif, valeur par défaut utilisée: %s", name, default)
        return default

    return value


def get_env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in TRUTHY:
        return True
    if normalized in FALSY:
        return False

    logger.warning("%s invalide (%s), valeur par défaut utilisée: %s", name, raw_value, default)
    return default


def get_env_list(name: str, default: list[str]) -> list[str]:
    """Liste séparée par des virgules. Une valeur vide renvoie une liste vide."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return list(default)
    return [element.strip() for element in raw_value.split(",") if element.strip()]


def mask_database_url(database_url: str) -> tuple[str, str]:
    """Retourne (URL sans mot de passe, hôte) — sûr à journaliser."""
    parsed_url = urlsplit(database_url)
    host = parsed_url.hostname or "inconnu"
    port = f":{parsed_url.port}" if parsed_url.port else ""
    auth = f"{parsed_url.username}:***@" if parsed_url.username else ""
    netloc = f"{auth}{host}{port}"
    masked_url = urlunsplit(
        (
            parsed_url.scheme,
            netloc,
            parsed_url.path,
            parsed_url.query,
            parsed_url.fragment,
        )
    )
    return masked_url, host
