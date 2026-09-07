"""Primitives de sécurité : génération/vérification d'OTP et limitation de débit.

Couvre les points OWASP suivants :

* **A02 — Cryptographic Failures** : les codes OTP sont tirés d'un générateur
  cryptographique (``secrets``) et ne sont jamais stockés en clair. La base ne
  contient qu'un HMAC-SHA256 calculé avec une clé serveur ; une fuite de la base
  ne suffit donc pas à rejouer un code.
* **A04 — Insecure Design** / **A07 — Authentication Failures** : un code à six
  chiffres se force en quelques dizaines de milliers de requêtes. Le nombre
  d'essais par compte et la cadence par adresse IP sont donc plafonnés.

Limite connue : les compteurs vivent en mémoire du processus. Cela suffit pour
un déploiement mono-conteneur ; derrière plusieurs workers ou plusieurs
instances, il faut un stockage partagé (Redis) — voir README.
"""

import hmac
import secrets
import threading
import time
from hashlib import sha256

OTP_LENGTH = 6


# --------------------------------------------------------------------------- #
# OTP
# --------------------------------------------------------------------------- #


def generate_otp(length: int = OTP_LENGTH) -> str:
    """Code numérique tiré d'un générateur cryptographiquement sûr.

    ``random.randint`` (Mersenne Twister) est prédictible : l'observation de
    quelques codes permet de reconstituer l'état interne du générateur.
    """
    upper_bound = 10**length
    return str(secrets.randbelow(upper_bound)).zfill(length)


def hash_otp(otp_code: str, secret: str) -> str:
    """HMAC-SHA256 du code, à stocker à la place du code lui-même."""
    return hmac.new(secret.encode("utf-8"), otp_code.encode("utf-8"), sha256).hexdigest()


def verify_otp(otp_code: str, stored_hash: str | None, secret: str) -> bool:
    """Comparaison à temps constant entre un code saisi et l'empreinte stockée."""
    if not stored_hash:
        return False
    return hmac.compare_digest(hash_otp(otp_code, secret), stored_hash)


# --------------------------------------------------------------------------- #
# Limitation de débit
# --------------------------------------------------------------------------- #


class RateLimiter:
    """Compteur glissant en mémoire, protégé par un verrou.

    ``hit`` enregistre une tentative et indique si le quota est dépassé.
    ``reset`` efface le compteur d'une clé (après une authentification réussie).
    """

    def __init__(self, max_attempts: int, window_seconds: float):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _purge(self, key: str, now: float) -> list[float]:
        recent = [
            moment
            for moment in self._attempts.get(key, [])
            if now - moment < self.window_seconds
        ]
        if recent:
            self._attempts[key] = recent
        else:
            self._attempts.pop(key, None)
        return recent

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._purge(key, time.monotonic())) >= self.max_attempts

    def hit(self, key: str) -> bool:
        """Enregistre une tentative. Retourne ``True`` si le quota est dépassé."""
        with self._lock:
            now = time.monotonic()
            recent = self._purge(key, now)
            recent.append(now)
            self._attempts[key] = recent
            return len(recent) > self.max_attempts

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()


def client_ip(request) -> str:
    """Adresse de l'appelant, en tenant compte d'un éventuel reverse proxy.

    ``X-Forwarded-For`` est falsifiable si l'application est exposée
    directement : la valeur ne sert qu'au comptage, jamais à une décision
    d'autorisation.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "inconnu"
