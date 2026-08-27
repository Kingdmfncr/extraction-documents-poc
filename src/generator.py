"""Génération de factures fournisseurs simulées mais réalistes — POC
personnel, étape 1b. Le fournisseur de chaque facture est une entreprise
réelle (voir entreprises.py, API Sirene) ; le contenu de la facture
(numéro, lignes, montants) est simulé, seed fixe pour reproductibilité.

3 familles de variation contrôlée, injectées volontairement pour que le
moteur d'extraction (étape 2) ait un vrai problème à résoudre, pas un cas
d'école :
1. Format de date variable (chiffres vs texte) — les fournisseurs n'ont pas
   tous le même logiciel de facturation.
2. SIRET avec ou sans espaces, TVA/TTC avec libellé variable — bruit
   typographique réaliste, pas une erreur de fond.
3. Incohérence de calcul (montant_ttc != ht + tva) sur une minorité de
   factures — erreur de saisie fournisseur réelle, pas une faute
   d'extraction : le contrôle qualité (étape 3) doit la détecter.
"""
import random
from pathlib import Path

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "factures_pdf"

SEED = 42
DATE_REFERENCE = pd.Timestamp("2026-08-27")

ARTICLES = [
    ("Prestation de conseil (jour)", 450.0), ("Licence logicielle annuelle", 1200.0),
    ("Ordinateur portable professionnel", 890.0), ("Fournitures de bureau (lot)", 65.0),
    ("Transport routier (forfait)", 320.0), ("Maintenance informatique (heure)", 75.0),
    ("Abonnement cloud mensuel", 149.0), ("Cartouches d'impression (lot)", 42.0),
]
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"]


def _formater_date(date, style):
    if style == "chiffres":
        return date.strftime("%d/%m/%Y")
    return f"{date.day} {MOIS_FR[date.month - 1]} {date.year}"


def _formater_siret(siret, avec_espaces):
    if not avec_espaces:
        return siret
    return f"{siret[0:3]} {siret[3:6]} {siret[6:9]} {siret[9:14]}"


def _generer_lignes(rng):
    n = rng.randint(1, 4)
    choisis = rng.sample(ARTICLES, k=n)
    lignes = []
    for designation, prix_unitaire in choisis:
        quantite = rng.randint(1, 6)
        lignes.append({"designation": designation, "quantite": quantite,
                        "prix_unitaire_ht": prix_unitaire})
    return lignes


def generer_factures(n=40, seed=SEED):
    """Retourne un DataFrame (1 ligne = 1 facture, champs structurés =
    vérité terrain) et une liste de dicts détaillés (avec lignes) pour le
    rendu PDF. La vérité terrain sert à évaluer l'extraction à l'étape 2."""
    rng = random.Random(seed)
    fournisseurs = pd.read_csv(RAW_DIR / "fournisseurs_reels.csv", dtype=str)
    fournisseurs = fournisseurs.dropna(subset=["commune"]).reset_index(drop=True)

    factures = []
    for i in range(n):
        fournisseur = fournisseurs.iloc[rng.randrange(len(fournisseurs))]
        lignes = _generer_lignes(rng)
        montant_ht = round(sum(l["quantite"] * l["prix_unitaire_ht"] for l in lignes), 2)
        taux_tva = rng.choice([20.0, 20.0, 20.0, 10.0, 5.5])  # 20% trois fois plus frequent, realiste
        montant_tva = round(montant_ht * taux_tva / 100, 2)
        montant_ttc = round(montant_ht + montant_tva, 2)

        # Famille d'anomalie 3 : ~12% des factures ont une incoherence de calcul
        # (erreur de saisie fournisseur), volontairement APRES calcul du TTC "vrai"
        # pour que le contrôle qualité ait quelque chose de reel a detecter.
        incoherente = rng.random() < 0.12
        montant_ttc_facture = round(montant_ttc + rng.choice([-15.0, 10.0, 25.0]), 2) if incoherente else montant_ttc

        date_facture = DATE_REFERENCE - pd.Timedelta(days=rng.randint(1, 60))
        style_date = rng.choice(["chiffres", "texte"])
        siret_avec_espaces = rng.random() < 0.5
        libelle_ttc = rng.choice(["Total TTC", "Net à payer", "Montant total TTC"])
        # Famille d'anomalie 2b : ~10% des factures n'affichent pas le SIRET du tout
        # (fournisseur qui l'a omis) -> champ non extractible, pas une erreur d'extraction.
        siret_absent = rng.random() < 0.10

        numero_facture = f"FA-2026-{i + 1:04d}"
        factures.append({
            "numero_facture": numero_facture,
            "date_facture": date_facture.strftime("%Y-%m-%d"),
            "fournisseur_nom": fournisseur["nom"],
            "fournisseur_siret": fournisseur["siret"],
            "fournisseur_siret_present_sur_doc": not siret_absent,
            "montant_ht": montant_ht,
            "taux_tva": taux_tva,
            "montant_tva": montant_tva,
            "montant_ttc": montant_ttc_facture,
            "montant_ttc_theorique": montant_ttc,
            "incoherence_injectee": incoherente,
            "rendu": {
                "date_str": _formater_date(date_facture, style_date),
                "siret_str": _formater_siret(fournisseur["siret"], siret_avec_espaces) if not siret_absent else None,
                "adresse": fournisseur["adresse"], "commune": fournisseur["commune"],
                "code_postal": fournisseur["code_postal"], "libelle_ttc": libelle_ttc,
                "lignes": lignes,
            },
        })
    return factures


def rendre_pdf(facture, chemin):
    r = facture["rendu"]
    c = canvas.Canvas(str(chemin), pagesize=A4)
    largeur, hauteur = A4
    y = hauteur - 25 * mm

    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, y, facture["fournisseur_nom"])
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, r["adresse"])
    y -= 5 * mm
    c.drawString(20 * mm, y, f"{r['code_postal']} {r['commune']}")
    y -= 5 * mm
    if r["siret_str"]:
        c.drawString(20 * mm, y, f"SIRET : {r['siret_str']}")
        y -= 5 * mm

    y -= 8 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, y, f"Facture {facture['numero_facture']}")
    c.setFont("Helvetica", 9)
    c.drawString(140 * mm, y, f"Date : {r['date_str']}")
    y -= 12 * mm

    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "Désignation")
    c.drawString(120 * mm, y, "Qté")
    c.drawString(140 * mm, y, "PU HT")
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    for ligne in r["lignes"]:
        c.drawString(20 * mm, y, ligne["designation"])
        c.drawString(120 * mm, y, str(ligne["quantite"]))
        c.drawString(140 * mm, y, f"{ligne['prix_unitaire_ht']:.2f} EUR")
        y -= 5 * mm

    y -= 8 * mm
    c.setFont("Helvetica", 9)
    c.drawString(120 * mm, y, f"Total HT : {facture['montant_ht']:.2f} EUR")
    y -= 5 * mm
    c.drawString(120 * mm, y, f"TVA ({facture['taux_tva']:.1f}%) : {facture['montant_tva']:.2f} EUR")
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(120 * mm, y, f"{r['libelle_ttc']} : {facture['montant_ttc']:.2f} EUR")

    c.showPage()
    c.save()


def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    factures = generer_factures()
    verite_terrain = []
    for f in factures:
        rendre_pdf(f, PDF_DIR / f"{f['numero_facture']}.pdf")
        ligne = {k: v for k, v in f.items() if k != "rendu"}
        verite_terrain.append(ligne)

    df = pd.DataFrame(verite_terrain)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RAW_DIR / "verite_terrain.csv", index=False, encoding="utf-8")
    print(f"{len(df)} factures PDF générées -> {PDF_DIR}")
    print(f"Vérité terrain -> {RAW_DIR / 'verite_terrain.csv'}")
    print(f"Incohérences de calcul injectées : {df['incoherence_injectee'].sum()}")
    print(f"SIRET absent du document : {(~df['fournisseur_siret_present_sur_doc']).sum()}")


if __name__ == "__main__":
    main()
