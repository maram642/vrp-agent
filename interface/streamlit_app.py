"""
interface/streamlit_app.py
---------------------------
Interface graphique du VRP Agent.

Usage :
    streamlit run interface/streamlit_app.py

Fonctionnalités :
    - Upload de fichier JSON ou sélection d'un scénario demo
    - Saisie de contraintes en langage naturel (LLM parser)
    - Lancement de l'optimisation
    - Visualisation des résultats (carte + tableau)
    - Explication LLM de la solution
    - Export JSON / CSV
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
import json
import streamlit as st
import pandas as pd
import tempfile

from core.preprocessing.cleaner         import load_and_clean
from core.classification.vrp_classifier import classify
from core.strategy.strategy_selector    import run as run_strategy
from core.export.export_solution        import export_solution
from interface.llm_parser               import parse_constraints
from interface.llm_explainer           import explain_solution


# ─── Config page ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title = "VRP Agent",
    page_icon  = "🚛",
    layout     = "wide",
)


# ─── Titre ────────────────────────────────────────────────────────────────────

st.title("🚛 VRP Agent — Optimisation Intelligente des Tournées")
st.divider()


# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Configuration")

    # source de données
    st.subheader("📂 Source de données")
    data_source = st.radio(
        "Source",
        ["Scénario démo", "Uploader un fichier JSON"],
        label_visibility="collapsed",
    )

    SCENARIOS = {
        "CVRP simple (15 cmd)"     : "data/synthetic/scenario_simple.json",
        "VRPTW + frigo (100 cmd)"  : "data/synthetic/scenario_timewindows.json",
        "Multi-dépôt (30 cmd)"     : "data/synthetic/scenario_multidepot.json",
        "Grand dataset (1000 cmd)" : "data/synthetic/scenario_large.json",
    }

    filepath    = None
    uploaded_ok = False

    if data_source == "Scénario démo":
        scenario    = st.selectbox("Scénario", list(SCENARIOS.keys()))
        filepath    = SCENARIOS[scenario]
        uploaded_ok = True
    else:
        uploaded = st.file_uploader("Fichier JSON", type=["json"])
        if uploaded:
            tmp_dir  = tempfile.gettempdir()   # détecte automatiquement le bon dossier
            tmp_path = os.path.join(tmp_dir, uploaded.name)
            with open(tmp_path, "wb") as f:
              f.write(uploaded.read())
            filepath    = tmp_path
            uploaded_ok = True

    st.divider()

    # contraintes LLM
    st.subheader("🤖 Contraintes LLM")
    use_llm  = st.checkbox("Activer", value=False)
    llm_text = ""
    if use_llm:
        llm_text = st.text_area(
            "Contraintes en langage naturel",
            placeholder="ex: livrer les produits frais avant 14h",
            height=90,
            label_visibility="collapsed",
        )
        

    st.divider()

    # options
    st.subheader("🔧 Options")
    show_explain = st.checkbox("Explication LLM", value=True)
    do_export    = st.checkbox("Exporter JSON/CSV", value=True)

    st.divider()

    run_btn = st.button(
        "🚀 Lancer l'optimisation",
        type="primary",
        use_container_width=True,
        disabled=not uploaded_ok,
    )


# ─── Chargement données ───────────────────────────────────────────────────────

if not uploaded_ok:
    st.info("👈 Sélectionnez un scénario ou uploadez un fichier JSON.")
    st.stop()

cache_key = filepath
if st.session_state.get("_filepath") != cache_key:
    try:
        st.session_state["dataset"]   = load_and_clean(filepath)
        st.session_state["_filepath"] = cache_key
        st.session_state.pop("result",  None)
        st.session_state.pop("profile", None)
    except Exception as e:
        st.error(f"❌ Erreur chargement : {e}")
        st.stop()

dataset = st.session_state["dataset"]


# ─── Aperçu données ───────────────────────────────────────────────────────────

c1, c2, c3, c4 = st.columns(4)
c1.metric("📦 Commandes",   len(dataset["orders"]))
c2.metric("🚛 Véhicules",   len(dataset["vehicles"]))
c3.metric("🏭 Dépôts",      len(dataset.get("depots", [dataset["depot"]])))
c4.metric("⚖️ Poids total", f"{sum(o['weight'] for o in dataset['orders']):.0f} kg")


# ─── Lancement ────────────────────────────────────────────────────────────────

if run_btn:
    st.divider()

    # LLM parser
    if use_llm and llm_text.strip():
        with st.spinner("🤖 Analyse des contraintes..."):
            flags = parse_constraints(llm_text, dataset)
        if flags:
            st.success(f"✅ Contraintes : {list(flags.keys())}")
        else:
            st.warning("⚠️ Aucune contrainte détectée")

    # classification
    with st.spinner("🔎 Classification..."):
        profile = classify(dataset)

    with st.expander("🔎 Profil détecté", expanded=False):
        fc1, fc2, fc3, fc4 = st.columns(4)
        fc1.metric("⏰ Time windows",  "Oui" if profile.has_time_windows else "Non")
        fc2.metric("🧊 Frigo",         "Oui" if profile.needs_refrigeration else "Non")
        fc3.metric("🏭 Multi-dépôt",   "Oui" if profile.is_multi_depot else "Non")
        fc4.metric("🗺️ Clustering",    "Oui" if profile.needs_clustering else "Non")

    # résolution
    with st.spinner("⚙️ Optimisation OR-Tools..."):
        t0     = time.time()
        result = run_strategy(dataset, profile)
        elapsed = round(time.time() - t0, 1)

    st.session_state.update({
        "result" : result,
        "profile": profile,
        "elapsed": elapsed,
    })
    st.success(f"✅ Optimisation terminée en {elapsed}s")


# ─── Résultats ────────────────────────────────────────────────────────────────

if "result" not in st.session_state:
    st.stop()

result  = st.session_state["result"]
profile = st.session_state["profile"]
elapsed = st.session_state.get("elapsed", "?")

st.divider()
st.subheader("📊 Résultats")

nb_total     = len(dataset["orders"])
nb_solved    = result.meta["nb_orders_solved"]
service_rate = round(nb_solved / max(nb_total, 1) * 100, 1)
nb_routes    = len(result.routes)
total_dist   = result.meta["total_distance_km"]
nb_clusters  = result.meta["nb_clusters_solved"]

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("📦 Livrées",    f"{nb_solved}/{nb_total}")
m2.metric("✅ Taux",        f"{service_rate}%")
m3.metric("🚛 Routes",      nb_routes)
m4.metric("📏 Distance",    f"{total_dist} km")
m5.metric("⏱️ Durée",       f"{elapsed}s")

st.divider()

# tableau routes + stops
st.subheader("🗺️ Tournées")
tab_routes, tab_stops, tab_map = st.tabs(["📋 Routes", "📍 Stops", "🗺️ Carte"])

with tab_routes:
    if result.routes:
        routes_df = pd.DataFrame([{
            "Véhicule"     : r["vehicle_id"],
            "Type"         : r["vehicle_type"],
            "Dépôt"        : r.get("depot_id", dataset["depot"]["id"]),
            "Stops"        : r["nb_stops"],
            "Poids (kg)"   : r["total_weight_kg"],
            "Capacité (kg)": r["vehicle_capacity"],
            "Charge (%)"   : round(r["total_weight_kg"] / r["vehicle_capacity"] * 100, 1),
            "Distance (km)": r["total_distance_km"],
        } for r in result.routes])
        st.dataframe(routes_df, use_container_width=True, hide_index=True)

with tab_stops:
    stops_rows = []
    for r in result.routes:
        for i, s in enumerate(r["stops"]):
            arrival = "—"
            if s.get("arrival_min") is not None:
                h, m = divmod(s["arrival_min"], 60)
                arrival = f"{h:02d}:{m:02d}"
            stops_rows.append({
                "Véhicule" : r["vehicle_id"],
                "Seq"      : i + 1,
                "Client"   : s["client"],
                "Poids"    : s["weight_kg"],
                "Arrivée"  : arrival,
                "Lat"      : s["lat"],
                "Lng"      : s["lng"],
            })

    if stops_rows:
        st.dataframe(
            pd.DataFrame(stops_rows),
            use_container_width=True,
            hide_index=True,
        )

with tab_map:
    if stops_rows:
        map_df = pd.DataFrame([
            {"lat": s["Lat"], "lon": s["Lng"]} for s in stops_rows
        ])
        st.map(map_df, zoom=11)

        # dépôts sur la carte
        depot_list = dataset.get("depots", [dataset["depot"]])
        depot_df   = pd.DataFrame([
            {"lat": d["lat"], "lon": d["lng"]} for d in depot_list
        ])
        st.caption(f"🏭 {len(depot_list)} dépôt(s) | 📍 {len(stops_rows)} stops")

# commandes non livrées
served_ids = {s["order_id"] for r in result.routes for s in r["stops"]}
unserved   = {o["id"] for o in dataset["orders"]} - served_ids

if unserved:
    with st.expander(f"⚠️ {len(unserved)} commandes non livrées", expanded=False):
        unserved_df = pd.DataFrame([{
            "ID"     : o["id"],
            "Client" : o["client"],
            "Poids"  : o["weight"],
        } for o in dataset["orders"] if o["id"] in unserved])
        st.dataframe(unserved_df, use_container_width=True, hide_index=True)

st.divider()

# explication LLM
if show_explain:
    st.subheader("💬 Analyse")
    with st.spinner("Génération de l'explication..."):
        explanation = explain_solution(result, dataset, profile)
    st.info(explanation)

# export
if do_export:
    st.divider()
    st.subheader("💾 Export")

    result_dict = {
        "routes"            : result.routes,
        "nb_orders"         : result.meta["nb_orders_solved"],
        "total_distance_km" : result.meta["total_distance_km"],
        "unserved_orders"   : list(unserved),
    }

    try:
        summary = export_solution(result_dict, dataset, profile)
        col_j, col_c = st.columns(2)

        with col_j:
            with open(summary["json_path"], "r", encoding="utf-8") as f:
                st.download_button(
                    "⬇️ Télécharger JSON",
                    data=f.read(),
                    file_name="routes_solution.json",
                    mime="application/json",
                    use_container_width=True,
                )

        with col_c:
            with open(summary["csv_path"], "r", encoding="utf-8") as f:
                st.download_button(
                    "⬇️ Télécharger CSV",
                    data=f.read(),
                    file_name="routes_solution.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
    except Exception as e:
        st.warning(f"Export non disponible : {e}")