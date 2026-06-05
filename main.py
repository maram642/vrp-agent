"""
main.py
--------
Orchestrateur principal du pipeline VRP Agent.

Pipeline :
    1. Charger et nettoyer les données
    2. Parser les contraintes LLM (optionnel)
    3. Classifier le problème (ProblemProfile)
    4. Résoudre (clustering + OR-Tools)
    5. Exporter la solution (JSON + CSV)
    6. Expliquer la solution (LLM)

Usage CLI :
    python main.py --file data/synthetic/scenario_simple.json
    python main.py --file data/synthetic/scenario_timewindows.json
    python main.py --file data/synthetic/scenario_multidepot.json
    python main.py --file data/synthetic/scenario_large.json
    python main.py --file data/synthetic/scenario_simple.json --constraints "livrer avant 14h"
    python main.py --file data/synthetic/scenario_simple.json --no-export --no-explain

Import depuis un autre module :
    from main import run_pipeline
    result = run_pipeline("data/synthetic/scenario_simple.json")
"""

import argparse
import sys
from pathlib import Path

from core.preprocessing.cleaner         import load_and_clean
from core.classification.vrp_classifier import classify
from core.strategy.strategy_selector    import run as run_strategy
from core.export.export_solution        import export_solution


# ─── Pipeline principal ───────────────────────────────────────────────────────

def run_pipeline(
    filepath            : str,
    natural_constraints : str  = None,
    export              : bool = True,
    verbose             : bool = True,
) -> dict:
    """
    Lance le pipeline VRP complet.

    Parameters
    ----------
    filepath            : chemin vers le fichier JSON de données
    natural_constraints : contraintes en langage naturel (optionnel)
    export              : exporter JSON/CSV (défaut True)
    verbose             : afficher explication LLM (défaut True)

    Returns
    -------
    dict { dataset, profile, result, summary }
    """

    SEP  = "─" * 56
    SEP2 = "═" * 56

    print(f"\n{SEP2}")
    print(f"  🚀 VRP Agent — Pipeline complet")
    print(f"{SEP2}")

    # ── Étape 1 : Chargement ──────────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  📂 Étape 1 — Chargement des données")
    print(SEP)
    dataset = load_and_clean(filepath)

    # ── Étape 2 : Parser LLM (optionnel) ──────────────────────────────────────
    if natural_constraints:
        print(f"\n{SEP}")
        print(f"  🤖 Étape 2 — Contraintes LLM")
        print(SEP)
        try:
            from interface.llm_parser import parse_constraints
            flags = parse_constraints(natural_constraints, dataset)
            if flags:
                print(f"  ✅ Flags appliqués : {list(flags.keys())}")
            else:
                print(f"  ⚠️  Aucun flag détecté")
        except ImportError:
            print("  ⚠️  llm_parser non disponible")

    # ── Étape 3 : Classification ───────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  🔎 Étape 3 — Classification du problème")
    print(SEP)
    profile = classify(dataset)

    # ── Étape 4 : Résolution ───────────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  ⚙️  Étape 4 — Optimisation OR-Tools")
    print(SEP)
    strategy_result = run_strategy(dataset, profile)

    # ── Étape 5 : Export ──────────────────────────────────────────────────────
    summary = {}
    if export:
        print(f"\n{SEP}")
        print(f"  💾 Étape 5 — Export")
        print(SEP)

        # construire le dict résultat pour export_solution
        served_ids = {
            stop["order_id"]
            for route in strategy_result.routes
            for stop in route["stops"]
        }
        unserved = [
            o["id"] for o in dataset["orders"]
            if o["id"] not in served_ids
        ]

        result_dict = {
            "routes"            : strategy_result.routes,
            "nb_orders"         : strategy_result.meta["nb_orders_solved"],
            "total_distance_km" : strategy_result.meta["total_distance_km"],
            "unserved_orders"   : unserved,
        }
        summary = export_solution(result_dict, dataset, profile)

    # ── Étape 6 : Explication LLM ─────────────────────────────────────────────
    if verbose:
        print(f"\n{SEP}")
        print(f"  💬 Étape 6 — Explication")
        print(SEP)
        try:
            from interface.llm_explainer import explain_solution
            explanation = explain_solution(strategy_result, dataset, profile)
            print(f"\n{explanation}\n")
        except ImportError:
            print("  ⚠️  llm_explainer non disponible")

    # ── Résumé final ──────────────────────────────────────────────────────────
    nb_total     = len(dataset["orders"])
    nb_solved    = strategy_result.meta["nb_orders_solved"]
    service_rate = round(nb_solved / max(nb_total, 1) * 100, 1)

    print(f"\n{SEP2}")
    print(f"  ✅ Pipeline terminé")
    print(f"{SEP2}")
    print(f"  📦 Commandes   : {nb_solved}/{nb_total} ({service_rate}%)")
    print(f"  🚛 Routes      : {len(strategy_result.routes)}")
    print(f"  📏 Distance    : {strategy_result.meta['total_distance_km']} km")
    print(f"  🔢 Clusters    : {strategy_result.meta['nb_clusters_solved']}")
    if summary:
        print(f"  📄 JSON → {summary.get('json_path', '')}")
        print(f"  📊 CSV  → {summary.get('csv_path', '')}")
    print(f"{SEP2}\n")

    return {
        "dataset" : dataset,
        "profile" : profile,
        "result"  : strategy_result,
        "summary" : summary,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="VRP Agent — Optimisation intelligente des tournées"
    )
    parser.add_argument(
        "--file", "-f",
        required=True,
        help="Chemin vers le fichier JSON de données"
    )
    parser.add_argument(
        "--constraints", "-c",
        default=None,
        help='Contraintes en langage naturel ex: "livrer avant 14h"'
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Ne pas exporter JSON/CSV"
    )
    parser.add_argument(
        "--no-explain",
        action="store_true",
        help="Ne pas générer l'explication LLM"
    )

    args = parser.parse_args()

    if not Path(args.file).exists():
        print(f"❌ Fichier introuvable : {args.file}")
        sys.exit(1)

    run_pipeline(
        filepath            = args.file,
        natural_constraints = args.constraints,
        export              = not args.no_export,
        verbose             = not args.no_explain,
    )


if __name__ == "__main__":
    main()