## Jeu de données open data (data.gouv.fr)
- "Décisions publiées par l'Autorité de la Concurrence depuis 1988" : 3 fichiers (texte intégral FR en JSON de 210 Mo, métadonnées en CSV, traductions EN).
- 6683 publications au 23/09/2026 (dont 4054 décisions de concentration, listées séparément sur le site). Hors concentrations : 2629, contre 2602 affichées sur le site (écart à expliquer).
- Le JSON est un unique tableau : lecture en flux avec `ijson` (`use_float=True`, sinon les nombres deviennent des `Decimal` non sérialisables).

### Pièges observés
- `id_decision` n'est pas unique (5 doublons, deux pages pour une même décision) : l'identifiant retenu est `url_site` (6683 valeurs uniques). À l'inverse, le suffixe `-0` d'une URL ne signale pas toujours un doublon : `26-D-06` et `26-D-07` ont le même titre, et Drupal a simplement ajouté `-0` à l'adresse de la seconde.
- Un identifiant hors format avec un espace final (`C2007/14 `) ; d'autres champs texte ont aussi des espaces parasites.
- Les listes n'ont pas la même forme selon le fichier : **texte au format Python** dans le CSV (`"['BTP']"`), mais **vraies listes JSON** dans le JSON. Vérifié dans le Bronze avec `jsonb_typeof` : `secteur_activite` et `entreprises_concernees` sont des tableaux pour les 6683 décisions ; `type_decision` est une chaîne pour 6479 décisions et un tableau pour 204.
- Piège d'exploration : `str()` en Python et l'opérateur `->>` de PostgreSQL affichent une vraie liste comme du texte. Une première version de la spécification Silver s'y est trompée (6683 anomalies au premier run réel) : pour connaître le type d'un champ, utiliser `jsonb_typeof`, pas l'affichage.
- `type_decision` mélange libellés (`Avis`, `Décision`), codes (`DCC`) et listes (type principal + sous-type : `MC`, `DEX`, `SOA`).
- Deux familles de schémas (décisions/avis et concentrations), plus un cas limite ("Lettre du minsitre de l'économie", avec cette faute de frappe dans le libellé, 20 champs, dont `type_operation_concentration_site`).
- Dates : le JSON contient à la fois une date en toutes lettres en français (`date_decision` : `04 août 2026`) et une date ISO (`date_decision_datetime` : `2026-08-04`). La couche Silver utilise la date ISO. Types différents entre fichiers (`date_decision_year` texte dans le JSON, nombre dans le CSV).
- Listes vides (`[]`) plutôt que valeurs manquantes : 919 décisions sans secteur, 1394 sans entreprise.
- Encodage : fichier en UTF-8, mais `Get-Content` (PowerShell) et `open()` (Python sous Windows) lisent par défaut en cp1252. Toujours préciser l'encodage, ou lire en binaire.
- `decision_simplifiee` vaut `null` pour 28 décisions : 27 des 28 décisions `DEX` et la lettre du ministre. Une seule décision `DEX` a une valeur. Ce n'est donc pas une règle stricte : le Silver garde `null` dans `attributes`, sans anomalie.
- **Deux apostrophes coexistent dans les titres** : typographique (`l’électricité`, par exemple `12-A-19`) et droite (`l'électricité`, par exemple `13-A-25`). Vérifié avec `_analyze` : l'analyseur `french_folded` de l'index les traite de la même façon (les deux donnent le terme `electricit`), la recherche n'est donc pas affectée. À garder en tête pour toute comparaison de titres hors de l'index (en SQL, par exemple).

### Observé lors des contrôles qualité (25/09/2026)
- **30 décisions sans texte intégral** (chaîne vide, pas `NULL`), donc impossibles à retrouver par une recherche dans le contenu : 21 décisions de concentration, dont 8 datées de 2026, et 9 avis et décisions des années 1990 et 2000, plus la lettre du ministre. Hypothèses à vérifier sur le site : une version publique pas encore publiée pour les concentrations récentes, des PDF numérisés sans texte extrait pour les documents anciens.
- **Numérotation et dates** : la numérotation d'une année se prolonge sur les premiers mois de l'année suivante (39 décisions, par exemple `00-D-68` à `00-D-92`, datées de janvier à mars 2001). Ce n'est pas une erreur. En revanche, **3 décisions ont une date impossible**, antérieure à l'année de leur numéro : `95-MC-06` (1990), `95-D-26` (1992) et `96-D-03` (1995). Probable erreur de saisie dans la date, à confirmer sur le site.
