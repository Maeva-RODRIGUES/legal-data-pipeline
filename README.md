# legal-data-pipeline

![CI](https://github.com/Maeva-RODRIGUES/legal-data-pipeline/actions/workflows/ci.yml/badge.svg)

Mini-pipeline de données juridiques : collecte multi-sources (API, open data, scraping), structuration et contrôle qualité.

## Objectif
- **Bronze** : collecter des décisions de justice et d'autorités administratives, stockées brutes dans PostgreSQL :
  - API Judilibre (Cour de cassation) ;
  - jeu de données open data de l'Autorité de la concurrence (data.gouv.fr) ;
  - scraper du site de l'Autorité de la concurrence, pour détecter les décisions pas encore publiées en open data.
- **Silver** : les ramener à un schéma commun (dédoublonnage, champs manquants, formats hétérogènes).
- **Qualité** : mesurer l'écart entre ce qui est collecté et ce qui est exploitable.
- **Bonus** : indexation Elasticsearch, API de recherche FastAPI.

## Avancement
- [x] Étape 1a : collecteur Judilibre (pagination, reprises sur erreur, collecte incrémentale, journal des runs), testé sur données réelles ; idempotence vérifiée (relance d'un run : 0 nouveau, 14 inchangés)
- [x] Industrialisation : CI GitHub Actions (ruff + pytest), pre-commit, Dependabot, branche `main` protégée
- [x] Migration de `/export` (déprécié) vers `/scan`, avec `date_type` explicite
- [x] Étape 1b : ingestion du jeu de données open data de l'Autorité de la concurrence (6683 décisions, lecture en flux d'un JSON de 210 Mo, idempotence vérifiée)
- [ ] Étape 1c : scraper de fraîcheur du site de l'Autorité de la concurrence
- [ ] Étape 1d : planification des collecteurs avec Celery et Redis (Celery Beat)
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
python -m src.collector.run_adlc                 # fichier local : data/raw/adlc-texte-complet-publications.json
python -m src.collector.run_adlc --url <URL>     # ou téléchargement préalable depuis data.gouv.fr
```
Le dossier `data/` est ignoré par Git : les fichiers sources sont téléchargés, jamais versionnés.

Options du collecteur : `--date-type update|creation` (défaut : `update`), `--batch-size` (défaut : 100). Sans `--start`, la collecte reprend après le dernier run réussi du même type de date.

## Méthode de travail
Le projet est développé avec l'aide de l'IA générative, selon deux modes :

- **Assistance conversationnelle (Claude)** : explications, discussions de conception, premières versions de code que je relis, adapte et teste.
- **Délégation à un agent (Claude Code)**, à partir du scraper de fraîcheur : je rédige une spécification (contexte, contraintes, critères de réussite) dans [`docs/tasks/`](docs/tasks/), l'agent produit le code et les tests sur une branche, et je valide avant toute fusion. Les conventions données à l'agent sont dans [`CLAUDE.md`](CLAUDE.md).

**Ce qui reste de mon ressort :**
- l'analyse de chaque source (documentation, `robots.txt`, structure des données) et les choix de conception qui en découlent ;
- la relecture du code, les runs sur données réelles et la vérification des résultats ;
- la documentation des pièges rencontrés, notés ci-dessous.

Chaque pull request précise ce qui a été délégué et ce que j'ai fait ou corrigé moi-même.

> [!IMPORTANT]
> **Pourquoi ne pas tout automatiser ?**
> J'aurais pu confier l'ensemble du projet à Claude Code, en lui faisant rédiger un plan d'implémentation (par exemple avec les skills Superpowers) puis l'exécuter de bout en bout. J'ai fait le choix inverse : **garder la main sur chaque étape**, pour comprendre ce qui est construit, prendre moi-même les décisions liées aux sources et pouvoir expliquer chaque ligne de code. La délégation à un agent vient ensuite, progressivement, sur des tâches dont je maîtrise le contexte et que je sais vérifier.
>
> **Ce que cette approche a permis de trouver :**
> - la route `/export` de l'API Judilibre était **dépréciée**, alors que rien ne le signalait à l'exécution ;
> - la valeur par défaut de `date_type` **changeait silencieusement** entre `/export` et `/scan` : sur une même période, seules 6 décisions étaient communes aux deux routes ;
> - une décision peut être **modifiée sans que sa date de mise à jour change**, ce que seule la comparaison des empreintes a détecté.

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
- Le contenu d'une décision peut changer **sans que sa date de mise à jour change** : observé le 24/09/2026 sur une décision datée du 15/09, dont le contenu renvoyé par `/scan` avait été modifié. Seule la comparaison des empreintes (hash du contenu complet) l'a détecté ; une détection fondée sur `update_date` l'aurait manqué.
- Une décision peut sortir d'une fenêtre de collecte après coup, si elle est remise à jour : un run relancé sur une période passée ne renvoie pas toujours le même ensemble. La collecte incrémentale la récupère dans la fenêtre de sa nouvelle date de mise à jour.

### Autorité de la concurrence (open data)
Documentation détaillée : [`docs/sources/autorite-concurrence.md`](docs/sources/autorite-concurrence.md).

- `id_decision` n'est pas unique (5 doublons) : l'identifiant retenu est l'URL de la décision. Vérifié en base : 6683 documents pour 6678 `id_decision` distincts.
- `type_decision` mélange libellés, codes et listes (type principal + sous-type), et les listes apparaissent sous deux formats différents (style Python et style JSON).
- Deux familles de schémas (décisions/avis et concentrations), plus un cas limite à 20 champs : il faudra un tronc commun et des attributs propres en Silver.
- Le `robots.txt` du site interdit toutes les URL avec paramètres, dont la pagination de la liste : l'historique vient donc de l'open data, et le scraper se limite à la première page et aux pages de détail.
