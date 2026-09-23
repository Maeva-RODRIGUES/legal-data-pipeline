# legal-data-pipeline

![CI](https://github.com/Maeva-RODRIGUES/legal-data-pipeline/actions/workflows/ci.yml/badge.svg)

Mini-pipeline de données juridiques : collecte (API + scraping), structuration et contrôle qualité.

## Objectif
- **Bronze** : collecter des décisions de justice depuis l'API Judilibre (Cour de cassation) et une source publique scrapée, stockées brutes dans PostgreSQL.
- **Silver** : les ramener à un schéma commun (dédoublonnage, champs manquants, formats hétérogènes).
- **Qualité** : mesurer l'écart entre ce qui est collecté et ce qui est exploitable.
- **Bonus** : indexation Elasticsearch, API de recherche FastAPI, CI GitHub Actions.

## Avancement
- [x] Étape 1a : collecteur Judilibre (pagination, reprises sur erreur, collecte incrémentale, journal des runs)
- [ ] Étape 1b : scraper d'une source publique
- [ ] Étape 2 : couche Silver
- [ ] Étape 3 : contrôles qualité
- [ ] Étapes 4-5 : Elasticsearch, FastAPI, CI

## Lancer le projet
```bash
cp .env.example .env            # puis renseigner JUDILIBRE_API_KEY
docker compose up -d
pip install -r requirements-dev.txt
pre-commit install
pytest
python -m src.collector.run --start 2026-09-01 --end 2026-09-07
```

## Méthode de travail
Développé avec Claude Code. Les choix de structure et la vérification des résultats sont faits à la main ; les pièges rencontrés sur chaque source sont notés ci-dessous.

## Pièges des sources
_(à compléter au fil du projet)_
