"""Tests des durcissements OWASP.

Chaque test référence la catégorie du Top 10 qu'il protège, afin qu'une
régression soit immédiatement rattachable au risque concerné.
"""

import os

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import User
from app.routers import auth as auth_module
from app.security import (
    RateLimiter,
    client_ip,
    generate_otp,
    hash_otp,
    verify_otp,
)

TEST_JWT_SECRET = os.environ["JWT_SECRET"]


# --------------------------------------------------------------------------- #
# A02 — Cryptographic Failures : génération et stockage des OTP
# --------------------------------------------------------------------------- #


def test_otp_a_six_chiffres():
    for _ in range(50):
        code = generate_otp()
        assert len(code) == 6
        assert code.isdigit()


def test_otp_conserve_les_zeros_de_tete():
    """``str(secrets.randbelow(...))`` seul produirait des codes trop courts."""
    codes = {generate_otp() for _ in range(500)}
    assert all(len(code) == 6 for code in codes)


def test_otp_nest_pas_previsible():
    """Un générateur figé produirait des collisions massives."""
    codes = [generate_otp() for _ in range(200)]
    assert len(set(codes)) > 150


def test_empreinte_otp_est_stable_et_non_reversible():
    empreinte = hash_otp("123456", TEST_JWT_SECRET)
    assert empreinte == hash_otp("123456", TEST_JWT_SECRET)
    assert "123456" not in empreinte
    assert len(empreinte) == 64


def test_empreinte_otp_depend_du_secret_serveur():
    """Une fuite de la base seule ne permet pas de recalculer les empreintes."""
    assert hash_otp("123456", "secret-a") != hash_otp("123456", "secret-b")


@pytest.mark.parametrize("code", ["123456", "000000", "999999"])
def test_verification_otp_accepte_le_bon_code(code):
    assert verify_otp(code, hash_otp(code, TEST_JWT_SECRET), TEST_JWT_SECRET)


def test_verification_otp_refuse_un_mauvais_code():
    empreinte = hash_otp("123456", TEST_JWT_SECRET)
    assert not verify_otp("654321", empreinte, TEST_JWT_SECRET)


def test_verification_otp_refuse_une_empreinte_absente():
    assert not verify_otp("123456", None, TEST_JWT_SECRET)
    assert not verify_otp("123456", "", TEST_JWT_SECRET)


def test_lotp_nest_jamais_stocke_en_clair(client, make_user, db, otp_fixe):
    """A02 — la base ne doit contenir que l'empreinte."""
    make_user(email="ok@example.com")
    client.post("/auth/request-otp", json={"email": "ok@example.com"})

    with db() as session:
        user = session.query(User).filter(User.email == "ok@example.com").one()
        assert user.otp_code != otp_fixe
        assert user.otp_code == hash_otp(otp_fixe, TEST_JWT_SECRET)


def test_secret_jwt_trop_court_est_refuse(monkeypatch):
    """A02 — HS256 exige au moins 32 octets de clé (RFC 7518)."""
    import importlib

    secret_initial = os.environ["JWT_SECRET"]
    try:
        monkeypatch.setenv("JWT_SECRET", "trop-court")
        with pytest.raises(RuntimeError, match="at least 32"):
            importlib.reload(auth_module)
    finally:
        os.environ["JWT_SECRET"] = secret_initial
        importlib.reload(auth_module)


# --------------------------------------------------------------------------- #
# A04 / A07 — Limitation de débit
# --------------------------------------------------------------------------- #


def test_rate_limiter_autorise_sous_le_quota():
    limiteur = RateLimiter(max_attempts=3, window_seconds=60)
    assert limiteur.hit("cle") is False
    assert limiteur.hit("cle") is False
    assert limiteur.hit("cle") is False
    assert limiteur.is_blocked("cle") is True


def test_rate_limiter_signale_le_depassement():
    limiteur = RateLimiter(max_attempts=2, window_seconds=60)
    limiteur.hit("cle")
    limiteur.hit("cle")
    assert limiteur.hit("cle") is True


def test_rate_limiter_cloisonne_les_cles():
    limiteur = RateLimiter(max_attempts=1, window_seconds=60)
    limiteur.hit("a")
    assert limiteur.is_blocked("a") is True
    assert limiteur.is_blocked("b") is False


def test_rate_limiter_oublie_les_tentatives_anciennes():
    limiteur = RateLimiter(max_attempts=2, window_seconds=0.05)
    limiteur.hit("cle")
    limiteur.hit("cle")
    assert limiteur.is_blocked("cle") is True

    import time

    time.sleep(0.08)
    assert limiteur.is_blocked("cle") is False


def test_rate_limiter_reset():
    limiteur = RateLimiter(max_attempts=1, window_seconds=60)
    limiteur.hit("cle")
    limiteur.reset("cle")
    assert limiteur.is_blocked("cle") is False


def test_brute_force_otp_est_bloque(client, make_user, otp_fixe):
    """A07 — un code à six chiffres se force sans plafonnement des essais."""
    make_user(email="cible@example.com")
    client.post("/auth/request-otp", json={"email": "cible@example.com"})

    for _ in range(auth_module.OTP_MAX_ATTEMPTS):
        reponse = client.post(
            "/auth/verify-otp",
            json={"email": "cible@example.com", "otp_code": "000000"},
        )
        assert reponse.status_code == 400

    bloque = client.post(
        "/auth/verify-otp", json={"email": "cible@example.com", "otp_code": "000000"}
    )
    assert bloque.status_code == 429

    # Même le bon code est refusé tant que le blocage est actif.
    avec_bon_code = client.post(
        "/auth/verify-otp", json={"email": "cible@example.com", "otp_code": otp_fixe}
    )
    assert avec_bon_code.status_code == 429


def test_un_nouveau_code_leve_le_blocage(client, make_user, otp_fixe):
    make_user(email="cible@example.com")
    client.post("/auth/request-otp", json={"email": "cible@example.com"})
    for _ in range(auth_module.OTP_MAX_ATTEMPTS + 1):
        client.post(
            "/auth/verify-otp",
            json={"email": "cible@example.com", "otp_code": "000000"},
        )

    client.post("/auth/request-otp", json={"email": "cible@example.com"})
    reponse = client.post(
        "/auth/verify-otp", json={"email": "cible@example.com", "otp_code": otp_fixe}
    )
    assert reponse.status_code == 200


def test_blocage_dun_compte_nimpacte_pas_les_autres(client, make_user, otp_fixe):
    make_user(email="a@example.com")
    make_user(email="b@example.com")
    client.post("/auth/request-otp", json={"email": "a@example.com"})
    client.post("/auth/request-otp", json={"email": "b@example.com"})

    for _ in range(auth_module.OTP_MAX_ATTEMPTS + 1):
        client.post(
            "/auth/verify-otp", json={"email": "a@example.com", "otp_code": "000000"}
        )

    reponse = client.post(
        "/auth/verify-otp", json={"email": "b@example.com", "otp_code": otp_fixe}
    )
    assert reponse.status_code == 200


def test_demandes_de_code_plafonnees_par_ip(client, make_user):
    """A04 — sans plafond, l'endpoint sert de relais d'envoi massif."""
    make_user(email="cible@example.com")

    for _ in range(auth_module.OTP_REQUEST_MAX):
        reponse = client.post(
            "/auth/request-otp", json={"email": "cible@example.com"}
        )
        assert reponse.status_code == 200

    bloque = client.post("/auth/request-otp", json={"email": "cible@example.com"})
    assert bloque.status_code == 429


def test_inscriptions_plafonnees_par_ip(client):
    for index in range(auth_module.OTP_REQUEST_MAX):
        reponse = client.post(
            "/auth/register",
            json={
                "email": f"user{index}@example.com",
                "first_name": "A",
                "last_name": "B",
            },
        )
        assert reponse.status_code == 200

    bloque = client.post(
        "/auth/register",
        json={"email": "dernier@example.com", "first_name": "A", "last_name": "B"},
    )
    assert bloque.status_code == 429


def test_client_ip_utilise_x_forwarded_for():
    class FakeRequest:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = None

    assert client_ip(FakeRequest()) == "203.0.113.7"


def test_client_ip_retombe_sur_ladresse_directe():
    class FakeClient:
        host = "198.51.100.4"

    class FakeRequest:
        headers = {}
        client = FakeClient()

    assert client_ip(FakeRequest()) == "198.51.100.4"


def test_client_ip_sans_information():
    class FakeRequest:
        headers = {}
        client = None

    assert client_ip(FakeRequest()) == "inconnu"


# --------------------------------------------------------------------------- #
# A03 / A04 — Validation des entrées
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "email",
    [
        "pas-un-email",
        "sans-arobase.fr",
        "@example.com",
        "a@b",
        "a@@b.fr",
        "avec espace@example.com",
        "a" * 300 + "@example.com",
    ],
)
def test_email_invalide_est_rejete(client, email):
    for chemin, charge in (
        ("/auth/request-otp", {"email": email}),
        ("/auth/register", {"email": email, "first_name": "A", "last_name": "B"}),
        ("/auth/verify-otp", {"email": email, "otp_code": "123456"}),
    ):
        assert client.post(chemin, json=charge).status_code == 422, (chemin, email)


@pytest.mark.parametrize("email", ["a@b.fr", "prenom.nom@sous.domaine.example.com"])
def test_email_valide_est_accepte(client, email):
    reponse = client.post(
        "/auth/register", json={"email": email, "first_name": "A", "last_name": "B"}
    )
    assert reponse.status_code == 200


@pytest.mark.parametrize("code", ["abc123", "12", "1" * 20, "", "12345a"])
def test_code_otp_mal_forme_est_rejete(client, make_user, code):
    make_user(email="ok@example.com")
    reponse = client.post(
        "/auth/verify-otp", json={"email": "ok@example.com", "otp_code": code}
    )
    assert reponse.status_code == 422


def test_nom_trop_long_est_rejete(client):
    reponse = client.post(
        "/auth/register",
        json={
            "email": "long@example.com",
            "first_name": "A" * 500,
            "last_name": "B",
        },
    )
    assert reponse.status_code == 422


def test_telephone_mal_forme_est_rejete(client):
    reponse = client.post(
        "/auth/register",
        json={
            "email": "tel@example.com",
            "phone": "pas-un-numero",
            "first_name": "A",
            "last_name": "B",
        },
    )
    assert reponse.status_code == 422


def test_libelle_trop_long_est_rejete(client, admin_headers):
    reponse = client.post(
        f"/api/v1/libs/",
        json={"key": "k", "fr": "A" * 5000, "en": "B"},
        headers=admin_headers,
    )
    assert reponse.status_code == 422


@pytest.mark.parametrize("age", [10, 200, -1])
def test_age_hors_bornes_est_rejete(client, login, age):
    login()
    assert client.put("/auth/me", json={"age": age}).status_code == 422


def test_identifiant_favori_doit_etre_positif(client, login):
    login()
    assert client.post(
        "/api/ecoles/favorites", json={"auto_ecole_id": 0}
    ).status_code == 422


# --------------------------------------------------------------------------- #
# A05 — Security Misconfiguration : en-têtes de réponse
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "entete,valeur",
    [
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "strict-origin-when-cross-origin"),
        ("cross-origin-opener-policy", "same-origin"),
    ],
)
def test_entetes_de_securite_presents(client, entete, valeur):
    response = client.get("/health")
    assert response.headers[entete] == valeur


def test_csp_interdit_tout_chargement_externe(client):
    response = client.get("/health")
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_hsts_absent_en_http(client):
    """HSTS sur une origine non chiffrée n'a pas de sens et bloque le dev local."""
    assert "strict-transport-security" not in client.get("/health").headers


@pytest.fixture
def client_qui_plante():
    """Client exposant une route qui lève, sans faire remonter l'erreur au test.

    La réponse 500 est fabriquée par ``ServerErrorMiddleware``, monté au-dessus
    des middlewares applicatifs : c'est le seul chemin de réponse qui ne
    traverse pas ``SecurityHeadersMiddleware``.
    """
    chemin = "/_erreur_de_test"

    @app.get(chemin)
    def _erreur():
        raise RuntimeError("panne simulée")

    try:
        yield TestClient(app, raise_server_exceptions=False), chemin
    finally:
        app.router.routes = [
            route for route in app.router.routes
            if getattr(route, "path", None) != chemin
        ]


@pytest.mark.parametrize(
    "entete",
    [
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "cross-origin-opener-policy",
        "permissions-policy",
        "content-security-policy",
    ],
)
def test_entetes_de_securite_presents_sur_une_500(client_qui_plante, entete):
    """A05 — une panne serveur ne doit pas renvoyer une réponse non durcie."""
    test_client, chemin = client_qui_plante
    reponse = test_client.get(chemin)
    assert reponse.status_code == 500
    assert entete in reponse.headers


def test_la_500_garde_le_corps_generique_de_starlette(client_qui_plante):
    """Le durcissement ne doit pas transformer la réponse ni divulguer la cause."""
    test_client, chemin = client_qui_plante
    reponse = test_client.get(chemin)
    assert reponse.text == "Internal Server Error"
    assert reponse.headers["content-type"] == "text/plain; charset=utf-8"
    assert "panne simulée" not in reponse.text


# --------------------------------------------------------------------------- #
# A07 / A09 — Session et journalisation
# --------------------------------------------------------------------------- #


def test_cookie_de_session_est_httponly(client, login):
    login()
    reponse = client.post(
        "/auth/verify-otp", json={"email": "test@example.com", "otp_code": "123456"}
    )
    entete = reponse.headers.get("set-cookie", "")
    if entete:
        assert "HttpOnly" in entete
        assert "SameSite=lax" in entete


def test_jeton_de_session_porte_une_date_demission(client, make_user, otp_fixe):
    make_user(email="ok@example.com")
    client.post("/auth/request-otp", json={"email": "ok@example.com"})
    reponse = client.post(
        "/auth/verify-otp", json={"email": "ok@example.com", "otp_code": otp_fixe}
    )
    charge = jwt.decode(
        reponse.cookies["access_token"], TEST_JWT_SECRET, algorithms=["HS256"]
    )
    assert "iat" in charge
    assert "exp" in charge


def test_sujet_non_numerique_est_rejete(client):
    """Un ``sub`` arbitraire ne doit pas provoquer d'erreur serveur."""
    from datetime import timedelta

    from app.routers.auth import utcnow

    token = jwt.encode(
        {"sub": "1 OR 1=1", "exp": utcnow() + timedelta(days=1)},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    client.cookies.set("access_token", token)
    reponse = client.get("/auth/me")
    assert reponse.status_code == 401


def test_aucun_jeton_ni_cookie_dans_les_journaux(client, make_user, caplog):
    """A09 — les journaux ne doivent jamais contenir de secret de session."""
    make_user(email="ok@example.com")
    client.cookies.set("access_token", "jeton-tres-secret-a-ne-pas-journaliser")

    with caplog.at_level("DEBUG"):
        client.get("/auth/me")

    assert "jeton-tres-secret-a-ne-pas-journaliser" not in caplog.text


def test_le_code_otp_napparait_pas_dans_les_journaux(client, make_user, caplog, otp_fixe):
    make_user(email="ok@example.com")
    with caplog.at_level("DEBUG"):
        client.post("/auth/request-otp", json={"email": "ok@example.com"})
    assert otp_fixe not in caplog.text


def test_reponse_derreur_ne_revele_pas_la_cause_exacte(client):
    """Distinguer « expiré » de « mal signé » aide un attaquant."""
    client.cookies.set("access_token", "pas-un-jwt")
    detail = client.get("/auth/me").json()["detail"]
    assert "signature" not in detail.lower()
    assert "expired" not in detail.lower()


def test_hsts_present_quand_le_cookie_est_securise(client, monkeypatch):
    """A05 — HSTS n'est émis que sur un déploiement HTTPS."""
    monkeypatch.setenv("COOKIE_SECURE", "true")
    response = client.get("/health")
    assert response.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )


def test_samesite_invalide_retombe_sur_lax(monkeypatch):
    """Une valeur SameSite inconnue est refusée par le navigateur : on borne."""
    import importlib

    secret_initial = os.environ["JWT_SECRET"]
    try:
        monkeypatch.setenv("COOKIE_SAMESITE", "n-importe-quoi")
        importlib.reload(auth_module)
        assert auth_module.COOKIE_SAMESITE == "lax"
    finally:
        monkeypatch.delenv("COOKIE_SAMESITE", raising=False)
        os.environ["JWT_SECRET"] = secret_initial
        importlib.reload(auth_module)


def test_affichage_du_code_otp_desactive_par_defaut(capsys, monkeypatch):
    """A09 — le code ne doit sortir en console que sur activation explicite."""
    monkeypatch.setenv("OTP_DEBUG_DELIVERY", "false")
    auth_module.deliver_otp("ok@example.com", "123456")
    assert "123456" not in capsys.readouterr().out


def test_affichage_du_code_otp_sur_activation_explicite(capsys, monkeypatch):
    monkeypatch.setenv("OTP_DEBUG_DELIVERY", "true")
    auth_module.deliver_otp("ok@example.com", "123456")
    assert "123456" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# A01 — Broken Access Control : portée des en-têtes de cache HTTP
#
# ``/api/ecoles`` et ``/api/ecoles/favorites`` partagent le même préfixe de
# routeur. Le premier est public et gagne à être mis en cache ; le second dépend
# de l'utilisateur connecté. Poser l'en-tête au niveau du routeur, ou par un
# middleware sur le préfixe, permettrait à un cache partagé (CDN, proxy) de
# servir les favoris d'un compte à un autre. Ces tests verrouillent la
# séparation.
# --------------------------------------------------------------------------- #


def test_liste_des_ecoles_cachable_publiquement(client, make_ecole):
    make_ecole(name="Auto-école du Centre")

    response = client.get("/api/ecoles")

    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("public")


def test_fiche_d_ecole_cachable_publiquement(client, make_ecole):
    ecole_id = make_ecole(name="Auto-école du Centre")

    response = client.get(f"/api/ecoles/{ecole_id}")

    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("public")


def test_favoris_jamais_mis_en_cache(client, login, make_ecole):
    """Le cœur du risque : une réponse propre à un compte, jamais partagée."""
    login()
    make_ecole(name="Auto-école du Centre")

    response = client.get("/api/ecoles/favorites")

    assert response.status_code == 200
    cache_control = response.headers["cache-control"]
    assert "no-store" in cache_control
    assert "public" not in cache_control


def test_favoris_non_authentifies_ne_sont_pas_cachables(client):
    """Un 401 ne doit pas davantage être mémorisé par un cache partagé."""
    response = client.get("/api/ecoles/favorites")

    assert response.status_code == 401
    assert "public" not in response.headers.get("cache-control", "")


@pytest.mark.parametrize("route", ["/api/v1/aides/saves", "/auth/me/export"])
def test_donnees_personnelles_jamais_mises_en_cache(client, login, route):
    login()
    response = client.get(route)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"


# --------------------------------------------------------------------------- #
# A01 — Broken Access Control : droits RGPD cloisonnés par compte
#
# Export et effacement agissent sur l'utilisateur de la session, jamais sur un
# identifiant fourni par le client.
# --------------------------------------------------------------------------- #


def test_effacer_la_recherche_dun_autre_compte_repond_404(client, login, make_aide, db):
    """404 et non 403 : un 403 confirmerait l'existence de la recherche."""
    from app.api.models.aide import AideSave

    make_aide(montant=1200.0)
    login(email="alice@example.com")
    client.post("/api/v1/aides/calculate", json={"age": 20, "statut": "etudiant"})
    save_id = client.get("/api/v1/aides/saves").json()[0]["id"]

    client.cookies.clear()
    login(email="bob@example.com")
    assert client.delete(f"/api/v1/aides/saves/{save_id}").status_code == 404
    with db() as session:
        assert session.query(AideSave).count() == 1


def test_export_ne_contient_que_les_donnees_du_compte(client, login, make_ecole):
    ecole_id = make_ecole()
    login(email="alice@example.com")
    client.post("/api/ecoles/favorites", json={"auto_ecole_id": ecole_id})

    client.cookies.clear()
    login(email="bob@example.com")
    corps = client.get("/auth/me/export").json()
    assert corps["compte"]["email"] == "bob@example.com"
    assert corps["favoris"] == []


def test_suppression_de_compte_ne_touche_pas_aux_autres(client, login, make_ecole, db):
    from app.models import Favorite

    ecole_id = make_ecole()
    login(email="alice@example.com")
    client.post("/api/ecoles/favorites", json={"auto_ecole_id": ecole_id})

    client.cookies.clear()
    login(email="bob@example.com")
    assert client.delete("/auth/me").status_code == 204

    with db() as session:
        assert session.query(User.email).all() == [("alice@example.com",)]
        assert session.query(Favorite).count() == 1


# --------------------------------------------------------------------------- #
# RGPD article 9 — données de santé
# --------------------------------------------------------------------------- #


def test_une_recherche_declarant_une_rqth_nest_pas_conservee(client, login, make_aide, db):
    """La RQTH est une donnée de santé : la conserver exigerait un consentement
    explicite. Le résultat est rendu, rien n'est écrit — pas même le reste de la
    recherche, dont les aides obtenues trahiraient le handicap."""
    from app.api.models.aide import AideSave

    login()
    make_aide(nom="AGEFIPH", handicap_requis=True, montant=1300.0)

    response = client.post(
        "/api/v1/aides/calculate",
        json={"age": 20, "statut": "etudiant", "has_rqth": True},
    )

    assert [a["nom"] for a in response.json()["aides"]] == ["AGEFIPH"]
    with db() as session:
        assert session.query(AideSave).count() == 0
