"""Moteur d'extraction déclaratif — POC personnel, étape 2.
Lit config/extraction_rules.yaml (pas de regex codée en dur), extrait le
texte de chaque facture PDF (pdfplumber), applique les patterns par champ
et normalise le résultat (dates, montants, SIRET). Ne devine jamais une
valeur manquante : un champ non trouvé reste vide plutôt que rempli par
une valeur par défaut qui masquerait le trou.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pdfplumber
import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "factures_pdf"

MOIS_FR = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
           "juillet": 7, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}

_config_cache = None


def _load_config():
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_DIR / "extraction_rules.yaml", encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


@dataclass
class ChampExtrait:
    nom: str
    valeur_brute: str = None
    valeur: object = None
    trouve: bool = False
    critique: bool = True

    @property
    def manquant_anormal(self):
        """Un champ critique non trouvé est une vraie anomalie d'extraction ;
        un champ non-critique absent (ex. SIRET omis par le fournisseur) ne
        l'est pas — voir extraction_rules.yaml."""
        return self.critique and not self.trouve


def _extraire_champ(texte, nom_champ, config_champ):
    for pattern in config_champ["patterns"]:
        m = re.search(pattern, texte, flags=re.IGNORECASE)
        if m:
            return ChampExtrait(nom=nom_champ, valeur_brute=m.group(1),
                                 trouve=True, critique=config_champ.get("critique", True))
    return ChampExtrait(nom=nom_champ, trouve=False, critique=config_champ.get("critique", True))


def _normaliser_date(valeur_brute):
    if valeur_brute is None:
        return None
    if "/" in valeur_brute:
        return pd.to_datetime(valeur_brute, format="%d/%m/%Y", errors="coerce")
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", valeur_brute)
    if not m:
        return None
    jour, mois_nom, annee = m.groups()
    mois = MOIS_FR.get(mois_nom.lower())
    if mois is None:
        return None
    return pd.Timestamp(year=int(annee), month=mois, day=int(jour))


def _normaliser_montant(valeur_brute):
    if valeur_brute is None:
        return None
    nettoye = valeur_brute.replace(" ", "").replace(",", ".")
    try:
        return float(nettoye)
    except ValueError:
        return None


def _normaliser_siret(valeur_brute):
    if valeur_brute is None:
        return None
    chiffres = re.sub(r"\D", "", valeur_brute)
    return chiffres if len(chiffres) == 14 else None


NORMALISATEURS = {
    "date_facture": _normaliser_date,
    "montant_ht": _normaliser_montant,
    "montant_tva": _normaliser_montant,
    "montant_ttc": _normaliser_montant,
    "taux_tva": _normaliser_montant,
    "siret": _normaliser_siret,
}


def extraire_facture(chemin_pdf):
    config = _load_config()
    with pdfplumber.open(chemin_pdf) as pdf:
        texte = pdf.pages[0].extract_text() or ""

    champs = {}
    for nom_champ, config_champ in config["champs"].items():
        champ = _extraire_champ(texte, nom_champ, config_champ)
        normalisateur = NORMALISATEURS.get(nom_champ)
        champ.valeur = normalisateur(champ.valeur_brute) if normalisateur else champ.valeur_brute
        champs[nom_champ] = champ
    return champs


def champs_to_record(nom_fichier, champs):
    record = {"fichier": nom_fichier}
    for nom_champ, champ in champs.items():
        record[nom_champ] = champ.valeur
        record[f"{nom_champ}_trouve"] = champ.trouve
    record["nb_champs_critiques_manquants"] = sum(
        1 for c in champs.values() if c.manquant_anormal
    )
    return record


def extraire_tous(dossier_pdf=PDF_DIR):
    lignes = []
    for chemin in sorted(dossier_pdf.glob("*.pdf")):
        champs = extraire_facture(chemin)
        lignes.append(champs_to_record(chemin.name, champs))
    return pd.DataFrame(lignes)


def main():
    df = extraire_tous()
    print(f"{len(df)} factures extraites")
    print(f"Factures avec au moins un champ critique manquant : {(df['nb_champs_critiques_manquants'] > 0).sum()}")
    print(f"SIRET non trouvé (attendu, non critique) : {(~df['siret_trouve']).sum()}")
    print(df.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
