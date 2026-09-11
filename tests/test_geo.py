"""Tests de la déduction département / région à partir d'un code postal."""

import pytest

from app.api.geo import (
    REGIONS_PAR_DEPARTEMENT,
    departement_depuis_code_postal,
    region_depuis_departement,
)


@pytest.mark.parametrize(
    "code_postal,departement,region",
    [
        ("75001", "75", "Île-de-France"),
        ("93200", "93", "Île-de-France"),
        ("01000", "01", "Auvergne-Rhône-Alpes"),
        ("31000", "31", "Occitanie"),
        ("83000", "83", "Provence-Alpes-Côte d'Azur"),
        ("20000", "2A", "Corse"),
        ("20167", "2A", "Corse"),
        ("20200", "2B", "Corse"),
        ("20600", "2B", "Corse"),
        ("97110", "971", "Guadeloupe"),
        ("97400", "974", "La Réunion"),
        ("97600", "976", "Mayotte"),
    ],
)
def test_departement_et_region(code_postal, departement, region):
    assert departement_depuis_code_postal(code_postal) == departement
    assert region_depuis_departement(departement) == region


@pytest.mark.parametrize(
    "code_postal",
    [None, "", "7500", "750011", "75A01", "00000", "98000", "97500"],
)
def test_code_postal_invalide_ou_hors_departement(code_postal):
    """Monaco (98000) et Saint-Pierre-et-Miquelon (97500) ne sont pas des départements."""
    assert departement_depuis_code_postal(code_postal) is None


def test_la_table_couvre_tous_les_departements():
    """96 départements métropolitains et 5 d'outre-mer, chacun dans une seule région."""
    metropole = {f"{n:02d}" for n in range(1, 96) if n != 20} | {"2A", "2B"}
    outre_mer = {"971", "972", "973", "974", "976"}
    assert set(REGIONS_PAR_DEPARTEMENT) == metropole | outre_mer
    assert len(set(REGIONS_PAR_DEPARTEMENT.values())) == 18


def test_regions_alignees_sur_le_catalogue_daides():
    """Une région mal orthographiée dans le seed ne correspondrait jamais."""
    from app.seed import AIDES

    regions_connues = set(REGIONS_PAR_DEPARTEMENT.values())
    departements_connus = set(REGIONS_PAR_DEPARTEMENT)
    for aide in AIDES:
        if aide.get("region"):
            assert aide["region"] in regions_connues, aide["nom"]
        if aide.get("departement"):
            assert aide["departement"] in departements_connus, aide["nom"]
