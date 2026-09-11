"""Localisation administrative déduite d'un code postal.

Le calculateur ne demande que le code postal : c'est la seule donnée que
l'utilisateur connaît à coup sûr. Les aides, elles, sont restreintes par
région ou par département. Sans cette traduction, les aides territoriales ne
pouvaient jamais correspondre, faute de région dans le profil.

La déduction est faite hors ligne, sans appel réseau : les deux premiers
chiffres d'un code postal désignent le département, à trois exceptions près
(Corse, outre-mer, Monaco). Quelques codes postaux sont partagés entre deux
départements limitrophes ; l'erreur reste alors dans la région voisine et ne
concerne qu'une poignée de communes, ce qui est acceptable pour une simulation
indicative.
"""

import re

CODE_POSTAL_PATTERN = r"^[0-9]{5}$"

# Noms identiques à ceux de la colonne ``AideDB.region`` et de la liste du
# front : la comparaison se fait à l'égalité stricte.
REGIONS_PAR_DEPARTEMENT: dict[str, str] = {
    **dict.fromkeys(
        ["01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"],
        "Auvergne-Rhône-Alpes",
    ),
    **dict.fromkeys(
        ["21", "25", "39", "58", "70", "71", "89", "90"], "Bourgogne-Franche-Comté"
    ),
    **dict.fromkeys(["22", "29", "35", "56"], "Bretagne"),
    **dict.fromkeys(["18", "28", "36", "37", "41", "45"], "Centre-Val de Loire"),
    **dict.fromkeys(["2A", "2B"], "Corse"),
    **dict.fromkeys(
        ["08", "10", "51", "52", "54", "55", "57", "67", "68", "88"], "Grand Est"
    ),
    **dict.fromkeys(["02", "59", "60", "62", "80"], "Hauts-de-France"),
    **dict.fromkeys(
        ["75", "77", "78", "91", "92", "93", "94", "95"], "Île-de-France"
    ),
    **dict.fromkeys(["14", "27", "50", "61", "76"], "Normandie"),
    **dict.fromkeys(
        ["16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87"],
        "Nouvelle-Aquitaine",
    ),
    **dict.fromkeys(
        ["09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"],
        "Occitanie",
    ),
    **dict.fromkeys(["44", "49", "53", "72", "85"], "Pays de la Loire"),
    **dict.fromkeys(
        ["04", "05", "06", "13", "83", "84"], "Provence-Alpes-Côte d'Azur"
    ),
    "971": "Guadeloupe",
    "972": "Martinique",
    "973": "Guyane",
    "974": "La Réunion",
    "976": "Mayotte",
}

# En Corse, les codes postaux commencent tous par 20 : c'est la tranche qui
# sépare la Corse-du-Sud (200xx-201xx) de la Haute-Corse (202xx-206xx).
SEUIL_HAUTE_CORSE = 20200


def departement_depuis_code_postal(code_postal: str | None) -> str | None:
    """Code du département (``"75"``, ``"2A"``, ``"971"``…), ou ``None``.

    ``None`` pour une saisie invalide ou hors départements (Monaco, collectivités
    d'outre-mer) : aucune aide départementale ne leur correspond.
    """
    if not code_postal or not re.fullmatch(CODE_POSTAL_PATTERN, code_postal):
        return None

    if code_postal.startswith("97"):
        departement = code_postal[:3]
    elif code_postal.startswith("20"):
        departement = "2A" if int(code_postal) < SEUIL_HAUTE_CORSE else "2B"
    else:
        departement = code_postal[:2]

    return departement if departement in REGIONS_PAR_DEPARTEMENT else None


def region_depuis_departement(departement: str | None) -> str | None:
    return REGIONS_PAR_DEPARTEMENT.get(departement) if departement else None
