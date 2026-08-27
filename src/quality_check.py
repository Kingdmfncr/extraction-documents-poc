"""Contrôle qualité post-extraction — POC personnel, étape 3.
Une extraction qui « réussit » techniquement (tous les champs trouvés) peut
quand même porter une facture fausse (erreur de calcul du fournisseur) :
ce module vérifie la cohérence métier des valeurs extraites, pas juste leur
présence. Distinction volontaire avec extractor.py : ce dernier détecte les
trous d'extraction, celui-ci détecte les incohérences dans ce qui a été
extrait avec succès — même logique de séparation des responsabilités que
quality_engine.py / anonymizer.py sur data-quality-pipeline.
"""
import pandas as pd

TOLERANCE_EUR = 0.02  # arrondi flottant, pas un seuil de tolerance metier


def controler_coherence_ttc(df):
    """montant_ttc doit egaler montant_ht + montant_tva, a l'arrondi pres.
    Ne s'applique qu'aux lignes ou les 3 montants ont ete extraits."""
    montants_complets = df[["montant_ht", "montant_tva", "montant_ttc"]].notna().all(axis=1)
    ht = pd.to_numeric(df["montant_ht"], errors="coerce").fillna(0)
    tva = pd.to_numeric(df["montant_tva"], errors="coerce").fillna(0)
    ttc = pd.to_numeric(df["montant_ttc"], errors="coerce").fillna(0)
    ecart = (ht + tva - ttc).abs()
    incoherent = montants_complets & (ecart > TOLERANCE_EUR)
    return incoherent, ecart


def controler_siret_present(df):
    """Champ non-critique par design (extractor.py) : signale au Data Owner
    qu'une verification manuelle est necessaire, sans jamais bloquer le
    traitement de la facture pour autant."""
    return ~df["siret_trouve"].fillna(False)


def controler_date_plausible(df, date_reference):
    date_reference = pd.Timestamp(date_reference)
    dates = pd.to_datetime(df["date_facture"], errors="coerce")
    dans_le_futur = dates.notna() & (dates > date_reference)
    trop_ancienne = dates.notna() & (dates < date_reference - pd.Timedelta(days=365))
    return dans_le_futur | trop_ancienne


def controler_montants_positifs(df):
    colonnes = ["montant_ht", "montant_tva", "montant_ttc"]
    return (df[colonnes].fillna(0) < 0).any(axis=1)


def executer_controles(df, date_reference):
    """Retourne le DataFrame enrichi de colonnes booleennes d'ecart (jamais
    de filtrage silencieux) et d'un statut de synthese par facture."""
    df = df.copy()
    incoherence_ttc, ecart_ttc = controler_coherence_ttc(df)
    df["ecart_ttc_incoherent"] = incoherence_ttc
    df["ecart_ttc_montant"] = ecart_ttc.round(2)
    df["siret_manquant"] = controler_siret_present(df)
    df["date_implausible"] = controler_date_plausible(df, date_reference)
    df["montant_negatif"] = controler_montants_positifs(df)

    df["nb_anomalies"] = (
        df["ecart_ttc_incoherent"].astype(int)
        + df["date_implausible"].astype(int)
        + df["montant_negatif"].astype(int)
        + df["nb_champs_critiques_manquants"].fillna(0).astype(int)
    )
    # siret_manquant volontairement exclu de nb_anomalies : non-critique par design,
    # affiche separement pour ne pas gonfler artificiellement le taux d'anomalie.
    df["statut"] = df["nb_anomalies"].apply(
        lambda n: "OK" if n == 0 else ("A VERIFIER" if n <= 1 else "ANOMALIE")
    )
    return df


def resumer(df):
    return {
        "Factures traitees": len(df),
        "OK": int((df["statut"] == "OK").sum()),
        "A verifier": int((df["statut"] == "A VERIFIER").sum()),
        "Anomalie": int((df["statut"] == "ANOMALIE").sum()),
        "SIRET manquant (info)": int(df["siret_manquant"].sum()),
    }


def main():
    import extractor
    df = extractor.extraire_tous()
    df = executer_controles(df, date_reference="2026-08-27")
    resume = resumer(df)
    for cle, valeur in resume.items():
        print(f"{cle} : {valeur}")
    print("\nFactures avec incoherence TTC :")
    print(df[df["ecart_ttc_incoherent"]][["fichier", "montant_ht", "montant_tva", "montant_ttc", "ecart_ttc_montant"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
