# PROMPT LOG — Comment j'ai construit ce projet avec l'IA

> Ce fichier documente ma méthode de travail réelle avec l'IA (Claude), même principe que `data-quality-pipeline/PROMPT_LOG.md`.

---

## Contexte de départ

Deuxième projet du chantier "montée en compétences" (`Freelancing/05_Portfolio_Technique/CONTEXTE_MONTEE_COMPETENCES.md`). Avant de construire quoi que ce soit, vérification des 30+ repos déjà existants dans `Portfolio_GitHub/` : aucun ne traite l'extraction de documents (facture/contrat), confirmé neuf. Au passage, découverte que `referentiel-tiers-unique` (construit le 2026-08-25, absent de l'audit stratégique du 2026-08-12) couvre déjà l'idée "MDM référentiel Clients/Produits (golden record)" du backlog — noté pour corriger le fichier de suivi, pas construit ici.

## Étape 1 — Fournisseurs réels & génération de factures

Réutilisation directe du pattern Sirene déjà éprouvé sur `labo-territoire-radar` (`recherche-entreprises.api.gouv.fr`, sans clé). Vérification en direct de la structure de réponse de l'API avant d'écrire le moindre code de parsing (règle de `METHODE_PORTFOLIO_PROJETS_CIBLES.md`) : le SIRET est dans `siege.siret`, pas dans le résultat racine — confirmé par un appel réel avant d'écrire `entreprises.py`.

**Décision volontaire** : 3 familles de variation contrôlée injectées dans les factures générées (format de date texte vs chiffres, SIRET avec/sans espaces, ~12% d'incohérences de calcul TTC, ~10% de SIRET omis du document) — sans ça, l'extraction n'aurait rien de réel à résoudre, juste des documents parfaitement uniformes.

**Point de vigilance repéré en testant, pas corrigé** : le champ `adresse` retourné par l'API Sirene inclut déjà le code postal et la ville (`"615 AVENUE DE LA CHAFFINE 13160 CHATEAURENARD"`), donc l'affichage PDF actuel les répète une deuxième fois. Cosmétique, n'affecte aucun champ extrait (numéro, date, SIRET, montants), laissé tel quel pour ce POC.

## Étape 2 — Moteur d'extraction déclaratif

**Bug d'environnement trouvé avant même d'écrire le code** : la dernière version de `pdfplumber` exige `Pillow>=12.2.0`, indisponible pour Python 3.9 (l'environnement de ce poste). Épinglé `pdfplumber==0.10.3` dans `requirements.txt` après avoir vérifié que cette version s'installe et fonctionne réellement, plutôt que de deviner une version compatible.

Même principe que `quality_engine.py` sur `data-quality-pipeline` : patterns regex déclarés en YAML, pas codés en dur, essayés dans l'ordre jusqu'au premier match (gère les 2 formats de date sans branche de code dédiée par format). Un champ non trouvé reste `None` — jamais une valeur par défaut qui masquerait un vrai trou.

## Étape 3 — Contrôle qualité métier

Distinction volontaire du moteur d'extraction : un champ peut être extrait avec succès et quand même être faux (facture incohérente). `controler_coherence_ttc()` ignore les lignes où un montant manque (pas assez d'information pour juger, pas une fausse anomalie) plutôt que de traiter une valeur manquante comme 0 et générer un faux positif.

**Bug trouvé en testant** : `FutureWarning` de pandas sur `.fillna()` appliqué à une colonne object (mélange de `float` et de `None`) dans `controler_coherence_ttc`. Corrigé en forçant explicitement `pd.to_numeric()` avant le calcul d'écart, avec un test dédié (`test_controler_coherence_ttc_ignore_les_lignes_incompletes`) qui couvre justement ce cas de colonne incomplète.

## Étape 4 — Dashboard

Repris du même design (palette, structure sidebar/onglets/KPI) que `data-quality-pipeline`, pour cohérence visuelle du portfolio. 4 onglets : vue d'ensemble, file de vérification, détail complet, transparence sur les règles déclarées. Le pipeline (fournisseurs → génération PDF → extraction → contrôle) est rejoué en mémoire à chaque lancement (`@st.cache_data`), avec génération des PDF uniquement si absents du dossier — évite de re-générer 40 PDF à chaque rerun en développement local.

## Étape 5 — Upload réel, score de confiance, précision mesurée (2026-08-28)

Trois pistes retenues pour rendre le projet plus utile (même méthode que le projet fertilité) :

1. **Score de confiance par champ** (`ChampExtrait.confiance`, `extractor.py`) : jamais un pourcentage inventé, dérivé de 2 signaux réels du pipeline — quel pattern a matché (le premier déclaré dans `extraction_rules.yaml` est censé être le plus fiable) et si la normalisation a réussi à interpréter le texte trouvé. **Trou détecté en construisant cette fonctionnalité** : un champ trouvé par regex mais dont la normalisation échoue (`_normaliser_montant` retourne `None` sur un texte illisible) avait `trouve=True` et `valeur=None` sans que ce cas soit distingué d'un simple champ vide — silencieusement faux plutôt qu'incertain. Corrigé en donnant à ce cas une confiance basse (0.3) explicite plutôt qu'une valeur vide muette.
2. **Upload d'une vraie facture** (nouvel onglet du dashboard, `st.file_uploader`) : extraction en direct sur le fichier déposé par l'utilisateur, avec le même moteur que les 40 factures de démo. Testé avec une vraie facture PDF (une des factures générées, envoyée comme si elle venait d'un utilisateur externe) : extraction correcte des 7 champs, confiance 1.00 partout, statut OK.
3. **Mesure de précision globale** (`src/eval.py`, même principe que `rag-connaissances-internes-poc/src/eval.py`) : compare chaque champ extrait à la vérité terrain connue (`data/raw/verite_terrain.csv`, produite par le générateur au moment de créer les factures). SIRET exclu de la mesure : ~10% des factures ne l'affichent pas du tout par construction (non-critique), le compter aurait faussé le taux à la baisse pour un cas qui n'est pas une erreur d'extraction.

**Résultat honnête, pas caché** : précision mesurée à 100% sur les 40 factures de démo — attendu, puisque les regex de `extraction_rules.yaml` ont été calées sur les formats mêmes que le générateur produit. La vraie valeur du chiffre se voit sur l'onglet upload, avec un document dont le format n'a pas été vu à l'avance.

**Vérifié dans le navigateur** : chargement du dashboard, section précision affichée (100%, détail par champ), upload d'une facture réelle testé de bout en bout (drag&drop simulé via l'API File du navigateur, pas seulement `extractor.extraire_facture()` appelé en Python), badges de confiance corrects, aucune erreur console. 8 tests Pytest supplémentaires (18 → 26 au total).

---

## Ce que ce projet prouve (pour un client ou un recruteur)

| Compétence démontrée | Preuve dans ce projet |
|---|---|
| Extraction structurée de documents non structurés | Moteur déclaratif YAML, gère 3 familles de variation de format sans code dédié par cas |
| Distinction trou d'extraction vs incohérence métier | Deux modules séparés (`extractor.py` / `quality_check.py`), jamais mélangés dans un seul indicateur |
| Rigueur méthodologique | Bug d'environnement (Pillow/pdfplumber) résolu par vérification réelle, pas supposition ; FutureWarning pandas trouvé et corrigé avec test dédié |
| Vérification, pas confiance aveugle | Chaque étape testée en local et dans le navigateur avant de passer à la suivante ; dédoublonnage contre le portfolio existant avant de commencer à coder |
| Fiabilité mesurée, pas déclarée | Étape 5 : précision d'extraction mesurée contre une vérité terrain connue, score de confiance par champ dérivé de signaux réels du pipeline, upload d'un vrai document externe testé |

---

## Ma conclusion

> La partie la plus utile de ce projet n'est pas le regex qui trouve un montant, c'est la décision de séparer "je n'ai pas trouvé ce champ" de "j'ai trouvé ce champ mais il ne colle pas avec les autres" — ce sont deux problèmes différents avec des correctifs différents, et les confondre dans un seul score de qualité aurait caché lequel des deux se passe vraiment sur chaque facture.

*Gisèle Metouck — Consultante Data Steward & Gouvernance*
