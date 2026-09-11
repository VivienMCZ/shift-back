# Les aides qui sont en réalité des prêts (remboursables) portent cette
# catégorie. Elles restent proposées, mais ne sont pas additionnées au total
# des aides : afficher « jusqu'à 2 400 € d'aides » dont 1 200 € à rembourser
# serait trompeur.
CATEGORIE_PRET = "Prêt"

# Le front a longtemps envoyé ``chomeur`` alors que les aides exigent
# ``demandeur_emploi`` : un demandeur d'emploi ne voyait ni le CPF ni le FAJ.
# L'alias reste accepté, car des profils déjà enregistrés portent cette valeur.
ALIAS_STATUTS = {"chomeur": "demandeur_emploi"}


class CalculateurAides:
    def __init__(self, user_profile, toutes_les_aides):
        self.user = user_profile
        self.aides = toutes_les_aides

    def statuts(self):
        """Statuts sous lesquels l'utilisateur peut prétendre à une aide.

        Le statut principal, plus ceux qui découlent des situations cumulables :
        une aide réservée aux salariés du BTP (``salarie_btp``) est ouverte à un
        salarié ou un apprenti qui a déclaré travailler dans le bâtiment.
        """
        statut = ALIAS_STATUTS.get(self.user.statut, self.user.statut)
        statuts = {statut}
        if self.user.reserviste:
            statuts.add("reserve_militaire")
        if self.user.secteur_btp:
            statuts.add("salarie_btp")
        if self.user.secteur_hcr:
            statuts.add("salarie_hcr")
        return statuts

    def executer(self):
        eligibles = []
        montant_total = 0
        montant_prets = 0

        for aide in self.aides:
            if self._est_eligible(aide):
                eligibles.append(aide)
                if not aide.montant:
                    continue
                if getattr(aide, "categorie", None) == CATEGORIE_PRET:
                    montant_prets += aide.montant
                else:
                    montant_total += aide.montant

        return {
            "aides": eligibles,
            "total_potentiel": montant_total,
            "total_prets": montant_prets,
        }

    def _est_eligible(self, aide):
        if aide.age_max and self.user.age > aide.age_max:
            return False
        if aide.age_min and self.user.age < aide.age_min:
            return False

        if aide.region and self.user.region != aide.region:
            return False
        if aide.departement and self.user.departement != aide.departement:
            return False
        if aide.commune and self.user.commune != aide.commune:
            return False

        if aide.statut_requis and len(aide.statut_requis) > 0:
            if self.statuts().isdisjoint(aide.statut_requis):
                return False

        if aide.handicap_requis and not self.user.has_rqth:
            return False
        if aide.boursier_requis and not self.user.is_boursier:
            return False
        if aide.inscrit_france_travail_requis and not self.user.inscrit_france_travail:
            return False
        if aide.rsa_requis and not self.user.beneficiaire_rsa:
            return False
        if aide.formation_qualifiante_requise and not self.user.en_formation_qualifiante:
            return False

        return True
