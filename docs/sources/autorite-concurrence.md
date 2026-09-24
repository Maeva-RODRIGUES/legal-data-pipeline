## Jeu de données open data (data.gouv.fr)
- "Décisions publiées par l'Autorité de la Concurrence depuis 1988" : 3 fichiers (texte intégral FR en JSON de 210 Mo, métadonnées en CSV, traductions EN).
- 6683 publications au 23/09/2026 (dont 4054 décisions de concentration, listées séparément sur le site). Hors concentrations : 2629, contre 2602 affichées sur le site (écart à expliquer).
- Le JSON est un unique tableau : lecture en flux avec `ijson` (`use_float=True`, sinon les nombres deviennent des `Decimal` non sérialisables).

### Pièges observés
- `id_decision` n'est pas unique (5 doublons, deux pages pour une même décision) : l'identifiant retenu est `url_site` (6683 valeurs uniques).
- Un identifiant hors format avec un espace final (`C2007/14 `) ; d'autres champs texte ont aussi des espaces parasites.
- Deux formats de listes sous forme de texte : style Python (`['BTP']`) pour secteurs et entreprises, style JSON (`["Avis", "SOA"]`) pour `type_decision`.
- `type_decision` mélange libellés (`Avis`, `Décision`), codes (`DCC`) et listes (type principal + sous-type : `MC`, `DEX`, `SOA`).
- Deux familles de schémas (décisions/avis et concentrations), plus un cas limite ("Lettre du ministre de l'économie", 20 champs, dont `type_operation_concentration_site`).
- Dates en toutes lettres en français (`04 août 2026`) dans le JSON, au format ISO dans le CSV ; types différents entre fichiers (`date_decision_year` texte ou nombre).
- Listes vides (`[]`) plutôt que valeurs manquantes : 919 décisions sans secteur, 1394 sans entreprise.
- Encodage : fichier en UTF-8, mais `Get-Content` (PowerShell) et `open()` (Python sous Windows) lisent par défaut en cp1252. Toujours préciser l'encodage, ou lire en binaire.
