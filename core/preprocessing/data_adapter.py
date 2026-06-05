"""
core/preprocessing/data_adapter.py
------------------------------------
Transforme les données brutes de l'API Addinn vers le format
interne standard attendu par cleaner.py.

Quand tu reçois le vrai format Addinn :
  → Mets à jour les dictionnaires ORDERS_MAP, VEHICLES_MAP, DEPOT_MAP
  → Le reste du code ne change pas.
"""

from typing import Any


# ─── Mappings de champs ───────────────────────────────────────────────────────
#
# Clé   = nom du champ dans TON format interne (ce que cleaner.py attend)
# Valeur = liste de noms possibles dans les données Addinn
#          → le premier trouvé est utilisé
#          → si aucun n'est trouvé → valeur par défaut (DEFAULT_*)

ORDERS_MAP = {
    # ton champ         candidats Addinn possibles
    "id"              : ["id", "order_id", "delivery_id", "commande_id"],
    "client"          : ["client", "customer_name", "client_name", "nom_client", "beneficiaire"],
    "lat"             : ["lat", "latitude", "delivery_latitude", "livraison_lat", "dest_lat"],
    "lng"             : ["lng", "longitude", "delivery_longitude", "livraison_lng", "dest_lng"],
    "weight"          : ["weight", "poids", "weight_kg", "package_weight", "colis_poids"],

    # champs optionnels VRPTW
    "time_window"           : ["time_window", "creneau", "delivery_window", "horaire_livraison"],
    "requires_refrigeration": ["requires_refrigeration", "cold_chain", "chaine_froid", "refrigere"],
    "service_time_min"      : ["service_time_min", "temps_service", "unloading_time", "duree_livraison"],
}

VEHICLES_MAP = {
    "id"                   : ["id", "vehicle_id", "camion_id", "truck_id"],
    "name"                 : ["name", "vehicle_name", "camion_nom", "label"],
    "capacity"             : ["capacity", "capacite", "max_load", "charge_max", "vehicle_capacity"],
    "type"                 : ["type", "vehicle_type", "camion_type", "truck_type"],
    "max_route_duration_h" : ["max_route_duration_h", "duree_max_h", "max_hours", "route_max_duration"],
}

DEPOT_MAP = {
    "id"           : ["id", "depot_id", "entrepot_id", "warehouse_id"],
    "name"         : ["name", "depot_name", "entrepot_nom", "warehouse_name"],
    "lat"          : ["lat", "latitude", "depot_lat", "entrepot_lat"],
    "lng"          : ["lng", "longitude", "depot_lng", "entrepot_lng"],
    "opening_time" : ["opening_time", "heure_ouverture", "open_at", "debut"],
    "closing_time" : ["closing_time", "heure_fermeture", "close_at", "fin"],
}

# ─── Conversions de poids ──────────────────────────────────────────────────────
#
# Addinn peut envoyer le poids en grammes ou en tonnes
# On détecte automatiquement et on convertit en kg

WEIGHT_UNIT_HINT = "kg"   # ← change en "g" ou "t" si Addinn envoie dans une autre unité


# ─── Utilitaires ──────────────────────────────────────────────────────────────

class AdapterError(Exception):
    """Erreur levée si l'adaptation échoue."""
    pass


def _resolve(obj: dict, candidates: list, default: Any = None) -> Any:
    """
    Cherche dans obj le premier champ dont le nom est dans candidates.
    Retourne default si aucun n'est trouvé.
    """
    for key in candidates:
        if key in obj:
            return obj[key]
    return default


def _convert_weight(raw_value, unit: str = "kg") -> float:
    """
    Convertit un poids brut en kg selon l'unité déclarée.
    unit : "kg" | "g" | "t"
    """
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        raise AdapterError(f"Poids invalide : {raw_value!r}")

    if unit == "g":
        return value / 1000.0
    elif unit == "t":
        return value * 1000.0
    else:
        return value   # déjà en kg


def _adapt_record(raw: dict, mapping: dict, context: str) -> dict:
    """
    Applique un mapping sur un enregistrement brut.
    Retourne un dict avec les clés internes.
    """
    result = {}
    for internal_key, candidates in mapping.items():
        result[internal_key] = _resolve(raw, candidates)
    return result


# ─── Adaptateurs par section ──────────────────────────────────────────────────

def _adapt_depot(raw_depot: dict) -> dict:
    """Adapte le dépôt Addinn vers le format interne."""
    if not raw_depot:
        raise AdapterError("Le dépôt est absent des données Addinn.")

    adapted = _adapt_record(raw_depot, DEPOT_MAP, "depot")

    # fallback id si toujours None
    if adapted["id"] is None:
        adapted["id"] = "depot_0"

    return {k: v for k, v in adapted.items() if v is not None}


def _adapt_vehicles(raw_vehicles: list) -> list:
    """Adapte la liste des véhicules Addinn vers le format interne."""
    if not raw_vehicles:
        raise AdapterError("La liste des véhicules est absente des données Addinn.")

    adapted = []
    for i, v in enumerate(raw_vehicles):
        record = _adapt_record(v, VEHICLES_MAP, f"vehicle[{i}]")

        # ID par défaut si manquant
        if record["id"] is None:
            record["id"] = f"v{i+1}"

        adapted.append({k: val for k, val in record.items() if val is not None})

    return adapted


def _adapt_orders(raw_orders: list) -> list:
    """Adapte la liste des commandes Addinn vers le format interne."""
    if not raw_orders:
        raise AdapterError("La liste des commandes est absente des données Addinn.")

    adapted = []
    for i, o in enumerate(raw_orders):
        record = _adapt_record(o, ORDERS_MAP, f"order[{i}]")

        # ID par défaut si manquant
        if record["id"] is None:
            record["id"] = f"o{i+1}"

        # Conversion poids selon unité Addinn
        if record.get("weight") is not None:
            record["weight"] = _convert_weight(record["weight"], WEIGHT_UNIT_HINT)

        adapted.append({k: val for k, val in record.items() if val is not None})

    return adapted


# ─── Fonction principale ──────────────────────────────────────────────────────

def adapt(raw_addinn: dict) -> dict:
    """
    Transforme une réponse brute de l'API Addinn vers le format
    interne standard attendu par cleaner.py.

    Parameters
    ----------
    raw_addinn : dict
        Données brutes récupérées depuis l'API Addinn.
        Structure attendue (noms de clés flexibles) :
        {
            "depot"    : { ... },
            "vehicles" : [ ... ],
            "orders"   : [ ... ]
        }

    Returns
    -------
    dict au format interne :
        {
            "scenario" : "ADDINN_LIVE",
            "depot"    : { id, name, lat, lng, ... },
            "vehicles" : [ { id, capacity, type, ... }, ... ],
            "orders"   : [ { id, lat, lng, weight, ... }, ... ]
        }

    Raises
    ------
    AdapterError : si les données sont trop incomplètes pour être adaptées.
    """

    # ── Détecte la structure racine ───────────────────────────────────────────
    # Addinn peut envoyer { "data": { "orders": [...] } } ou directement { "orders": [...] }
    if "data" in raw_addinn:
        raw_addinn = raw_addinn["data"]

    # Cherche les 3 sections principales avec noms alternatifs
    raw_depot    = _resolve(raw_addinn, ["depot", "entrepot", "warehouse", "depot_info"])
    raw_vehicles = _resolve(raw_addinn, ["vehicles", "vehicules", "camions", "fleet", "trucks"], [])
    raw_orders   = _resolve(raw_addinn, ["orders", "commandes", "deliveries", "livraisons"], [])

    print("\n🔄 Adaptation des données Addinn...")

    depot    = _adapt_depot(raw_depot)
    vehicles = _adapt_vehicles(raw_vehicles)
    orders   = _adapt_orders(raw_orders)

    print(f"  ✅ Dépôt adapté    : {depot.get('id')}")
    print(f"  ✅ Véhicules       : {len(vehicles)}")
    print(f"  ✅ Commandes       : {len(orders)}")

    return {
        "scenario" : "ADDINN_LIVE",
        "depot"    : depot,
        "vehicles" : vehicles,
        "orders"   : orders,
    }


# ─── Mise à jour du mapping ────────────────────────────────────────────────────

def update_mapping(section: str, internal_key: str, new_candidates: list):
    """
    Met à jour dynamiquement un mapping quand tu connais le vrai format Addinn.

    Utilisation :
        from core.preprocessing.data_adapter import update_mapping
        update_mapping("orders", "lat", ["gps_latitude", "coord_lat"])

    Parameters
    ----------
    section       : "orders" | "vehicles" | "depot"
    internal_key  : clé interne à mettre à jour (ex: "lat")
    new_candidates: nouveaux noms Addinn à ajouter en tête de liste
    """
    maps = {"orders": ORDERS_MAP, "vehicles": VEHICLES_MAP, "depot": DEPOT_MAP}

    if section not in maps:
        raise AdapterError(f"Section inconnue : '{section}'. Choisir parmi : {list(maps.keys())}")
    if internal_key not in maps[section]:
        raise AdapterError(f"Clé inconnue '{internal_key}' dans section '{section}'.")

    # Ajoute les nouveaux candidats en tête (priorité maximale)
    existing = maps[section][internal_key]
    maps[section][internal_key] = new_candidates + [c for c in existing if c not in new_candidates]
    print(f"  ✅ Mapping mis à jour : {section}.{internal_key} → {maps[section][internal_key]}")