"""Mesure de précision de l'extraction — ajouté le 28/08 (piste "rendre le
projet plus utile"). Compare les valeurs extraites (extractor.py) à la
vérité terrain connue, produite par generator.py au moment où il génère les
40 factures PDF (`data/raw/verite_terrain.csv`) — même principe que
rag-connaissances-internes-poc/src/eval.py : un vrai chiffre mesuré sur un
jeu de vérité connue, jamais une estimation.
"""
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
VERITE_TERRAIN_FILE = RAW_DIR / "verite_terrain.csv"

# siret exclu : ~10% des factures ne l'affichent pas du tout, volontairement
# (voir generator.py) — un champ non-critique absent n'est pas une erreur
# d'extraction, le compter fausserait le taux de précision à la baisse.
CHAMPS_COMPARABLES = [
    "numero_facture", "date_facture", "montant_ht", "taux_tva", "montant_tva", "montant_ttc",
]


def _valeurs_egales(champ, extrait, verite):
    if pd.isna(extrait) or verite is None or (isinstance(verite, float) and pd.isna(verite)):
        return False
    if champ == "date_facture":
        return pd.Timestamp(extrait).date() == pd.Timestamp(verite).date()
    if champ == "numero_facture":
        return str(extrait) == str(verite)
    return abs(float(extrait) - float(verite)) < 0.01


def evaluer(df_extrait, verite_terrain=None):
    """df_extrait : sortie de extractor.extraire_tous(). verite_terrain :
    DataFrame optionnel (sinon relu depuis VERITE_TERRAIN_FILE) — permet de
    tester sans dépendre du fichier réel. Retourne (precision_globale_pct,
    precision_par_champ: Series, detail: DataFrame)."""
    if verite_terrain is None:
        verite_terrain = pd.read_csv(VERITE_TERRAIN_FILE, dtype={"numero_facture": str})

    df_extrait = df_extrait.copy()
    df_extrait["numero_facture_doc"] = df_extrait["fichier"].str.replace(".pdf", "", regex=False)

    lignes = []
    for _, ligne_verite in verite_terrain.iterrows():
        correspondance = df_extrait[df_extrait["numero_facture_doc"] == ligne_verite["numero_facture"]]
        if correspondance.empty:
            continue
        ligne_extraite = correspondance.iloc[0]
        for champ in CHAMPS_COMPARABLES:
            correct = _valeurs_egales(champ, ligne_extraite.get(champ), ligne_verite.get(champ))
            lignes.append({"facture": ligne_verite["numero_facture"], "champ": champ, "correct": correct})

    detail = pd.DataFrame(lignes)
    if detail.empty:
        return None, pd.Series(dtype=float), detail

    precision_par_champ = (detail.groupby("champ")["correct"].mean() * 100).round(1)
    precision_globale = round(detail["correct"].mean() * 100, 1)
    return precision_globale, precision_par_champ, detail


def main():
    import extractor
    df_extrait = extractor.extraire_tous()
    precision_globale, precision_par_champ, detail = evaluer(df_extrait)
    print(f"Précision globale : {precision_globale}% ({len(detail)} champs comparés sur {detail['facture'].nunique()} factures)")
    print("\nPar champ :")
    print(precision_par_champ.to_string())
    errones = detail[~detail["correct"]]
    if not errones.empty:
        print(f"\n{len(errones)} champ(s) mal extrait(s) :")
        print(errones.to_string(index=False))


if __name__ == "__main__":
    main()
