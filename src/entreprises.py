"""Ingestion de fournisseurs réels (API Sirene) — POC personnel, étape 1a.
Sert de base réaliste aux factures simulées : chaque "fournisseur" sur une
facture générée est une entreprise réelle (SIREN/SIRET/adresse réels),
même principe que labo-territoire-radar et referentiel-tiers-unique.
"""
import time
from pathlib import Path

import pandas as pd
import requests

API_URL = "https://recherche-entreprises.api.gouv.fr/search"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
CACHE_FILE = RAW_DIR / "fournisseurs_reels.csv"

# Secteurs plausibles comme fournisseurs d'une PME (fournitures, informatique,
# transport, conseil) — volontairement pas un seul secteur, pour ne pas
# recouper labo-territoire-radar (pharma/cosmétique/biotech).
NAF_CIBLES = {
    "46.49B": "Commerce de gros de fournitures de bureau",
    "46.51Z": "Commerce de gros de matériel informatique",
    "49.41A": "Transports routiers de fret",
    "70.22Z": "Conseil pour les affaires et autres conseils de gestion",
}
DEPARTEMENTS = ["75", "69", "33", "44"]


def _requete(naf, departement, per_page=15):
    reponse = requests.get(API_URL, params={
        "activite_principale": naf, "departement": departement, "per_page": per_page,
        "etat_administratif": "A",
    }, timeout=20, headers={"User-Agent": "PortfolioPoC-ExtractionDocuments/1.0"})
    reponse.raise_for_status()
    return reponse.json().get("results", [])


def telecharger_fournisseurs(force=False):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not force and CACHE_FILE.exists():
        return pd.read_csv(CACHE_FILE, dtype=str)

    lignes = []
    for naf, libelle_naf in NAF_CIBLES.items():
        for dept in DEPARTEMENTS:
            try:
                resultats = _requete(naf, dept)
            except requests.RequestException:
                continue
            for r in resultats:
                siege = r.get("siege") or {}
                siret = siege.get("siret", "")
                if not siret or not siege.get("adresse"):
                    continue  # pas de facture crédible sans SIRET ni adresse
                lignes.append({
                    "siren": r.get("siren", ""),
                    "siret": siret,
                    "nom": r.get("nom_raison_sociale") or r.get("nom_complet", ""),
                    "naf": naf,
                    "libelle_naf": libelle_naf,
                    "adresse": siege.get("adresse", ""),
                    "code_postal": siege.get("code_postal", ""),
                    "commune": siege.get("libelle_commune", ""),
                })
            time.sleep(0.2)

    df = pd.DataFrame(lignes).drop_duplicates(subset=["siret"])
    df.to_csv(CACHE_FILE, index=False, encoding="utf-8")
    return df


def main():
    df = telecharger_fournisseurs()
    print(f"{len(df)} fournisseurs réels téléchargés (Sirene) -> {CACHE_FILE}")
    print(df[["nom", "siret", "commune", "libelle_naf"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
