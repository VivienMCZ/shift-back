"""Tests d'intégration du routeur ``/auth`` (inscription, OTP, session)."""

import os
from datetime import timedelta

import jwt
import pytest

from app.models import User
from app.routers.auth import utcnow
from app.security import hash_otp

TEST_JWT_SECRET = os.environ["JWT_SECRET"]


def empreinte_otp(db, email):
    """Relit l'empreinte OTP stockée (le code en clair n'est jamais persisté)."""
    with db() as session:
        user = session.query(User).filter(User.email == email).one()
        return user.otp_code


# --------------------------------------------------------------------------- #
# Inscription
# --------------------------------------------------------------------------- #


def test_inscription_cree_lutilisateur(client, db):
    response = client.post(
        "/auth/register",
        json={
            "email": "nouveau@example.com",
            "phone": "0600000000",
            "first_name": "Marie",
            "last_name": "Curie",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"message": "User created and OTP sent"}

    with db() as session:
        user = session.query(User).filter(User.email == "nouveau@example.com").one()
        assert user.first_name == "Marie"
        assert user.otp_code is not None
        # Empreinte HMAC-SHA256, jamais le code lui-même.
        assert len(user.otp_code) == 64
        assert user.otp_expires_at > utcnow()


def test_inscription_sans_telephone(client):
    response = client.post(
        "/auth/register",
        json={"email": "sansphone@example.com", "first_name": "A", "last_name": "B"},
    )
    assert response.status_code == 200


def test_inscription_email_deja_utilise(client, make_user):
    make_user(email="deja@example.com")
    response = client.post(
        "/auth/register",
        json={"email": "deja@example.com", "first_name": "A", "last_name": "B"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


def test_inscription_telephone_deja_utilise(client, make_user):
    make_user(email="premier@example.com", phone="0611111111")
    response = client.post(
        "/auth/register",
        json={
            "email": "second@example.com",
            "phone": "0611111111",
            "first_name": "A",
            "last_name": "B",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Phone already registered"


def test_inscription_champs_obligatoires_manquants(client):
    response = client.post("/auth/register", json={"email": "x@example.com"})
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Demande d'OTP
# --------------------------------------------------------------------------- #


def test_demande_otp_pour_un_utilisateur_existant(client, make_user, db):
    make_user(email="connu@example.com")
    response = client.post("/auth/request-otp", json={"email": "connu@example.com"})
    assert response.status_code == 200
    assert empreinte_otp(db, "connu@example.com") is not None


def test_demande_otp_utilisateur_inconnu(client):
    response = client.post("/auth/request-otp", json={"email": "inconnu@example.com"})
    assert response.status_code == 404


def test_demande_otp_regenere_un_code(client, make_user, db):
    make_user(email="connu@example.com")
    client.post("/auth/request-otp", json={"email": "connu@example.com"})
    premier = empreinte_otp(db, "connu@example.com")
    client.post("/auth/request-otp", json={"email": "connu@example.com"})
    second = empreinte_otp(db, "connu@example.com")
    assert premier is not None and second is not None
    assert premier != second


# --------------------------------------------------------------------------- #
# Vérification de l'OTP
# --------------------------------------------------------------------------- #


def test_verification_otp_reussie_pose_le_cookie(client, make_user, otp_fixe):
    make_user(email="ok@example.com", first_name="Ada")
    client.post("/auth/request-otp", json={"email": "ok@example.com"})

    response = client.post(
        "/auth/verify-otp", json={"email": "ok@example.com", "otp_code": otp_fixe}
    )
    assert response.status_code == 200
    assert response.json()["first_name"] == "Ada"
    assert "access_token" in response.cookies

    token = response.cookies["access_token"]
    payload = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])
    assert payload["sub"].isdigit()


def test_verification_otp_efface_le_code(client, make_user, db, otp_fixe):
    make_user(email="ok@example.com")
    client.post("/auth/request-otp", json={"email": "ok@example.com"})
    client.post("/auth/verify-otp", json={"email": "ok@example.com", "otp_code": otp_fixe})

    with db() as session:
        user = session.query(User).filter(User.email == "ok@example.com").one()
        assert user.otp_code is None
        assert user.otp_expires_at is None


def test_verification_otp_code_incorrect(client, make_user):
    make_user(email="ok@example.com")
    client.post("/auth/request-otp", json={"email": "ok@example.com"})
    response = client.post(
        "/auth/verify-otp", json={"email": "ok@example.com", "otp_code": "000000"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired OTP"


def test_verification_otp_expire(client, make_user, db):
    make_user(email="ok@example.com")
    with db() as session:
        user = session.query(User).filter(User.email == "ok@example.com").one()
        user.otp_code = hash_otp("123456", TEST_JWT_SECRET)
        user.otp_expires_at = utcnow() - timedelta(minutes=1)
        session.commit()

    response = client.post(
        "/auth/verify-otp", json={"email": "ok@example.com", "otp_code": "123456"}
    )
    assert response.status_code == 400


def test_verification_otp_sans_code_demande(client, make_user):
    make_user(email="ok@example.com")
    response = client.post(
        "/auth/verify-otp", json={"email": "ok@example.com", "otp_code": "123456"}
    )
    assert response.status_code == 400


def test_verification_otp_utilisateur_inconnu(client):
    response = client.post(
        "/auth/verify-otp", json={"email": "inconnu@example.com", "otp_code": "123456"}
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Session courante
# --------------------------------------------------------------------------- #


def test_me_sans_cookie(client):
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert "no token" in response.json()["detail"]


def test_me_avec_un_token_illisible(client):
    client.cookies.set("access_token", "pas-un-jwt")
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert "decode error" in response.json()["detail"]


def test_me_avec_un_token_signe_par_une_autre_cle(client, make_user):
    user_id = make_user(email="ok@example.com")
    token = jwt.encode(
        {"sub": str(user_id), "exp": utcnow() + timedelta(days=1)},
        "mauvaise-cle",
        algorithm="HS256",
    )
    client.cookies.set("access_token", token)
    assert client.get("/auth/me").status_code == 401


def test_me_avec_un_token_expire(client, make_user):
    user_id = make_user(email="ok@example.com")
    token = jwt.encode(
        {"sub": str(user_id), "exp": utcnow() - timedelta(seconds=1)},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    client.cookies.set("access_token", token)
    assert client.get("/auth/me").status_code == 401


def test_me_avec_un_token_sans_sujet(client):
    token = jwt.encode(
        {"exp": utcnow() + timedelta(days=1)},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    client.cookies.set("access_token", token)
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert "no sub" in response.json()["detail"]


def test_me_pour_un_utilisateur_supprime(client, make_user, db):
    user_id = make_user(email="supprime@example.com")
    token = jwt.encode(
        {"sub": str(user_id), "exp": utcnow() + timedelta(days=1)},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    with db() as session:
        session.query(User).filter(User.id == user_id).delete()
        session.commit()

    client.cookies.set("access_token", token)
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "User not found"


def test_me_retourne_le_profil(client, login):
    login(email="profil@example.com")
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "profil@example.com"


def test_me_nexpose_pas_lotp(client, login):
    login()
    corps = client.get("/auth/me").json()
    assert "otp_code" not in corps
    assert "otp_expires_at" not in corps


# --------------------------------------------------------------------------- #
# Mise à jour du profil
# --------------------------------------------------------------------------- #


def test_mise_a_jour_du_profil(client, login):
    login()
    response = client.put(
        "/auth/me", json={"age": 24, "statut": "etudiant", "postal_code": "31000"}
    )
    assert response.status_code == 200
    corps = response.json()
    assert corps["age"] == 24
    assert corps["statut"] == "etudiant"
    assert corps["postal_code"] == "31000"


def test_mise_a_jour_partielle_preserve_les_autres_champs(client, login):
    login()
    client.put("/auth/me", json={"age": 24, "statut": "etudiant"})
    response = client.put("/auth/me", json={"postal_code": "75001"})
    corps = response.json()
    assert corps["age"] == 24
    assert corps["statut"] == "etudiant"
    assert corps["postal_code"] == "75001"


def test_mise_a_jour_vide_ne_change_rien(client, login):
    login()
    client.put("/auth/me", json={"age": 30})
    response = client.put("/auth/me", json={})
    assert response.json()["age"] == 30


def test_mise_a_jour_exige_une_authentification(client):
    assert client.put("/auth/me", json={"age": 24}).status_code == 401


@pytest.mark.parametrize("charge", [{"age": "vingt"}, {"postal_code": []}])
def test_mise_a_jour_type_invalide(client, login, charge):
    login()
    assert client.put("/auth/me", json=charge).status_code == 422


# --------------------------------------------------------------------------- #
# Déconnexion
# --------------------------------------------------------------------------- #


def test_deconnexion_supprime_le_cookie(client, login):
    login()
    assert client.get("/auth/me").status_code == 200

    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"message": "Logged out successfully"}
    assert client.get("/auth/me").status_code == 401


def test_deconnexion_sans_session_ne_casse_pas(client):
    assert client.post("/auth/logout").status_code == 200
