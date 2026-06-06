

import json
import csv
import os
from datetime import datetime
from pathlib import Path


# ─── Dossier de sortie ────────────────────────────────────────────────────────

OUTPUT_DIR = Path("data/output")


# ─── Formatage du temps ───────────────────────────────────────────────────────

def _minutes_to_hhmm(minutes: int) -> str:
    """Convertit des minutes depuis minuit en 'HH:MM'."""
    if minutes is None:
        return "N/A"
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


# ─── Construction du document JSON complet ───────────────────────────────────

def _build_json_document(result: dict, dataset: dict, profile) -> dict:


    # ── Meta ──────────────────────────────────────────────────────────────────
    meta = {
        "generated_at"   : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scenario"       : dataset.get("scenario", "UNKNOWN"),
        "depot_id"       : dataset["depot"]["id"],
        "depot_name"     : dataset["depot"].get("name", "Dépôt"),
        "depot_lat"      : dataset["depot"]["lat"],
        "depot_lng"      : dataset["depot"]["lng"],
    }

    # ── Summary ───────────────────────────────────────────────────────────────
    routes          = result.get("routes", [])
    total_stops     = sum(r["nb_stops"] for r in routes)
    total_weight    = sum(r["total_weight_kg"] for r in routes)
    vehicles_used   = len(routes)
    vehicles_total  = len(dataset["vehicles"])

    summary = {
        "nb_orders_total"    : len(dataset["orders"]),
        "nb_orders_served"   : result.get("nb_orders", 0),
        "nb_orders_unserved" : len(result.get("unserved_orders", [])),
        "service_rate_pct"   : round(
            result.get("nb_orders", 0) / max(len(dataset["orders"]), 1) * 100, 1
        ),
        "total_distance_km"  : result.get("total_distance_km", 0.0),
        "total_weight_kg"    : round(total_weight, 1),
        "total_stops"        : total_stops,
        "vehicles_used"      : vehicles_used,
        "vehicles_total"     : vehicles_total,
        "vehicles_restantes"      : vehicles_total - vehicles_used,
        "avg_stops_per_route": round(total_stops / max(vehicles_used, 1), 1),
        "avg_distance_per_route_km": round(
            result.get("total_distance_km", 0) / max(vehicles_used, 1), 2
        ),
    }

    # ── Flags actifs ──────────────────────────────────────────────────────────
    flags = profile.flags if profile else {}

    # ── Routes ────────────────────────────────────────────────────────────────
    formatted_routes = []
    for i, route in enumerate(routes):
        stops = []
        for j, stop in enumerate(route["stops"]):
            stops.append({
                "sequence"    : j + 1,
                "order_id"    : stop["order_id"],
                "client"      : stop["client"],
                "lat"         : stop["lat"],
                "lng"         : stop["lng"],
                "weight_kg"   : stop["weight_kg"],
                "arrival_time": _minutes_to_hhmm(stop.get("arrival_min")),
            })

        formatted_routes.append({
            "route_id"          : i + 1,
            "vehicle_id"        : route["vehicle_id"],
            "vehicle_type"      : route["vehicle_type"],
            "vehicle_capacity"  : route["vehicle_capacity"],
            "nb_stops"          : route["nb_stops"],
            "total_weight_kg"   : route["total_weight_kg"],
          
            "total_distance_km" : route["total_distance_km"],
            "stops"             : stops,
        })

    # ── Commandes non livrées ─────────────────────────────────────────────────
    unserved_ids = result.get("unserved_orders", [])
    unserved     = []
    order_map    = {o["id"]: o for o in dataset["orders"]}

    for oid in unserved_ids:
        o = order_map.get(oid, {})
        unserved.append({
            "order_id" : oid,
            "client"   : o.get("client", ""),
            "weight_kg": o.get("weight", 0),
            "lat"      : o.get("lat"),
            "lng"      : o.get("lng"),
        })

    return {
        "meta"    : meta,
        "summary" : summary,
        "flags"   : flags,
        "routes"  : formatted_routes,
        "unserved": unserved,
    }


# ─── Export JSON ──────────────────────────────────────────────────────────────

def export_json(
    result  : dict,
    dataset : dict,
    profile ,
    filename: str = "routes_solution.json",
) -> Path:
  
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / filename

    document = _build_json_document(result, dataset, profile)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)

    print(f"\n  📄 JSON exporté → {filepath}")
    return filepath


# ─── Export CSV ───────────────────────────────────────────────────────────────

def export_csv(
    result  : dict,
    dataset : dict,
    filename: str = "routes_solution.csv",
) -> Path:

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / filename

    rows = []
    for i, route in enumerate(result.get("routes", [])):
        for j, stop in enumerate(route["stops"]):
            rows.append({
                "route_id"          : i + 1,
                "vehicle_id"        : route["vehicle_id"],
                "vehicle_type"      : route["vehicle_type"],
                "vehicle_capacity"  : route["vehicle_capacity"],
                "sequence"          : j + 1,
                "order_id"          : stop["order_id"],
                "client"            : stop["client"],
                "lat"               : stop["lat"],
                "lng"               : stop["lng"],
                "weight_kg"         : stop["weight_kg"],
                "arrival_time"      : _minutes_to_hhmm(stop.get("arrival_min")),
                "route_distance_km" : route["total_distance_km"],
                "route_weight_kg"   : route["total_weight_kg"],
            })

    if not rows:
        print("  ⚠️  Aucune route à exporter en CSV.")
        return filepath

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"  📊 CSV exporté  → {filepath}")
    return filepath


# ─── Fonction principale ──────────────────────────────────────────────────────

def export_solution(
    result  : dict,
    dataset : dict,
    profile ,
) -> dict:
 
    print(f"\n{'─'*52}")
    print(f"  💾 Export de la solution")
    print(f"{'─'*52}")

    json_path = export_json(result, dataset, profile)
    csv_path  = export_csv(result, dataset)

    # résumé console
    summary = {
        "nb_orders_served"  : result.get("nb_orders", 0),
        "nb_orders_total"   : len(dataset["orders"]),
        "total_distance_km" : result.get("total_distance_km", 0.0),
        "vehicles_used"     : len(result.get("routes", [])),
        "json_path"         : str(json_path),
        "csv_path"          : str(csv_path),
    }

    service_rate = round(
        summary["nb_orders_served"] / max(summary["nb_orders_total"], 1) * 100, 1
    )

    print(f"\n  ✅ Export terminé")
    print(f"     Commandes livrées : "
          f"{summary['nb_orders_served']}/{summary['nb_orders_total']} "
          f"({service_rate}%)")
    print(f"     Distance totale   : {summary['total_distance_km']} km")
    print(f"     Véhicules utilisés: {summary['vehicles_used']}")
    print(f"{'─'*52}")

    return summary