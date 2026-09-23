# legal-data-pipeline

![CI](https://github.com/Maeva-RODRIGUES/legal-data-pipeline/actions/workflows/ci.yml/badge.svg)

Mini-pipeline de données juridiques : collecte (API + scraping), structuration et contrôle qualité.

## Objectif
- **Bronze** : collecter des décisions de justice depuis l'API Judilibre (Cour de cassation) et une source publique scrapée, stockées brutes dans PostgreSQL.
- **Silver** : les ramener à un schéma commun (dédoublonnage, champs manquants, formats hétérogènes).
- **Qualité** : mesurer l'écart entre ce qui est collecté et ce qui est exploitable.
- **Bonus** : indexation Elasticsearch, API de recherche FastAPI.

## Avancement
- [x] Étape 1a : collecteur Judilibre (pagination, reprises sur erreur, collecte incrémentale, journal des runs), testé sur données réelles ; idempotence vérifiée (relance d'un run : 0 nouveau, 14 inchangés)
- [x] Industrialisation : CI GitHub Actions (ruff + pytest), pre-commit, Dependabot, branche `main` protégée
- [x] Migration de `/export` (déprécié) vers `/scan`, avec `date_type` explicite
- [ ] Étape 1b : scraper d'une source publique
- [ ] Étape 2 : couche Silver
- [ ] Étape 3 : contrôles qualité
- [ ] Étapes 4-5 : Elasticsearch, FastAPI

## Lancer le projet
```bash
cp .env.example .env            # puis renseigner JUDILIBRE_API_KEY
docker compose up -d            # ou : podman compose up -d
pip install -r requirements-dev.txt
pre-commit install
pytest
python -m src.collector.run --start 2026-09-01 --end 2026-09-07
```

Options du collecteur : `--date-type update|creation` (défaut : `update`), `--batch-size` (défaut : 100). Sans `--start`, la collecte reprend après le dernier run réussi du même type de date.

## Méthode de travail
Développé avec l'aide de Claude (IA générative). Les choix de structure, les tests et la vérification des résultats sont faits à la main ; les pièges rencontrés sur chaque source sont notés ci-dessous.

## Pièges des sources

### Judilibre (API PISTE)
Spécification de référence : [`docs/api/`](docs/api/).

**Observé lors du premier run** (15-16 septembre 2026 : 14 décisions collectées) :
- La décision est renvoyée complète (31 champs), texte intégral compris (`text`) et découpage du texte en parties (`zones`) : pas besoin d'un appel supplémentaire par décision.
- `number` et `numbers` coexistent : une décision peut porter sur plusieurs pourvois. Choix à faire en Silver (numéro principal ou liste).
- Chaque date existe en deux versions (`decision_date` / `decision_datetime`, `update_date` / `update_datetime`) : leur cohérence sera à contrôler en Silver.

**D'après la spécification Swagger :**
- `GET /export` est marqué comme déprécié. Son remplaçant, `GET /scan`, accepte les mêmes filtres mais pagine avec un curseur au lieu d'un numéro de lot, ce qui convient mieux aux gros volumes.
- Sans paramètre `jurisdiction`, seules les décisions de la Cour de cassation (`cc`) sont renvoyées ; les cours d'appel (`ca`) et tribunaux judiciaires (`tj`) doivent être demandés explicitement.
- `batch_size` vaut 10 par défaut, 1000 au maximum.
- `GET /transactionalhistory` liste les créations, mises à jour et **suppressions** de décisions : la couche Bronze ne détecte pas encore les décisions retirées.

**Observé lors de la migration vers `/scan` :**
- Le curseur de pagination s'appelle `searchAfter` dans la réponse (et non `search_after` comme dans la documentation) et il est fourni dans `next_batch` sous forme de paramètres d'URL. Le collecteur le renvoie tel quel, sans le reconstruire.
- **La valeur par défaut de `date_type` diffère entre les deux endpoints**, et la documentation ne la précise pas. Sur la même période (15-16/09/2026) :
  - `/export` sans `date_type` : 14 décisions, filtrées sur la **date de décision** (identique à `date_type=creation`) ;
  - `/scan` sans `date_type` : 16 décisions, filtrées sur la **date de mise à jour** (identique à `date_type=update`) ;
  - seules 6 décisions sont communes aux deux ensembles.
- Conséquence : migrer sans `date_type` explicite change silencieusement le périmètre de la collecte. Le collecteur envoie désormais toujours `date_type` (`update` par défaut, pour ne pas manquer les décisions publiées tardivement, dont une rendue en 2021 et mise à jour le 16/09/2026), et le journal des runs l'enregistre.

**Questions ouvertes :**
- Certaines décisions ont un contenu différent selon qu'elles sont obtenues par `/export` ou par `/scan`, ou ont été mises à jour entre deux runs. La couche Bronze écrasant l'ancienne version, la différence ne peut pas être analysée : piste pour une Bronze en append-only (historique des versions).
