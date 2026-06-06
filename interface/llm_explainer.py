

import os
import requests
from dotenv import load_dotenv

load_dotenv()


# ─── Configuration ────────────────────────────────────────────────────────────

GROQ_API_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL     = "llama-3.3-70b-versatile"

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-20250514"


# ─── Contexte de la solution ──────────────────────────────────────────────────

def _build_context(strategy_result, dataset: dict, profile) -> str:
    """Construit un résumé de la solution pour le LLM."""
    routes       = strategy_result.routes
    meta         = strategy_result.meta
    nb_total     = len(dataset["orders"])
    nb_solved    = meta["nb_orders_solved"]
    service_rate = round(nb_solved / max(nb_total, 1) * 100, 1)
    active_flags = [k for k, v in profile.flags.items() if v is True]

    route_lines = []
    for r in routes[:8]:
        route_lines.append(
            f"  - {r['vehicle_id']} ({r['vehicle_type']}) : "
            f"{r['nb_stops']} stops, "
            f"{r['total_weight_kg']}kg, "
            f"{r['total_distance_km']} km"
            + (f", départ: {r.get('depot_id','')}" if r.get('depot_id') else "")
        )
    if len(routes) > 8:
        route_lines.append(f"  ... + {len(routes)-8} autres routes")

    return f"""
Solution VRP calculée :
- {nb_total} commandes | {len(dataset['vehicles'])} véhicules
- Contraintes : {active_flags}
- {meta['nb_clusters_solved']} cluster(s) traité(s)

Résultats :
- {nb_solved}/{nb_total} livrées ({service_rate}%)
- {len(routes)} routes | {meta['total_distance_km']} km total

Détail :
{chr(10).join(route_lines)}
{"- " + str(nb_total - nb_solved) + " commandes non livrées (capacité insuffisante)" if nb_total > nb_solved else "- Toutes les commandes livrées"}
""".strip()


# ─── Appels API ───────────────────────────────────────────────────────────────

SYSTEM_EXPLAIN = """Tu es un expert en logistique et optimisation de tournées.
Génère une explication claire et professionnelle en français de la solution VRP fournie.
Maximum 180 mots. Couvre : résultats globaux, logique de répartition, recommandations si besoin."""


def _call_groq(context: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return ""

    try:
        response = requests.post(
            GROQ_API_URL,
            headers = {
                "Content-Type" : "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json = {
                "model"      : GROQ_MODEL,
                "max_tokens" : 400,
                "temperature": 0.3,
                "messages"   : [
                    {"role": "system", "content": SYSTEM_EXPLAIN},
                    {"role": "user",   "content": context},
                ],
            },
            timeout = 20,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  ❌ Groq explainer : {e}")
        return ""


def _call_claude(context: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return ""

    try:
        response = requests.post(
            CLAUDE_API_URL,
            headers = {
                "Content-Type"      : "application/json",
                "x-api-key"         : api_key,
                "anthropic-version" : "2023-06-01",
            },
            json = {
                "model"      : CLAUDE_MODEL,
                "max_tokens" : 400,
                "system"     : SYSTEM_EXPLAIN,
                "messages"   : [{"role": "user", "content": context}],
            },
            timeout = 30,
        )
        response.raise_for_status()
        return response.json()["content"][0]["text"].strip()
    except Exception as e:
        print(f"  ❌ Claude explainer : {e}")
        return ""


# ─── Fallback règle-based ─────────────────────────────────────────────────────

def _explain_rulebased(strategy_result, dataset: dict, profile) -> str:
    """Explication sans API — toujours disponible."""
    meta         = strategy_result.meta
    routes       = strategy_result.routes
    nb_total     = len(dataset["orders"])
    nb_solved    = meta["nb_orders_solved"]
    service_rate = round(nb_solved / max(nb_total, 1) * 100, 1)
    nb_unsolved  = nb_total - nb_solved

    lines = [
        f"Résumé de la solution :",
        f"",
        f"  {nb_solved}/{nb_total} commandes livrées ({service_rate}%)",
        f"  {len(routes)} routes générées sur {meta['total_distance_km']} km",
    ]

    if meta["nb_clusters_solved"] > 1:
        lines.append(f"  Découpage en {meta['nb_clusters_solved']} zones géographiques")

    if profile.has_time_windows:
        lines.append(f"  Créneaux horaires respectés")

    if profile.needs_refrigeration:
        lines.append(f"  Chaîne du froid assurée (véhicules frigorifiques)")

    if profile.is_multi_depot:
        lines.append(f"  Flotte répartie sur {len(dataset.get('depots', []))} dépôts")

    if nb_unsolved > 0:
        lines += [
            f"",
            f"  {nb_unsolved} commandes reportées au prochain passage.",
            f"  Recommandation : augmenter la flotte ou planifier 2 passages.",
        ]
    else:
        lines.append(f"  Toutes les commandes ont été livrées.")

    return "\n".join(lines)


# ─── Fonction principale ──────────────────────────────────────────────────────

def explain_solution(strategy_result, dataset: dict, profile) -> str:
    """
    Génère une explication de la solution VRP.
    Utilise Groq → Claude → règle-based selon disponibilité.
    """
    context = _build_context(strategy_result, dataset, profile)

    if os.getenv("GROQ_API_KEY"):
        explanation = _call_groq(context)
        if explanation:
            return explanation

    if os.getenv("ANTHROPIC_API_KEY"):
        explanation = _call_claude(context)
        if explanation:
            return explanation

    return _explain_rulebased(strategy_result, dataset, profile) 