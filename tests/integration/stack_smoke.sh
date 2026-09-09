#!/usr/bin/env bash
#
# Test d'intégration de la pile assemblée : PostgreSQL + API dans Docker Compose.
#
# La suite pytest tourne sur SQLite jetable et un TestClient : elle valide la
# logique, jamais l'assemblage réel. Ce script comble ce trou — il démarre les
# vrais conteneurs, attend que l'API se déclare saine, puis vérifie de bout en
# bout que le service répond, que la base est bien connectée, que la pagination
# et le géocodage fonctionnent, et que les durcissements de sécurité clés
# tiennent sur l'application qui tourne (et non sur un TestClient en mémoire).
#
# Les contrôles de sécurité ci-dessous ne dupliquent pas la suite unitaire :
# ils confirment que le même comportement survit une fois l'app conteneurisée,
# derrière ses middlewares et son serveur ASGI réels.
#
# Usage :
#   tests/integration/stack_smoke.sh
#
# Prérequis : Docker + Docker Compose. Un fichier .env est généré si absent.
# Seuls les services db et api sont démarrés (le service front vit dans un autre
# dépôt, hors périmètre de ce test).
#
# ISOLATION — ce test ne touche JAMAIS la stack de développement :
#   * Il s'exécute dans un projet Compose dédié (``shift-back-itest``), donc ses
#     conteneurs et son volume portent un préfixe distinct : le nettoyage final
#     (``down -v``) ne peut pas supprimer le volume ``shift-back_pgdata`` du dev.
#   * Si la stack de dev tourne déjà (elle occupe les ports 8000/5432), le script
#     s'arrête immédiatement sans rien démarrer ni arrêter, et demande de la
#     stopper d'abord. Aucune action destructrice sur une stack existante.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Projet Compose dédié : cloisonne conteneurs ET volume du test vis-à-vis du dev.
PROJET_TEST="${COMPOSE_ITEST_PROJECT:-shift-back-itest}"
COMPOSE="docker compose -p $PROJET_TEST"
SERVICES="db api"
BASE="http://localhost:8000"
ECHECS=0

log() { printf '\n\033[1;34m== %s\033[0m\n' "$1"; }
ok()  { printf '  \033[1;32mOK\033[0m   %s\n' "$1"; }
ko()  { printf '  \033[1;31mKO\033[0m   %s\n' "$1"; ECHECS=$((ECHECS + 1)); }

# Vérifie qu'une requête renvoie le code HTTP attendu.
attendu() {
  local libelle="$1" attendu_code="$2" url="$3"; shift 3
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' "$@" "$url")"
  if [ "$code" = "$attendu_code" ]; then ok "$libelle ($code)"; else ko "$libelle : attendu $attendu_code, obtenu $code"; fi
}

# ---------------------------------------------------------------------------- #
# Garde-fou : ne jamais marcher sur une stack de développement
#
# La stack de dev (projet Compose par défaut ``shift-back``) occupe les mêmes
# ports 8000/5432. Si elle tourne, on s'arrête AVANT tout : ni démarrage, ni
# arrêt, ni suppression de volume. L'utilisateur la stoppe lui-même s'il veut
# lancer l'intégration.
# ---------------------------------------------------------------------------- #
dev_en_cours="$(docker compose ps -q 2>/dev/null || true)"
if [ -n "$dev_en_cours" ]; then
  printf '\033[1;31mUne stack de développement tourne déjà (projet Compose par défaut).\033[0m\n'
  printf 'Ce test occuperait les mêmes ports et pourrait la perturber.\n'
  printf 'Arrête-la d’abord :  docker compose down\n'
  printf 'Puis relance ce script.\n'
  exit 1
fi

# ---------------------------------------------------------------------------- #
# Préparation
# ---------------------------------------------------------------------------- #
if [ ! -f .env ]; then
  log "Génération d'un .env de test (aucun secret réel)"
  JWT="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  cat > .env <<EOF
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=postgres
JWT_SECRET=$JWT
ADMIN_API_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
OTP_DEBUG_DELIVERY=false
EOF
fi

nettoyage() {
  # $COMPOSE est cadré sur le projet dédié : ce down -v ne supprime que le
  # volume du test (shift-back-itest_pgdata), jamais celui du dev.
  log "Arrêt de la pile de test"
  $COMPOSE logs api --tail 40 || true
  $COMPOSE down -v --remove-orphans || true
}
trap nettoyage EXIT

# ---------------------------------------------------------------------------- #
# Démarrage
# ---------------------------------------------------------------------------- #
log "Build et démarrage de $SERVICES"
$COMPOSE up -d --build $SERVICES

log "Attente de l'état sain de l'API (max 120 s)"
pret=0
for _ in $(seq 1 60); do
  etat="$($COMPOSE ps api --format '{{.Health}}' 2>/dev/null || echo '')"
  if [ "$etat" = "healthy" ]; then pret=1; break; fi
  sleep 2
done
if [ "$pret" != "1" ]; then ko "l'API n'est jamais devenue saine"; exit 1; fi
ok "API saine"

# ---------------------------------------------------------------------------- #
# Bout en bout : le service et la base répondent
# ---------------------------------------------------------------------------- #
log "Parcours fonctionnel"
attendu "GET /health"                 200 "$BASE/health"
attendu "GET /api/ecoles (liste)"     200 "$BASE/api/ecoles?limit=5"
attendu "GET /api/locations/search"   200 "$BASE/api/locations/search?q=paris"

# La liste doit porter l'en-tête de total ET l'en-tête de cache public :
# c'est la preuve que la route traverse bien la base et les middlewares réels.
entetes="$(curl -s -D - -o /dev/null "$BASE/api/ecoles?limit=5")"
echo "$entetes" | grep -iq '^x-total-count:'  && ok "en-tête X-Total-Count présent"          || ko "X-Total-Count manquant"
echo "$entetes" | grep -iq '^cache-control: public' && ok "liste publique cachable"           || ko "Cache-Control public manquant sur la liste"

# ---------------------------------------------------------------------------- #
# Sécurité sur l'application assemblée (ne double pas les tests unitaires,
# confirme qu'ils tiennent une fois conteneurisés)
# ---------------------------------------------------------------------------- #
log "Durcissements sur la pile réelle"

# A05 — en-têtes de durcissement injectés par le middleware ASGI.
for h in x-content-type-options x-frame-options content-security-policy; do
  echo "$entetes" | grep -iq "^$h:" && ok "en-tête $h présent" || ko "en-tête $h manquant"
done

# A01 — favoris cloisonnés : inaccessibles sans session, et jamais publiquement
# cachables. Le `no-store` sur la réponse *authentifiée* est vérifié par la suite
# unitaire (test_favoris_jamais_mis_en_cache) ; ici, sans session, on obtient un
# 401 — qu'un cache partagé ne mémorise pas par défaut. On confirme seulement
# qu'aucun `public` ne s'y glisse.
attendu "GET /favorites sans session refusé" 401 "$BASE/api/ecoles/favorites"
fav="$(curl -s -D - -o /dev/null "$BASE/api/ecoles/favorites")"
echo "$fav" | grep -iq '^cache-control: public' && ko "favoris marqués public" || ok "favoris non publiquement cachables"

# A01 — écriture sur les libellés fermée sans jeton admin.
attendu "POST /libs sans jeton refusé" 401 "$BASE/api/v1/libs/" \
  -X POST -H 'Content-Type: application/json' -d '{"key":"x","fr":"a","en":"b"}'

# A03 — liste blanche sur la sélection de colonne par langue.
attendu "lang=otp_code rejeté" 400 "$BASE/api/v1/libs/x/translate?lang=otp_code"

# A04 — bornes d'entrée.
attendu "limit hors borne rejeté" 422 "$BASE/api/ecoles?limit=99999"

# ---------------------------------------------------------------------------- #
# Verdict
# ---------------------------------------------------------------------------- #
log "Résultat"
if [ "$ECHECS" -eq 0 ]; then
  printf '\033[1;32mTous les contrôles d’intégration sont passés.\033[0m\n'
  exit 0
fi
printf '\033[1;31m%s contrôle(s) en échec.\033[0m\n' "$ECHECS"
exit 1
