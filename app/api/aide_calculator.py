class CalculateurAides:
    def __init__(self, user_profile, toutes_les_aides):
        self.user = user_profile
        self.aides = toutes_les_aides

    def executer(self):
        eligibles = []
        montant_total = 0

        for aide in self.aides:
            if self._est_eligible(aide):
                eligibles.append(aide)
                if aide.montant:
                    montant_total += aide.montant

        return {
            "aides": eligibles,
            "total_potentiel": montant_total
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
            if self.user.statut not in aide.statut_requis:
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
