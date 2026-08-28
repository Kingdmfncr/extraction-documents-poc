"""Tests unitaires — extraction et contrôle qualité, mêmes principes que
data-quality-pipeline/tests/test_quality.py : petits cas construits à la
main, rapides, isolant une seule règle chacun.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import eval as extraction_eval  # "eval" est un mot réservé Python, alias explicite
import extractor
import quality_check


# ── extractor : normalisation des champs ────────────────────────────────────

def test_normaliser_date_format_chiffres():
    assert extractor._normaliser_date("18/08/2026") == pd.Timestamp("2026-08-18")


def test_normaliser_date_format_texte():
    assert extractor._normaliser_date("3 mars 2026") == pd.Timestamp("2026-03-03")


def test_normaliser_date_texte_mois_inconnu_retourne_none():
    assert extractor._normaliser_date("3 zorblax 2026") is None


def test_normaliser_montant_gere_virgule_et_point():
    assert extractor._normaliser_montant("1 234,56") == 1234.56
    assert extractor._normaliser_montant("1234.56") == 1234.56


def test_normaliser_montant_valeur_invalide_retourne_none():
    assert extractor._normaliser_montant("abc") is None


def test_normaliser_siret_retire_les_espaces():
    assert extractor._normaliser_siret("408 772 960 00022") == "40877296000022"


def test_normaliser_siret_longueur_invalide_retourne_none():
    assert extractor._normaliser_siret("123") is None


def test_extraire_champ_essaie_les_patterns_dans_l_ordre():
    config = {"patterns": [r"Date\s*:\s*(\d{2}/\d{2}/\d{4})", r"Date\s*:\s*(\d{1,2}\s+\w+\s+\d{4})"],
              "critique": True}
    champ = extractor._extraire_champ("Facture X\nDate : 18/08/2026", "date_facture", config)
    assert champ.trouve is True
    assert champ.valeur_brute == "18/08/2026"


def test_extraire_champ_non_trouve_reste_vide_pas_de_valeur_par_defaut():
    config = {"patterns": [r"SIRET\s*:\s*(\d{14})"], "critique": False}
    champ = extractor._extraire_champ("Facture sans SIRET visible", "siret", config)
    assert champ.trouve is False
    assert champ.valeur_brute is None
    assert champ.manquant_anormal is False  # non critique


def test_champ_critique_non_trouve_est_manquant_anormal():
    config = {"patterns": [r"Total HT\s*:\s*([\d.,]+)"], "critique": True}
    champ = extractor._extraire_champ("rien ici", "montant_ht", config)
    assert champ.manquant_anormal is True


# ── quality_check : cohérence métier post-extraction ────────────────────────

def _df_facture(montant_ht=100.0, montant_tva=20.0, montant_ttc=120.0, siret_trouve=True,
                 date_facture="2026-08-01", nb_champs_critiques_manquants=0):
    return pd.DataFrame([{
        "montant_ht": montant_ht, "montant_tva": montant_tva, "montant_ttc": montant_ttc,
        "siret_trouve": siret_trouve, "date_facture": date_facture,
        "nb_champs_critiques_manquants": nb_champs_critiques_manquants,
    }])


def test_controler_coherence_ttc_detecte_un_ecart():
    df = _df_facture(montant_ht=100.0, montant_tva=20.0, montant_ttc=135.0)
    incoherent, ecart = quality_check.controler_coherence_ttc(df)
    assert incoherent.iloc[0] == True
    assert ecart.iloc[0] == pytest.approx(15.0)


def test_controler_coherence_ttc_tolere_l_arrondi_flottant():
    df = _df_facture(montant_ht=33.33, montant_tva=6.67, montant_ttc=40.0)
    incoherent, _ = quality_check.controler_coherence_ttc(df)
    assert incoherent.iloc[0] == False


def test_controler_coherence_ttc_ignore_les_lignes_incompletes():
    df = _df_facture(montant_ht=None, montant_tva=20.0, montant_ttc=120.0)
    incoherent, _ = quality_check.controler_coherence_ttc(df)
    assert incoherent.iloc[0] == False  # pas assez d'info pour juger, pas une fausse anomalie


def test_controler_date_implausible_detecte_le_futur():
    df = _df_facture(date_facture="2027-01-01")
    resultat = quality_check.controler_date_plausible(df, date_reference="2026-08-27")
    assert resultat.iloc[0] == True


def test_controler_date_implausible_accepte_une_date_recente():
    df = _df_facture(date_facture="2026-08-01")
    resultat = quality_check.controler_date_plausible(df, date_reference="2026-08-27")
    assert resultat.iloc[0] == False


def test_executer_controles_statut_ok_si_aucune_anomalie():
    df = _df_facture()
    resultat = quality_check.executer_controles(df, date_reference="2026-08-27")
    assert resultat["statut"].iloc[0] == "OK"


def test_executer_controles_siret_manquant_n_impacte_pas_le_statut_seul():
    """Un SIRET absent (non critique) ne doit pas a lui seul faire basculer
    la facture en 'A VERIFIER' ou 'ANOMALIE' -- affiche separement."""
    df = _df_facture(siret_trouve=False)
    resultat = quality_check.executer_controles(df, date_reference="2026-08-27")
    assert resultat["statut"].iloc[0] == "OK"
    assert resultat["siret_manquant"].iloc[0] == True


def test_executer_controles_cumule_plusieurs_anomalies_vers_anomalie():
    df = _df_facture(montant_ht=100.0, montant_tva=20.0, montant_ttc=999.0, date_facture="2027-01-01")
    resultat = quality_check.executer_controles(df, date_reference="2026-08-27")
    assert resultat["nb_anomalies"].iloc[0] == 2
    assert resultat["statut"].iloc[0] == "ANOMALIE"


# ── confiance par champ (28/08) ──────────────────────────────────────────

def test_confiance_champ_non_trouve_est_nulle():
    champ = extractor.ChampExtrait(nom="x", trouve=False)
    assert champ.confiance == 0.0


def test_confiance_premier_pattern_est_maximale():
    champ = extractor.ChampExtrait(nom="x", valeur_brute="a", valeur="a", trouve=True, rang_pattern=0)
    assert champ.confiance == 1.0


def test_confiance_pattern_de_repli_est_plus_basse():
    premier = extractor.ChampExtrait(nom="x", valeur_brute="a", valeur="a", trouve=True, rang_pattern=0)
    repli = extractor.ChampExtrait(nom="x", valeur_brute="a", valeur="a", trouve=True, rang_pattern=1)
    assert repli.confiance < premier.confiance


def test_confiance_basse_si_normalisation_echoue():
    """Trouvé par regex (valeur_brute non vide) mais non normalisable
    (valeur=None) -- signal de doute réel, pas masqué comme un champ vide."""
    champ = extractor.ChampExtrait(nom="x", valeur_brute="texte illisible", valeur=None, trouve=True, rang_pattern=0)
    assert champ.confiance == 0.3


def test_extraire_champ_enregistre_le_rang_du_pattern_matche():
    config = {"patterns": [r"PREMIER:(\w+)", r"REPLI:(\w+)"]}
    champ = extractor._extraire_champ("REPLI:valeur", "x", config)
    assert champ.trouve is True
    assert champ.rang_pattern == 1


# ── précision globale mesurée (28/08) ────────────────────────────────────

def test_evaluer_compte_correct_quand_extraction_egale_verite():
    df_extrait = pd.DataFrame([{
        "fichier": "FA-2026-0001.pdf", "numero_facture": "FA-2026-0001",
        "date_facture": pd.Timestamp("2026-08-01"), "montant_ht": 100.0,
        "taux_tva": 20.0, "montant_tva": 20.0, "montant_ttc": 120.0,
    }])
    verite = pd.DataFrame([{
        "numero_facture": "FA-2026-0001", "date_facture": "2026-08-01",
        "montant_ht": 100.0, "taux_tva": 20.0, "montant_tva": 20.0, "montant_ttc": 120.0,
    }])
    precision_globale, precision_par_champ, detail = extraction_eval.evaluer(df_extrait, verite)
    assert precision_globale == 100.0
    assert len(detail) == 6  # 6 champs comparables


def test_evaluer_detecte_un_champ_faux():
    df_extrait = pd.DataFrame([{
        "fichier": "FA-2026-0001.pdf", "numero_facture": "FA-2026-0001",
        "date_facture": pd.Timestamp("2026-08-01"), "montant_ht": 100.0,
        "taux_tva": 20.0, "montant_tva": 20.0, "montant_ttc": 999.0,  # faux
    }])
    verite = pd.DataFrame([{
        "numero_facture": "FA-2026-0001", "date_facture": "2026-08-01",
        "montant_ht": 100.0, "taux_tva": 20.0, "montant_tva": 20.0, "montant_ttc": 120.0,
    }])
    precision_globale, precision_par_champ, detail = extraction_eval.evaluer(df_extrait, verite)
    assert precision_globale < 100.0
    assert precision_par_champ["montant_ttc"] == 0.0


def test_evaluer_champ_manquant_nest_jamais_compte_comme_correct():
    df_extrait = pd.DataFrame([{
        "fichier": "FA-2026-0001.pdf", "numero_facture": "FA-2026-0001",
        "date_facture": pd.Timestamp("2026-08-01"), "montant_ht": None,
        "taux_tva": 20.0, "montant_tva": 20.0, "montant_ttc": 120.0,
    }])
    verite = pd.DataFrame([{
        "numero_facture": "FA-2026-0001", "date_facture": "2026-08-01",
        "montant_ht": 100.0, "taux_tva": 20.0, "montant_tva": 20.0, "montant_ttc": 120.0,
    }])
    _, precision_par_champ, _ = extraction_eval.evaluer(df_extrait, verite)
    assert precision_par_champ["montant_ht"] == 0.0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
