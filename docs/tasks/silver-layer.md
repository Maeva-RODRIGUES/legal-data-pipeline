# Task: Silver layer (`src/silver/`)

## Goal
Build a single table `silver.decisions` from two Bronze sources: `judilibre` and `adlc-opendata`.
The `adlc-scraper` source is a freshness monitor, not a content source: it is **not** part of Silver.

## Approach (keep it simple)
- **Full rebuild on every run**: in a single transaction, empty `silver.decisions` and fill it again from Bronze. If anything fails, the previous content stays intact.
- **One pure transform function per source** (Bronze payload in, Silver row out), with no database access, fully unit-tested.
- **Never guess**: a value that cannot be converted becomes `NULL` and is counted as an anomaly. Only a row without an identifier is skipped.
- No deduplication, no merging between sources: duplicates stay visible for the quality step.

## Table
Add migration `sql/003_silver.sql` (schema `silver`, table `decisions`):

| Column | Type | Notes |
|---|---|---|
| `source` | text | primary key with `external_id` |
| `external_id` | text | same identifier as Bronze |
| `decision_number` | text | |
| `issuer` | text | court or authority |
| `decision_type` | text | short controlled vocabulary |
| `decision_date` | date | |
| `title` | text | |
| `text` | text | full text |
| `sectors` | text[] | never NULL, empty array allowed |
| `url` | text | |
| `attributes` | jsonb | never NULL, source-specific fields |
| `built_at` | timestamptz | set at insertion |

## Mapping: `judilibre`
- `decision_number`: first element of `numbers` if it matches `^\d{2}-\d{2}\.\d{3}$`, else `NULL` (anomaly). **Ignore `number`**: it is a corrupted concatenation of all numbers.
- `issuer`: from `jurisdiction`: `cc` → `Cour de cassation`, `ca` → `Cour d'appel`, `tj` → `Tribunal judiciaire`; unknown → `NULL` (anomaly).
- `decision_type`: `NULL` (the source `type` is `other` for every decision); keep the raw value in `attributes.judilibre_type`.
- `decision_date`: `decision_date` (ISO date); invalid → `NULL` (anomaly).
- `title`: `NULL` (no title in the source; `summary` is often empty).
- `text`: `text`.
- `sectors`: empty array.
- `url`: `https://www.courdecassation.fr/decision/{id}` (format verified on 25/09/2026 with decision 19-24.008).
- `attributes`: `ecli`, `numbers` (deduplicated, order preserved), `chamber`, `formation`, `solution`, `publication`, `themes`, `summary` (only if not empty), `update_date`, `judilibre_type`.

## Mapping: `adlc-opendata`
- `decision_number`: `id_decision`, stripped of surrounding spaces.
- `issuer`: `Autorité de la concurrence`.
- `decision_type` and `attributes.subtypes`, from `type_decision`:
  - if the value starts with `[`, parse it as JSON: first element is the main type, the others are subtypes;
  - main type mapping: `Décision` → `decision`, `Avis` → `avis`, `DCC` → `concentration`, `Lettre du minsitre de l'économie` (typo is in the source) → `lettre_ministre`;
  - any other value → `NULL` (anomaly). Never map an unknown value to a known type.
- `decision_date`: `date_decision_datetime` (already ISO). Do not parse the French text date `date_decision`.
- `title`: `titre_decision`, stripped.
- `text`: `texte_complet_decision`.
- `sectors`: `secteur_activite` is a Python literal list (`"['BTP']"`): parse it with `ast.literal_eval`, strip each item; malformed → empty array (anomaly).
- `url`: `url_site`, stripped.
- `attributes`: every other field as-is, except:
  - `entreprises_concernees`: parsed like `secteur_activite`;
  - `decision_simplifiee`: `Oui` → `true`, `Non` → `false`;
  - string values stripped of surrounding spaces;
  - plus `subtypes` (list, possibly empty).

## Run script
- `python -m src.silver.run`: full rebuild, logged in `bronze.collection_runs` (source `silver`, `date_type` = `rebuild`, date of the day).
- Print the number of rows written per source and the number of anomalies per type (e.g. `unknown_decision_type`, `invalid_decision_number`, `malformed_sectors`).
- Read Bronze with a server-side cursor or in batches: the `adlc-opendata` payloads are large.

## Tests (no database, no network)
- Judilibre: the corrupted `number` is ignored; `numbers` with duplicates gives the right `decision_number` and a deduplicated list; unknown jurisdiction gives `NULL`.
- ADLC: each of the 7 known `type_decision` values; an unknown value gives `NULL` and an anomaly; sectors parsing; `decision_simplifiee`; spaces stripped in `id_decision` (e.g. `C2007/14 `).

## Acceptance criteria
- `pytest` and `pre-commit run --all-files` pass.
- A real run writes one Silver row per Bronze row of the two sources (24 for `judilibre` and 6683 for `adlc-opendata` on the current database).
- Two consecutive runs give the same row counts.

## Deliverable
A `feat/silver-layer` branch with separate commits. Do not merge it, do not push it.
