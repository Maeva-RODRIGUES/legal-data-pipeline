# Contrat de l'API de recherche (`src/api/`)

Spécification de référence : [`search-api.md`](search-api.md). Ce document est la phase 1 : il fixe les routes, les paramètres, les réponses et les erreurs. **Validé le 26/09/2026**, avec les décisions de la section 11.

## 0. Vérifications préalables (faites, lecture seule, 26/09/2026)
- Alias `decisions` → un seul index, `decisions_20260926_135231` ; `max_result_window` = 10 000 (valeur par défaut).
- Silver : 6683 `adlc-opendata`, 24 `judilibre`. Aucun titre Judilibre (24/24 `NULL`), aucun titre ADLC manquant ; aucune date ni aucun numéro `NULL`.
- `decision_type` : `concentration` (4082), `decision` (1922), `avis` (678), `lettre_ministre` (1) ; `NULL` pour Judilibre.
- `sectors` : 19 valeurs distinctes, libellés libres de la source (`Distribution`, `Energie / Environnement`, `Banque / Assurance`…).
- `external_id` ADLC = URL complète de la décision (`https://www.autoritedelaconcurrence.fr/fr/avis/...`) : contient `/`, `//` et `:`, d'où un identifiant en paramètre de requête pour la route de détail (voir 3).
- Surlignage testé sur l'alias avec la requête de `query.py` : `electricite` → 457 résultats, extraits `<mark>` dans le titre et le texte (le texte est indexé avec `offsets`).

## 1. Principes communs
- **Lecture seule** : Elasticsearch n'est appelé qu'en `search`, `ping` et lecture d'alias ; PostgreSQL uniquement en `SELECT`, dans des connexions `read_only = True` (une écriture échouerait côté serveur, pas seulement par convention).
- **Configuration** : `DATABASE_URL` et `ELASTICSEARCH_URL` (lus via `python-dotenv`, comme les autres points d'entrée). Variable absente → échec au démarrage, avec le nom de la variable dans le message (jamais sa valeur).
- **Délais** : Elasticsearch `request_timeout=5` s ; PostgreSQL `connect_timeout=3` s et `statement_timeout=5000` ms. Un délai dépassé donne une 503, jamais une attente sans fin.
- **Pas de préfixe de version** (`/search`, pas `/v1/search`) : API locale, un seul client.
- **Dates** : `YYYY-MM-DD` pour les dates de décision, ISO 8601 avec fuseau pour les horodatages.
- **Documentation** : `/docs` (Swagger UI) et `/openapi.json`, générés par FastAPI à partir des modèles Pydantic de ce contrat.

## 2. `GET /search` — recherche plein texte ou par numéro

### Paramètres (query string)
| Paramètre | Type | Défaut | Règle |
|---|---|---|---|
| `q` | texte | — | recherche plein texte ; 1 à 500 caractères après suppression des espaces autour |
| `number` | texte | — | recherche par numéro exact ; 1 à 100 caractères après suppression des espaces autour |
| `source` | `judilibre` \| `adlc-opendata` | — | répétable (`?source=a&source=b`) |
| `decision_type` | `concentration` \| `decision` \| `avis` \| `lettre_ministre` | — | répétable |
| `date_from` | date | — | incluse, sur `decision_date` |
| `date_to` | date | — | incluse ; `date_from` ≤ `date_to` |
| `sector` | texte | — | répétable ; valeur exacte (casse et accents compris), comme dans Silver |
| `page` | entier | 1 | ≥ 1 |
| `page_size` | entier | 10 | 1 à 50 ; `page × page_size` ≤ 10 000 |

**Exactement un** des deux paramètres `q` et `number` est fourni : aucun ou les deux → 422.

Plusieurs valeurs d'un même filtre se combinent en **OU**, des filtres différents en **ET**. Une valeur inconnue de `source` ou `decision_type` est refusée (422) ; un `sector` inconnu donne simplement 0 résultat (liste non contrôlée). Filtrer sur `decision_type` exclut de fait Judilibre (type vide).

### Requête envoyée à l'alias `decisions`
La requête évaluée n'est jamais réécrite : elle est construite par `query.py`, puis complétée.

```python
if number is None:
    query = title_query(q, DEFAULT_TITLE_BOOST)       # inchangée
else:
    query = number_query(number)                      # inchangée
if filters:
    query = {"bool": {"must": [query], "filter": filters}}  # clauses filter : aucun effet sur le score
body = search_body(query)                             # track_total_hits: true conservé
body |= {"from": (page - 1) * page_size, "size": page_size,
         "_source": [<champs de la réponse, sans text ni attributes>],
         "highlight": HIGHLIGHT}                 # recherche plein texte seulement
```

- **Sans filtre**, la clause `query` est **identique** à celle de l'évaluation. Avec filtres, elle est dans `bool.must` et les filtres (`terms` sur `source`, `decision_type`, `sectors` ; `range` sur `decision_date`) dans `bool.filter` : les scores restent ceux de la requête évaluée.
- Tri : pertinence seule (`_score`), comme dans l'évaluation.
- Recherche par numéro : mêmes filtres, même pagination, **sans surlignage** (`highlight` absent du corps, `highlights` vide dans la réponse). La casse et les accents du numéro sont ignorés par le normaliseur `folded` du mapping, qui s'applique aussi à la valeur cherchée.
- `HIGHLIGHT` : `encoder: html` (le texte source est échappé, seules les balises `<mark>` sont du HTML), `pre_tags ["<mark>"]`, `post_tags ["</mark>"]` ; `title` en entier (`number_of_fragments: 0`), `text` en 3 fragments de 150 caractères au plus.

### Réponse 200
```json
{
  "query": "electricite",
  "number": null,
  "filters": {"source": [], "decision_type": [], "date_from": null, "date_to": null, "sector": []},
  "page": 1,
  "page_size": 10,
  "total": 457,
  "results": [
    {
      "source": "adlc-opendata",
      "external_id": "https://www.autoritedelaconcurrence.fr/fr/avis/concernant-leffacement-de-consommation-dans-le-secteur-de-lelectricite",
      "decision_number": "12-A-19",
      "issuer": "Autorité de la concurrence",
      "decision_type": "avis",
      "decision_date": "2012-07-26",
      "title": "concernant l’effacement de consommation dans le secteur de l’électricité",
      "display_title": "concernant l’effacement de consommation dans le secteur de l’électricité",
      "sectors": ["Energie / Environnement"],
      "url": "https://www.autoritedelaconcurrence.fr/fr/avis/concernant-leffacement-de-consommation-dans-le-secteur-de-lelectricite",
      "has_text": true,
      "score": 11.95,
      "highlights": {
        "title": ["concernant l’effacement de consommation dans le secteur de <mark>l’électricité</mark>"],
        "text": ["chaque consommateur <mark>d&#x27;électricité</mark> (...) est responsable des écarts entre les injections et les soutirages <mark>d&#x27;électricité</mark> auxquels il procède »."]
      },
      "detail_path": "/decisions/adlc-opendata?id=https%3A%2F%2Fwww.autoritedelaconcurrence.fr%2Ffr%2Favis%2Fconcernant-leffacement-de-consommation-dans-le-secteur-de-lelectricite"
    }
  ]
}
```
- `total` : nombre exact de résultats (`hits.total.value`, relation `eq` grâce à `track_total_hits`).
- `query` / `number` : le paramètre reçu (nettoyé), l'autre vaut `null`.
- `highlights.title` / `highlights.text` : listes éventuellement vides (pas de correspondance dans ce champ, décision sans texte, ou recherche par numéro).
- `title` : valeur brute de l'index (`null` pour Judilibre) ; `display_title` : voir 7.
- `detail_path` : chemin et paramètre de la route de détail, `external_id` déjà encodé, pour éviter au client de le reconstruire.
- Page au-delà du dernier résultat : 200 avec `results: []` et le `total` réel.

## 3. `GET /decisions/{source}?id=...` — détail d'une décision
Lu dans `silver.decisions` (clé primaire `source, external_id`), jamais dans l'index.

- `source` (chemin) : `judilibre` \| `adlc-opendata` (autre valeur → 422).
- `id` (requête, obligatoire) : l'`external_id`, encodé en pourcentage par le client (`/` → `%2F`, `:` → `%3A`). En paramètre de requête plutôt que dans le chemin : les identifiants ADLC sont des URL avec `/` et `//`, que certains serveurs normalisent dans un chemin. Comparé tel quel (aucune suppression d'espaces : c'est une clé). Le `detail_path` des résultats de recherche est déjà prêt à l'emploi.

### Réponse 200
```json
{
  "source": "judilibre",
  "external_id": "6a6c3834d6da041962933bac",
  "decision_number": "26-83.146",
  "issuer": "Cour de cassation",
  "decision_type": null,
  "decision_date": "2026-07-29",
  "title": null,
  "display_title": "Cour de cassation, 29 juillet 2026, n° 26-83.146",
  "text": "…texte intégral…",
  "has_text": true,
  "sectors": [],
  "url": "https://www.courdecassation.fr/decision/6a6c3834d6da041962933bac",
  "attributes": {"ecli": "ECLI:FR:CCASS:2026:CR01159", "chamber": "cr", "solution": "cassation", "...": "..."},
  "built_at": "2026-09-25T13:08:36.399674+00:00"
}
```
`text` est renvoyé en entier (jusqu'à 1,2 million de caractères) ; `has_text` suit la même règle que l'index (`src/search/document.py`). `attributes` est renvoyé tel quel (champs propres à chaque source).

## 4. `GET /runs` — derniers runs du pipeline
Lu dans `bronze.collection_runs`, du plus récent au plus ancien (`run_id` décroissant).

| Paramètre | Type | Défaut | Règle |
|---|---|---|---|
| `source` | texte | — | répétable ; valeur exacte (`judilibre`, `adlc-opendata`, `adlc-scraper`, `silver`, `quality`, `search`, `search-eval`), non contrôlée : une source inconnue donne une liste vide |
| `status` | `running` \| `success` \| `failed` | — | |
| `limit` | entier | 20 | 1 à 100 |

### Réponse 200
```json
{
  "runs": [
    {
      "run_id": 33,
      "source": "quality",
      "date_type": "checks",
      "date_start": "2026-09-26",
      "date_end": "2026-09-26",
      "started_at": "2026-09-26T13:54:21.430157+00:00",
      "finished_at": "2026-09-26T13:54:23.303507+00:00",
      "status": "success",
      "nb_fetched": 22,
      "nb_new": 0,
      "nb_changed": 0,
      "error": null
    }
  ]
}
```
`error` est renvoyé tel que stocké (1000 caractères au plus à l'écriture) ; `finished_at` vaut `null` pour un run `running`, `date_type` pour les runs antérieurs à la migration 002.

## 5. `GET /quality/latest` — derniers résultats qualité
Résultats du dernier run présent dans `quality.check_results` (`max(run_id)`), avec le run correspondant de `bronze.collection_runs`. Le verdict est recalculé par `src.quality.evaluate.run_failed`, sans dupliquer la règle.

| Paramètre | Type | Défaut | Règle |
|---|---|---|---|
| `status` | `pass` \| `fail` \| `no_data` \| `unchecked` \| `query_error` | — | répétable ; filtre `results`, sans changer `verdict` ni `counts` |

### Réponse 200
```json
{
  "run": {"run_id": 33, "started_at": "2026-09-26T13:54:21.430157+00:00", "finished_at": "2026-09-26T13:54:23.303507+00:00", "status": "success"},
  "verdict": "success",
  "counts": {"pass": 22, "fail": 0, "no_data": 0, "unchecked": 0, "query_error": 0},
  "results": [
    {
      "check_name": "hours_since_last_success",
      "dimension": "freshness",
      "severity": "warning",
      "source": "search",
      "value": 0,
      "expected": "<= 168",
      "status": "pass",
      "error": null,
      "checked_at": "2026-09-26T13:54:23.2+00:00"
    }
  ]
}
```
- `verdict` : `failure` si un résultat de sévérité `error` est en `fail`, `no_data` ou `query_error`, `success` sinon (même règle que le code de sortie de `src.quality.run`).
- `value` : nombre JSON (le `NUMERIC` PostgreSQL est converti ; entier quand il n'a pas de partie décimale), `null` pour `no_data` et `query_error`.
- Ordre des résultats : celui du rapport de `src.quality.run` (statut, puis sévérité, contrôle et source).
- Aucun résultat qualité en base → 404 `quality_results_not_found`.

## 6. `GET /health` — état de PostgreSQL et d'Elasticsearch
Les deux services sont toujours testés, indépendamment : l'échec de l'un n'empêche pas de rendre compte de l'autre.

- PostgreSQL : `SELECT 1`.
- Elasticsearch : `ping`, puis index cible de l'alias `decisions`. Serveur joignable **sans** alias → `error` : la recherche est impossible.

### Réponses
**200** si les deux services sont `ok`, **503** sinon, avec le même corps (utilisable par un healthcheck de conteneur) :
```json
{
  "status": "degraded",
  "services": {
    "postgres": {"status": "ok", "latency_ms": 4, "error": null},
    "elasticsearch": {"status": "error", "latency_ms": 5003, "index": null, "error": "connection timeout"}
  }
}
```
`status` global : `ok` ou `degraded`. `error` : type et message court de l'exception, sans l'URL de connexion (qui peut contenir un mot de passe).

## 7. Titre d'affichage (`display_title`)
Calculé dans l'API (fonction pure, dans `src/api/`), jamais stocké ; présent dans la recherche et le détail.

- `title` non vide → `display_title = title`, tel quel (les titres ADLC commencent souvent par une minuscule : pas de retouche).
- Sinon (Judilibre) → format de citation : `{issuer}, {jour} {mois en toutes lettres} {année}, n° {decision_number}`.
  - Mois en français, sans dépendre de la locale du système (table des 12 mois dans le code).
  - Premier jour du mois : `1er` (`Cour de cassation, 1er octobre 2026, n° 26-12.345`), selon l'usage des citations.
  - Élément manquant (`issuer`, date ou numéro) : le segment est omis ; si les trois manquent, `Décision {external_id}`. Aucun cas en base aujourd'hui, mais Silver l'autorise (colonnes nullables).

Exemples : `Cour de cassation, 29 juillet 2026, n° 26-83.146` ; sans date : `Cour de cassation, n° 26-83.146`.

## 8. Erreurs
Corps unique pour toutes les erreurs, y compris la 422 de validation de FastAPI (gestionnaire remplacé) :
```json
{"error": {"code": "invalid_parameter", "message": "date_from must be on or before date_to", "details": [{"field": "date_from", "message": "..."}]}}
```

| Cas | Statut | `code` |
|---|---|---|
| Paramètre absent, mal typé, hors bornes, valeur d'énumération inconnue, `date_from > date_to`, `page × page_size > 10000`, `q` ou `number` vide, ni `q` ni `number`, ou les deux, `id` absent | 422 | `invalid_parameter` |
| Décision absente de `silver.decisions` | 404 | `decision_not_found` |
| Aucun résultat qualité | 404 | `quality_results_not_found` |
| Route inconnue | 404 | `not_found` |
| Elasticsearch injoignable ou délai dépassé | 503 | `elasticsearch_unavailable` |
| Alias `decisions` absent | 503 | `search_index_unavailable` |
| PostgreSQL injoignable ou délai dépassé | 503 | `database_unavailable` |
| Toute autre exception | 500 | `internal_error` (message générique ; détail dans les logs, jamais dans la réponse) |

Chaque route ne dépend que de son service : `/search` fonctionne sans PostgreSQL, `/decisions`, `/runs` et `/quality/latest` sans Elasticsearch.

## 9. Tests prévus (sans Elasticsearch, sans base, sans réseau)
Dépendances FastAPI remplacées (`app.dependency_overrides`) par de faux clients, avec `TestClient` :
- `/search` : la clause envoyée est **égale** à `title_query(q, DEFAULT_TITLE_BOOST)` (ou `number_query(number)`) sans filtre, et à `bool.must[0]` avec filtres ; `q` et `number` exclusifs ; pas de surlignage par numéro ; filtres, pagination (`from`/`size`), `track_total_hits`, surlignage ; mise en forme des résultats, `detail_path`, page vide.
- `/decisions` : ADLC (identifiant URL encodé en paramètre), Judilibre avec `display_title`, `id` absent (422), 404.
- `/runs`, `/quality/latest` : filtres, `limit`, verdict `success` / `failure`, 404 sans résultat.
- `/health` : 200, 503 pour chaque service en panne, alias absent.
- Chaque ligne du tableau des erreurs ; `display_title` : cas nominal, `1er`, segments manquants.

## 10. Fichiers prévus (phase 2)
```
src/api/__init__.py
src/api/main.py          # application, gestionnaires d'erreurs, routes, dépendances
src/api/backends.py      # configuration, accès Elasticsearch et PostgreSQL (lecture seule), erreurs 503
src/api/search.py        # construction du corps de recherche autour de query.py, mise en forme des résultats
src/api/models.py        # modèles Pydantic des réponses
src/api/display.py       # display_title
tests/test_api_*.py
requirements.txt         # + fastapi, uvicorn
README.md                # section « API », commande dans « Lancer le projet », « Structure du projet »
```
Lancement : `uvicorn src.api.main:app` (routes synchrones, exécutées par FastAPI dans son pool de threads ; une connexion PostgreSQL par requête, sans pool : volume local).

## 11. Décisions (26/09/2026)
1. **Recherche par numéro** : ajoutée, par le paramètre `number`, exclusif de `q` (l'un des deux est obligatoire), avec `number_query`, sans surlignage, avec les mêmes filtres et la même pagination.
2. **Route de détail** : identifiant en paramètre de requête, `GET /decisions/{source}?id=...` ; `detail_path` adapté.
3. **Format des erreurs** : enveloppe unique `{"error": …}`, y compris pour la 422.
4. **`/health`** : 503 quand un service est en panne.
5. **`q` obligatoire**, sauf quand `number` est fourni.

## 12. Écarts relevés
1. **Exemple de titre de la spec** : la décision 26-83.146 est datée du 29 juillet 2026 en Silver. Décision : le titre suit la date de décision (`Cour de cassation, 29 juillet 2026, n° 26-83.146`).
2. **Nombre de contrôles qualité** : les deux contrôles de trouvabilité manquaient dans `src/quality/checks.yml` ; ajoutés (commit 22bfa1a), le catalogue compte 12 contrôles.
