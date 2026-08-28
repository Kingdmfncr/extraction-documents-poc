"""Extraction Structurée de Documents Métier — POC personnel.
Factures fournisseurs simulées (fournisseurs réels via API Sirene) ->
moteur d'extraction déclaratif (YAML, pas de regex codée en dur) ->
contrôle qualité métier (cohérence TTC, plausibilité) -> file de
vérification pour un Data Steward.
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "factures_pdf"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
sys.path.insert(0, str(SRC_DIR))

import entreprises
import eval as extraction_eval  # "eval" est un mot réservé Python, alias explicite
import extractor
import generator
import quality_check

C_PRIMARY = "#0071E3"
C_GOOD    = "#34C759"
C_WARNING = "#FF9F0A"
C_DANGER  = "#FF3B30"
C_SURF    = "#F5F5F7"
C_TEXT    = "#1D1D1F"
C_MUTED   = "#6E6E73"
C_BORDER  = "#E8E8ED"

STATUT_COLORS = {"OK": C_GOOD, "A VERIFIER": C_WARNING, "ANOMALIE": C_DANGER}
DATE_REFERENCE = "2026-08-27"

CHART_DEFAULTS = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=C_TEXT, family="Inter, -apple-system, sans-serif", size=13),
    margin=dict(l=20, r=20, t=40, b=20),
)

st.set_page_config(page_title="Extraction Documents Métier", page_icon="📄",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
html, body, [class*="css"] { font-family:'Inter',-apple-system,sans-serif; }
div[data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 700; }
.stTabs [aria-selected="true"] { font-weight: 700; }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_all():
    entreprises.telecharger_fournisseurs()  # depuis cache CSV si deja present

    if not any(PDF_DIR.glob("*.pdf")):
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        factures = generator.generer_factures()
        for f in factures:
            generator.rendre_pdf(f, PDF_DIR / f"{f['numero_facture']}.pdf")
        verite = pd.DataFrame([{k: v for k, v in f.items() if k != "rendu"} for f in factures])
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        verite.to_csv(RAW_DIR / "verite_terrain.csv", index=False, encoding="utf-8")

    df_extrait = extractor.extraire_tous()
    df = quality_check.executer_controles(df_extrait, date_reference=DATE_REFERENCE)
    resume = quality_check.resumer(df)

    with open(CONFIG_DIR / "extraction_rules.yaml", encoding="utf-8") as f:
        regles = yaml.safe_load(f)["champs"]

    precision_globale, precision_par_champ, _ = extraction_eval.evaluer(df_extrait)

    return {
        "df": df, "resume": resume, "regles": regles,
        "precision_globale": precision_globale, "precision_par_champ": precision_par_champ,
    }


data = load_all()
df = data["df"]
resume = data["resume"]

with st.sidebar:
    st.markdown(
        "<div style='text-align:center;padding:12px 0;'>"
        "<div style='font-size:1.8rem;'>📄</div>"
        f"<div style='color:{C_PRIMARY};font-size:1.0rem;font-weight:700;'>Extraction Documents</div>"
        f"<div style='color:{C_MUTED};font-size:0.72rem;'>Factures fournisseurs · Data Steward</div>"
        "</div>", unsafe_allow_html=True)
    st.markdown(f"<hr style='border-color:{C_BORDER};'>", unsafe_allow_html=True)

    st.markdown(
        f"<div style='background:{C_SURF};border-radius:8px;padding:10px;font-size:0.75rem;color:{C_MUTED};'>"
        "⚠️ <strong>Projet personnel (POC)</strong><br>"
        "Je voulais comprendre comment automatiser la saisie de factures fournisseurs sans "
        "faire aveuglément confiance à l'extraction : détecter aussi bien un champ manquant "
        "qu'une facture cohérente en apparence mais fausse. Fournisseurs réels (API Sirene), "
        "contenu des factures simulé."
        "</div>", unsafe_allow_html=True)
    st.caption("Construit avec l'IA — Gisèle Metouck")
    st.caption("[GitHub](https://github.com/Kingdmfncr)")

st.title("Extraction Structurée de Documents Métier")
st.caption("Moteur d'extraction déclaratif (YAML) + contrôle qualité métier sur factures fournisseurs simulées.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Factures traitées", resume["Factures traitees"])
c2.metric("OK", resume["OK"])
c3.metric("À vérifier", resume["A verifier"])
c4.metric("Anomalie", resume["Anomalie"])

tabs = st.tabs(["Vue d'ensemble", "Factures à vérifier", "Détail extraction",
                "Règles d'extraction", "Uploader une facture"])

with tabs[0]:
    rep_statut = df["statut"].value_counts()
    fig = go.Figure(go.Pie(labels=rep_statut.index, values=rep_statut.values, hole=0.55,
                            marker=dict(colors=[STATUT_COLORS[s] for s in rep_statut.index])))
    fig.update_layout(title="Répartition des factures par statut", height=320, **CHART_DEFAULTS)
    st.plotly_chart(fig, use_container_width=True, key="chart_statut")

    st.subheader("Précision d'extraction mesurée")
    st.caption(
        "Comparaison champ par champ entre ce qui a été extrait et la vérité terrain connue "
        "(`data/raw/verite_terrain.csv`, produite par le générateur) — un vrai chiffre mesuré, "
        "pas une estimation. Le SIRET est exclu : ~10% des factures ne l'affichent pas du tout "
        "par construction, ce n'est pas une erreur d'extraction."
    )
    if data["precision_globale"] is None:
        st.caption("Vérité terrain indisponible (fichier absent) — précision non calculable.")
    else:
        cg, cd = st.columns([1, 2])
        cg.metric("Précision globale", f"{data['precision_globale']}%")
        cd.dataframe(data["precision_par_champ"].rename("Précision (%)"), use_container_width=True)

    st.info(
        f"{int(df['siret_manquant'].sum())} facture(s) sans SIRET visible sur le document "
        "— non compté comme anomalie (champ non-critique par design), mais signalé pour vérification manuelle."
    )
    st.caption("Écarts de cohérence TTC détectés (montant_ttc ≠ HT + TVA à l'extraction) :")
    incoherentes = df[df["ecart_ttc_incoherent"]]
    if incoherentes.empty:
        st.success("✅ Aucune incohérence de calcul détectée.")
    else:
        st.dataframe(
            incoherentes[["fichier", "montant_ht", "montant_tva", "montant_ttc", "ecart_ttc_montant"]],
            use_container_width=True, hide_index=True,
        )

with tabs[1]:
    st.caption("Factures nécessitant une vérification humaine avant intégration en base (statut ≠ OK).")
    a_verifier = df[df["statut"] != "OK"][
        ["fichier", "statut", "numero_facture", "date_facture", "siret_manquant",
         "ecart_ttc_incoherent", "date_implausible", "nb_champs_critiques_manquants"]
    ]
    if a_verifier.empty:
        st.success("✅ Toutes les factures sont passées les contrôles.")
    else:
        st.dataframe(a_verifier, use_container_width=True, hide_index=True)

with tabs[2]:
    st.caption(f"Détail des {len(df)} factures extraites, tous champs et indicateurs de contrôle.")
    st.dataframe(df, use_container_width=True, hide_index=True)

with tabs[3]:
    st.caption("Règles d'extraction déclarées dans `config/extraction_rules.yaml` — aucune regex codée en dur.")
    lignes = []
    for nom_champ, meta in data["regles"].items():
        lignes.append({
            "Champ": nom_champ, "Critique": "🔴 Oui" if meta.get("critique", True) else "🟢 Non (peut être absent)",
            "Nb patterns essayés": len(meta["patterns"]),
        })
    st.dataframe(pd.DataFrame(lignes), use_container_width=True, hide_index=True)

with tabs[4]:
    st.caption(
        "Dépose une vraie facture PDF (pas une des 40 factures simulées de la démo) : "
        "l'extraction tourne en direct sur ton document, avec le même moteur déclaratif. "
        "Les patterns de `config/extraction_rules.yaml` sont calés sur le format de la démo — "
        "un format très différent peut légitimement ne rien trouver, c'est un vrai test, pas "
        "un tour de magie."
    )
    fichier_uploade = st.file_uploader("Facture PDF", type="pdf")

    if fichier_uploade is not None:
        try:
            champs = extractor.extraire_facture(fichier_uploade)
        except Exception as exc:
            st.error(f"Échec de lecture du PDF : {exc}")
        else:
            record = extractor.champs_to_record(fichier_uploade.name, champs)
            df_upload = pd.DataFrame([record])
            df_upload = quality_check.executer_controles(df_upload, date_reference=DATE_REFERENCE)
            ligne = df_upload.iloc[0]

            st.markdown(f"**Statut** : {ligne['statut']}")
            for nom_champ in data["regles"].keys():
                valeur = ligne.get(nom_champ)
                confiance = ligne.get(f"{nom_champ}_confiance", 0.0)
                trouve = ligne.get(f"{nom_champ}_trouve", False)
                emoji = "🟢" if confiance >= 0.8 else ("🟡" if confiance > 0 else "⚪")
                affichage = valeur if trouve and pd.notna(valeur) else "_non trouvé_"
                st.markdown(f"{emoji} **{nom_champ}** : {affichage}  (confiance {confiance:.2f})")

            if ligne.get("ecart_ttc_incoherent"):
                st.warning(f"⚠️ Incohérence de calcul détectée (écart de {ligne['ecart_ttc_montant']} EUR).")
            if ligne.get("nb_champs_critiques_manquants", 0) > 0:
                st.warning(f"⚠️ {int(ligne['nb_champs_critiques_manquants'])} champ(s) critique(s) non trouvé(s).")
