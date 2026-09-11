"""Tests de la synchronisation du catalogue d'aides (``app.seed.sync_aides``)."""

from app.api.models.aide import AideDB
from app.seed import AIDES, AIDES_RETIREES, sync_aides


def noms_en_base(session):
    return {nom for (nom,) in session.query(AideDB.nom).all()}


def test_base_vide_recoit_tout_le_catalogue(db):
    with db() as session:
        sync_aides(session)
        assert noms_en_base(session) == {a["nom"] for a in AIDES}


def test_synchronisation_idempotente(db):
    with db() as session:
        sync_aides(session)
        sync_aides(session)
        assert session.query(AideDB).count() == len(AIDES)


def test_une_ligne_existante_est_realignee(db, make_aide):
    """Corriger une aide dans le seed doit aussi corriger une base déjà remplie."""
    make_aide(
        nom="Permis à 1 € par jour",
        categorie="Nationale",
        region="Bretagne",
        montant=1.0,
    )
    with db() as session:
        sync_aides(session)
        aide = session.query(AideDB).filter(AideDB.nom == "Permis à 1 € par jour").one()
        assert aide.categorie == "Prêt"
        assert aide.montant == 1200.0
        # Absente de l'entrée du seed : remise à sa valeur par défaut.
        assert aide.region is None


def test_les_aides_retirees_sont_supprimees(db, make_aide):
    make_aide(nom="Aide 500 € pour les apprentis", montant=500.0)
    make_aide(nom="Aide ajoutée à la main", montant=10.0)
    with db() as session:
        sync_aides(session)
        noms = noms_en_base(session)
    assert "Aide 500 € pour les apprentis" not in noms
    # Une aide inconnue du seed, mais pas explicitement retirée, est conservée.
    assert "Aide ajoutée à la main" in noms


def test_aucune_aide_retiree_nest_encore_au_catalogue():
    assert not {a["nom"] for a in AIDES} & set(AIDES_RETIREES)
