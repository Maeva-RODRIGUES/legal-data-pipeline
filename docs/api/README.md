# Documentation des API sources

Ce dossier concerne les **API externes** interrogées par les collecteurs. L'API du projet (FastAPI) est documentée dans le [README principal](../../README.md#api), dans son contrat ([`docs/tasks/search-api-contract.md`](../tasks/search-api-contract.md)) et, une fois lancée, sur `http://127.0.0.1:8000/docs`.

- `judilibre-swagger-2026-09-23.json` : spécification OpenAPI (Swagger 2.0) de l'API Judilibre,
  téléchargée depuis le portail PISTE le 23/09/2026.
  Copie de référence : la version à jour fait foi sur https://piste.gouv.fr.

Écarts constatés entre cette spécification et le comportement réel de l'API (détails dans le [README principal](../../README.md#judilibre-api-piste)) :
- `GET /export` est marqué comme déprécié, remplacé par `GET /scan` ;
- le curseur de pagination de `/scan` s'appelle `searchAfter` dans la réponse, et non `search_after` ;
- la valeur par défaut de `date_type` n'est pas précisée, et diffère entre `/export` (date de décision) et `/scan` (date de mise à jour).
