"""
core/preprocessing/cleaner.py
-------------------------------
Charge et valide un fichier JSON de scénario VRP.
Retourne un dataset propre prêt pour le reste du pipeline.
"""

import json
import math
from pathlib import Path


# ─── Constantes de validation ────────────────────────────────────────────────

LAT_MIN, LAT_MAX = -90.0, 90.0
LNG_MIN, LNG_MAX = -180.0, 180.0
WEIGHT_MIN       = 0.1       # kg minimum acceptable
WEIGHT_MAX       = 50_000.0  # kg maximum acceptable (camion lourd)
CAPACITY_MIN     = 1.0


# ─── Erreurs personnalisées ───────────────────────────────────────────────────

class CleanerError(Exception):
    """Erreur levée quand les données sont invalides."""
    pass


# ─── Fonctions utilitaires ────────────────────────────────────────────────────

def _check_required(obj: dict, fields: list, context: str):
    """Vérifie que tous les champs requis existent dans un dict."""
    for field in fields:
        if field not in obj:
            raise CleanerError(f"[{context}] Champ obligatoire manquant : '{field}'")


def _validate_coords(lat, lng, context: str):
    """Vérifie que lat/lng sont numériques et dans les bornes globales."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        raise CleanerError(f"[{context}] lat/lng doivent être des nombres. Reçu : lat={lat}, lng={lng}")

    if not (LAT_MIN <= lat <= LAT_MAX):
        raise CleanerError(f"[{context}] Latitude hors bornes : {lat} (attendu entre {LAT_MIN} et {LAT_MAX})")
    if not (LNG_MIN <= lng <= LNG_MAX):
        raise CleanerError(f"[{context}] Longitude hors bornes : {lng} (attendu entre {LNG_MIN} et {LNG_MAX})")

    return lat, lng


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    """Distance en km entre deux points GPS (formule Haversine)."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi        = math.radians(lat2 - lat1)
    dlambda     = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─── Validation dépôt ────────────────────────────────────────────────────────

def _clean_depot(depot: dict) -> dict:
    """Valide et normalise le dépôt principal."""
    context = "depot"
    _check_required(depot, ["id", "lat", "lng"], context)

    lat, lng = _validate_coords(depot["lat"], depot["lng"], context)

    return {
        "id"           : str(depot["id"]),
        "name"         : str(depot.get("name", "Depot")),
        "lat"          : lat,
        "lng"          : lng,
        "opening_time" : depot.get("opening_time", "00:00"),
        "closing_time" : depot.get("closing_time", "23:59"),
    }


def _clean_depots(raw: dict) -> list:
    """
    Valide et normalise la liste des dépôts si présente (multi-dépôt).
    Retourne None si pas de multi-dépôt (clé absente ou moins de 2 dépôts).
    """
    raw_depots = raw.get("depots")

    if not isinstance(raw_depots, list) or len(raw_depots) < 2:
        return None

    cleaned  = []
    seen_ids = set()

    for i, d in enumerate(raw_depots):
        context = f"depots[{i}]"
        _check_required(d, ["id", "lat", "lng"], context)

        did = str(d["id"])
        if did in seen_ids:
            raise CleanerError(f"[{context}] ID dépôt dupliqué : '{did}'")
        seen_ids.add(did)

        lat, lng = _validate_coords(d["lat"], d["lng"], context)

        cleaned.append({
            "id"           : did,
            "name"         : str(d.get("name", f"Depot_{i}")),
            "lat"          : lat,
            "lng"          : lng,
            "opening_time" : d.get("opening_time", "00:00"),
            "closing_time" : d.get("closing_time", "23:59"),
        })

    return cleaned


# ─── Validation véhicules ─────────────────────────────────────────────────────

def _clean_vehicles(vehicles: list) -> list:
    """Valide et normalise la liste des véhicules."""
    if not vehicles:
        raise CleanerError("[vehicles] La liste des véhicules est vide.")

    cleaned = []
    seen_ids = set()

    for i, v in enumerate(vehicles):
        context = f"vehicle[{i}]"
        _check_required(v, ["id", "capacity"], context)

        vid = str(v["id"])
        if vid in seen_ids:
            raise CleanerError(f"[{context}] ID dupliqué : '{vid}'")
        seen_ids.add(vid)

        try:
            capacity = float(v["capacity"])
        except (TypeError, ValueError):
            raise CleanerError(f"[{context}] 'capacity' doit être un nombre. Reçu : {v['capacity']}")

        if capacity < CAPACITY_MIN:
            raise CleanerError(f"[{context}] 'capacity' trop faible : {capacity} kg (min={CAPACITY_MIN})")

        cleaned.append({
            "id"                    : vid,
            "name"                  : str(v.get("name", vid)),
            "capacity"              : capacity,
            "type"                  : str(v.get("type", "standard")),
            "max_route_duration_h"  : float(v.get("max_route_duration_h", 12.0)),
        })

    return cleaned


# ─── Validation commandes ─────────────────────────────────────────────────────

def _clean_orders(orders: list, depot: dict) -> list:
    """Valide, normalise et enrichit les commandes (distance au dépôt)."""
    if not orders:
        raise CleanerError("[orders] La liste des commandes est vide.")

    cleaned    = []
    seen_ids   = set()
    duplicates = []

    for i, o in enumerate(orders):
        context = f"order[{i}]"
        _check_required(o, ["id", "lat", "lng", "weight"], context)

        oid = str(o["id"])

        # Doublon d'ID → on log mais on ne plante pas, on skip le doublon
        if oid in seen_ids:
            duplicates.append(oid)
            continue
        seen_ids.add(oid)

        lat, lng = _validate_coords(o["lat"], o["lng"], context)

        try:
            weight = float(o["weight"])
        except (TypeError, ValueError):
            raise CleanerError(f"[{context}] 'weight' doit être un nombre. Reçu : {o['weight']}")

        if not (WEIGHT_MIN <= weight <= WEIGHT_MAX):
            raise CleanerError(
                f"[{context}] 'weight' hors bornes : {weight} kg "
                f"(attendu entre {WEIGHT_MIN} et {WEIGHT_MAX})"
            )

        dist_km = _haversine_km(depot["lat"], depot["lng"], lat, lng)

        entry = {
            "id"                    : oid,
            "client"                : str(o.get("client", oid)),
            "lat"                   : lat,
            "lng"                   : lng,
            "weight"                : weight,
            "distance_to_depot_km"  : round(dist_km, 3),
            # champs optionnels VRPTW
            "time_window"           : o.get("time_window", None),
            "requires_refrigeration": bool(o.get("requires_refrigeration", False)),
            "service_time_min"      : int(o.get("service_time_min", 0)),
            # champ optionnel large
            "zone"                  : o.get("zone", None),
        }

        cleaned.append(entry)

    if duplicates:
        print(f"  ⚠️  Doublons ignorés ({len(duplicates)}) : {duplicates[:5]}{'...' if len(duplicates)>5 else ''}")

    return cleaned


# ─── Validations globales ─────────────────────────────────────────────────────

def _global_checks(dataset: dict):
    """Vérifications croisées entre orders et vehicles."""
    vehicles = dataset["vehicles"]
    orders   = dataset["orders"]

    max_capacity  = max(v["capacity"] for v in vehicles)
    total_weight  = sum(o["weight"] for o in orders)
    total_capacity = sum(v["capacity"] for v in vehicles)

    # Une commande plus lourde que le plus grand camion → impossible à livrer
    overweight = [o for o in orders if o["weight"] > max_capacity]
    if overweight:
        ids = [o["id"] for o in overweight[:5]]
        raise CleanerError(
            f"{len(overweight)} commande(s) dépassent la capacité du plus grand véhicule "
            f"({max_capacity} kg) : {ids}"
        )

    # Alerte si la flotte ne peut pas tout livrer (pas un crash, juste un warning)
    if total_weight > total_capacity:
        print(
            f"  ⚠️  Attention : poids total commandes ({total_weight:.0f} kg) "
            f"> capacité totale flotte ({total_capacity:.0f} kg). "
            f"Toutes les commandes ne pourront pas être livrées en un seul passage."
        )


# ─── Fonction principale ──────────────────────────────────────────────────────

def load_and_clean(filepath: str) -> dict:
    """
    Charge un fichier JSON de scénario VRP, valide toutes les données
    et retourne un dataset propre.

    Parameters
    ----------
    filepath : str
        Chemin vers le fichier JSON (ex: "data/synthetic/scenario_simple.json")

    Returns
    -------
    dict avec les clés : scenario, depot, vehicles, orders, stats

    Raises
    ------
    FileNotFoundError  : si le fichier n'existe pas
    json.JSONDecodeError : si le JSON est malformé
    CleanerError       : si les données sont invalides
    """

    path = Path(filepath)

    # ── 1. Lecture du fichier ──────────────────────────────────────────────────
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {filepath}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    print(f"\n📂 Fichier chargé : {path.name}")

    # ── 2. Structure de base ───────────────────────────────────────────────────
    # "depot" est optionnel si "depots" (multi-dépôt) est présent
    _check_required(raw, ["vehicles", "orders"], "root")
    if "depot" not in raw and "depots" not in raw:
        raise CleanerError("[root] Ni 'depot' ni 'depots' présents dans les données.")

    # ── 3. Multi-dépôt (optionnel) — détecté en premier ──────────────────────
    depots = _clean_depots(raw)
    if depots:
        print(f"  🔍 Multi-dépôt détecté : {len(depots)} dépôts")

    # ── 4. Dépôt principal ────────────────────────────────────────────────────
    print("  🔍 Validation du dépôt...")
    if "depot" in raw:
        depot = _clean_depot(raw["depot"])
    elif depots:
        # multi-dépôt sans clé "depot" → dériver depuis le premier dépôt
        depot = depots[0]
        print("  ℹ️  Dépôt principal dérivé du premier dépôt (multi-dépôt)")
    else:
        raise CleanerError("[root] Impossible de déterminer le dépôt principal.")

    print("  🔍 Validation des véhicules...")
    vehicles = _clean_vehicles(raw["vehicles"])

    print("  🔍 Validation des commandes...")
    orders = _clean_orders(raw["orders"], depot)

    # ── 5. Checks croisés ─────────────────────────────────────────────────────
    print("  🔍 Vérifications globales...")
    dataset = {
        "scenario" : raw.get("scenario", "UNKNOWN"),
        "depot"    : depot,
        "vehicles" : vehicles,
        "orders"   : orders,
    }
    if depots:
        dataset["depots"] = depots
    _global_checks(dataset)

    # ── 5. Statistiques ───────────────────────────────────────────────────────
    total_weight   = sum(o["weight"] for o in orders)
    total_capacity = sum(v["capacity"] for v in vehicles)
    avg_dist       = sum(o["distance_to_depot_km"] for o in orders) / len(orders)
    has_tw         = any(o["time_window"] is not None for o in orders)
    needs_fridge   = any(o["requires_refrigeration"] for o in orders)

    stats = {
        "nb_orders"          : len(orders),
        "nb_vehicles"        : len(vehicles),
        "total_weight_kg"    : round(total_weight, 1),
        "total_capacity_kg"  : round(total_capacity, 1),
        "load_ratio_pct"     : round(total_weight / total_capacity * 100, 1),
        "avg_distance_km"    : round(avg_dist, 2),
        "has_time_windows"   : has_tw,
        "needs_refrigeration": needs_fridge,
    }
    dataset["stats"] = stats

    # ── 6. Résumé console ─────────────────────────────────────────────────────
    print(f"\n  ✅ Dataset propre — scénario : {dataset['scenario']}")
    print(f"     Commandes  : {stats['nb_orders']}")
    print(f"     Véhicules  : {stats['nb_vehicles']}")
    print(f"     Poids total : {stats['total_weight_kg']} kg / {stats['total_capacity_kg']} kg dispo ({stats['load_ratio_pct']}%)")
    print(f"     Dist. moy. dépôt : {stats['avg_distance_km']} km")
    print(f"     Time windows : {'Oui' if has_tw else 'Non'}")
    print(f"     Chaîne du froid : {'Oui' if needs_fridge else 'Non'}")

    return dataset