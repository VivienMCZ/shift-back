# shift-back

API FastAPI du comparateur d'auto-écoles et du calculateur d'aides Shift.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Renseigner ensuite les secrets dans `.env` (voir [Configuration](#configuration)) :

```bash
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))"
python -c "import secrets; print('ADMIN_API_TOKEN=' + secrets.token_urlsafe(32))"
```

## Lancer le serveur

```bash
uvicorn app.main:app --reload
```

L'API sera disponible sur `http://127.0.0.1:8000`.

En local hors Docker, `DATABASE_URL` doit pointer vers `localhost`, par exemple :

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
```

## Lancer avec Docker Compose

```bash
docker compose up -d --build
```

- API : `http://localhost:8000`
- PostgreSQL : `localhost:5432`
- pgAdmin : `http://localhost:5050` (profil `tools` : `docker compose --profile tools up -d pgadmin`)

Dans Docker Compose, le backend utilise le host PostgreSQL `db` car ce nom est résolu
par le réseau Docker interne. Depuis la machine hôte, il faut utiliser `localhost`.

Si le port local `5432` est déjà occupé, choisir un autre port hôte sans changer le
port interne Docker :

```bash
POSTGRES_HOST_PORT=5433 docker compose up -d --build
```

Dans ce cas, une API lancée hors Docker doit aussi utiliser ce port dans `DATABASE_URL`.

Configuration du serveur PostgreSQL dans pgAdmin — host `db`, port `5432`, puis les
identifiants de `.env` (`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`).

## Tests

```bash
pytest                                   # suite complète
pytest --cov --cov-report=term           # avec couverture
pytest tests/test_security.py -v         # durcissements OWASP uniquement
```

La suite s'exécute sur une base **SQLite jetable** : `tests/conftest.py` force
`DATABASE_URL` avant tout import de `app.*`, de sorte qu'aucune exécution de tests
ne peut atteindre une base réelle, même si l'environnement en expose une.

## Configuration

Toutes les variables sont documentées dans `.env.example`. Les plus sensibles :

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `JWT_SECRET` | Signature des jetons de session. **32 caractères minimum**, l'application refuse de démarrer en deçà. | *(requis)* |
| `ADMIN_API_TOKEN` | Jeton attendu dans l'en-tête `X-Admin-Token` pour écrire sur `/api/v1/libs`. Vide = toute écriture refusée. | *(vide)* |
| `COOKIE_SECURE` | `true` dès que l'API est servie en HTTPS. Active aussi l'en-tête HSTS. | `false` |
| `COOKIE_SAMESITE` | `lax`, `strict` ou `none`. | `lax` |
| `CORS_ORIGINS` | Origines autorisées, séparées par des virgules. Vide = défauts de développement. | localhost:3000/3001 |
| `ENABLE_DOCS` | Expose `/docs`, `/redoc` et `/openapi.json`. À passer à `false` en production. | `true` |
| `OTP_MAX_ATTEMPTS` | Essais de vérification d'un code avant blocage temporaire du compte. | `5` |
| `OTP_REQUEST_MAX` | Demandes d'envoi de code par IP et par fenêtre. | `10` |
| `OTP_DEBUG_DELIVERY` | Affiche le code OTP en console. **Développement uniquement.** | `false` |

## Sécurité

Correctifs appliqués, par catégorie du [Top 10 OWASP](https://owasp.org/www-project-top-ten/) :

| Catégorie | Mesure |
| --- | --- |
| A01 Broken Access Control | Écriture sur `/api/v1/libs` derrière `X-Admin-Token`, en échec fermé si le jeton n'est pas configuré. Favoris et historique d'aides cloisonnés par utilisateur. En-têtes `Cache-Control` posés **par route** : `public` sur la liste et la fiche d'auto-école, `private, no-store` sur `/api/ecoles/favorites`. Poser l'en-tête au niveau du routeur laisserait un cache partagé servir les favoris d'un compte à un autre. |
| A02 Cryptographic Failures | OTP tirés de `secrets`, stockés en HMAC-SHA256 et jamais en clair. `JWT_SECRET` obligatoire et d'au moins 32 caractères. Cookie `HttpOnly`, `Secure`/`SameSite` configurables. |
| A03 Injection | Requêtes via l'ORM. Liste blanche stricte sur le paramètre `lang` (sélection de colonne). Jokers SQL neutralisés dans le filtre `gear`. Longueurs et formats bornés sur toutes les entrées. |
| A04 Insecure Design | Plafonnement des essais d'OTP par compte et des demandes d'envoi par IP. |
| A05 Security Misconfiguration | Conteneur exécuté sans privilège (`appuser`). En-têtes `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `CSP`, `COOP`, `Permissions-Policy`, HSTS en HTTPS. CORS et documentation pilotés par l'environnement. Plus aucun secret par défaut dans `docker-compose.yml`. |
| A06 Vulnerable Components | Dépendances figées, auditées par `pip-audit` en CI et mises à jour par Dependabot. Image de base scannée par Trivy. |
| A07 Authentication Failures | Blocage après plusieurs codes erronés, code invalidé après usage, jeton horodaté (`iat`/`exp`). |
| A08 Data Integrity | Versions épinglées, workflows et image Docker suivis par Dependabot. |
| A09 Logging Failures | Suppression des `print` qui exposaient cookies, jetons et codes OTP. Aucun secret dans les journaux, mot de passe masqué dans l'URL de base. |
| A10 SSRF | Le proxy de géocodage cible un hôte fixe ; l'appelant ne contrôle que les paramètres de requête. |

### Limites connues

- **Limitation de débit en mémoire.** Les compteurs vivent dans le processus.
  Derrière plusieurs workers ou plusieurs instances, il faut un stockage partagé
  (Redis) pour que les plafonds restent effectifs.
- **Énumération de comptes.** `/auth/request-otp` renvoie `404` sur un e-mail
  inconnu, et `/auth/register` `400` sur un e-mail déjà pris. Le parcours du
  front s'appuie sur ces codes pour basculer vers l'inscription : les uniformiser
  casserait la connexion. À traiter avec une évolution côté front.
- **Pas de rôle administrateur en base.** L'écriture sur les libellés est protégée
  par un jeton partagé, pas par un compte nominatif.
- **Pas d'outil de migration.** Le schéma est créé par `create_all` : toute
  nouvelle colonne sur une base existante devra passer par un `ALTER TABLE`
  manuel. Alembic est le prochain jalon naturel.
- **Deux jeux de données de seed.** `app/seed.py` (utilisé au démarrage) contient
  10 aides, `app/data_seed.py` en contient 34. Les deux sources doivent être
  fusionnées.

## Intégration continue

`.github/workflows/CI.yml` enchaîne trois jobs :

1. **`ci`** — pytest avec couverture (rapports JUnit et Cobertura en artefacts),
   SonarQube (ignoré sans `SONAR_TOKEN`), `pip-audit` (bloquant sur
   `requirements.txt`), build + smoke test + scan Trivy de l'image, puis le
   **test d'intégration Docker Compose** (`tests/integration/stack_smoke.sh`) :
   la pile `db` + `api` est démarrée en conteneurs et vérifiée de bout en bout
   (service, base, géocodage, durcissements de sécurité).
2. **`supply_chain`** — `gitleaks` (aucun secret commité, historique inclus) et
   `hadolint` (bonnes pratiques du `Dockerfile`, bloquant au niveau *error*).
3. **`codeql`** — analyse statique de sécurité (SAST) du code Python, requêtes
   `security-extended`. Symétrique de CodeQL côté front.

### Lancer le test d'intégration en local

```bash
bash tests/integration/stack_smoke.sh   # démarre db+api, teste, puis nettoie
```

Il génère un `.env` de test si absent (aucun secret réel requis) et ne démarre
que `db` et `api` — le service `front` vit dans un autre dépôt.

`.github/dependabot.yml` ouvre chaque lundi les PR de mise à jour pour pip, les
actions GitHub et l'image de base Docker.

## Réparer la résolution Docker de `db`

Si l'API échoue avec `could not translate host name "db" to address`, recréer les
conteneurs sans supprimer les volumes :

```bash
docker compose up -d --force-recreate db
docker compose up -d --build api front
docker compose ps -a
docker compose exec api getent hosts db
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/api/ecoles
```

Ne pas lancer `docker compose down -v` sauf si vous voulez supprimer le volume
PostgreSQL `shift-back_pgdata`.

Si `POSTGRES_HOST_PORT` est utilisé, garder le même préfixe sur les commandes
`docker compose` de réparation.

## Endpoint de santé

- `GET /health`
