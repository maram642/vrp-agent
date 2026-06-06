

import json
import math
from pathlib import Path
from typing import Optional


# ─── Config frigorifique ──────────────────────────────────────────────────────

def _load_fridge_types() -> list:
    config_path = Path("constraints_config.json")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("refrigerated_vehicle_types", ["refrigerated"])
        except Exception:
            pass
    return ["refrigerated"]


FRIDGE_TYPES = _load_fridge_types()


# ─── Erreur ───────────────────────────────────────────────────────────────────

class ConstraintError(Exception):
    pass


# ─── Conteneur ────────────────────────────────────────────────────────────────

class ConstraintConfig:
  

    def __init__(self):
        self.vehicles        = []
        self.orders          = []
        self.depot           = {}
        self.distance_matrix = []
        self.depot_indices   = [0]   # ← indices réels des dépôts dans la matrice
        self.capacities      = []
        self.max_durations   = []
        self.time_windows    = None
        self.service_times   = []
        self.vehicle_allowed = {}
        self.priorities      = None
        self.depots          = None
        self.flags           = {}

    def __repr__(self):
        n = len(self.distance_matrix)
        lines = [
            f"\n{'─'*52}",
            f"  ConstraintConfig",
            f"{'─'*52}",
            f"  Véhicules disponibles : {len(self.vehicles)}",
            f"  Commandes             : {len(self.orders)}",
            f"  Matrice distances     : {n}×{n}",
            f"  Dépôts indices        : {self.depot_indices}",
            f"  Time windows          : {'Oui' if self.time_windows else 'Non'}",
            f"  Restrictions véhicule : {'Oui' if self.vehicle_allowed else 'Non'}",
            f"  Priorités             : {'Oui' if self.priorities else 'Non'}",
            f"  Multi-dépôt           : {'Oui' if self.depots else 'Non'}",
            f"{'─'*52}",
        ]
        return "\n".join(lines)


# ─── Utilitaires ─────────────────────────────────────────────────────────────

def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    R    = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a    = (math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2)
            * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _time_to_minutes(t: str) -> int:
    try:
        h, m = map(int, t.split(":"))
        return h * 60 + m
    except Exception:
        return 0


# ─── Matrice de distances ─────────────────────────────────────────────────────

def _build_distance_matrix(depot: dict, orders: list) -> list:
    
    points = [(depot["lat"], depot["lng"])] + [
        (o["lat"], o["lng"]) for o in orders
    ]
    n      = len(points)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                matrix[i][j] = _haversine_km(
                    points[i][0], points[i][1],
                    points[j][0], points[j][1],
                )
    return matrix


def _build_distance_matrix_multi_depot(depots: list, orders: list) -> list:

    depot_points = [(d["lat"], d["lng"]) for d in depots]
    order_points = [(o["lat"], o["lng"]) for o in orders]
    points       = depot_points + order_points   # dépôts AVANT commandes

    n      = len(points)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                matrix[i][j] = _haversine_km(
                    points[i][0], points[i][1],
                    points[j][0], points[j][1],
                )
    return matrix


# ─── Blocs de contraintes ─────────────────────────────────────────────────────

def _build_capacities(vehicles: list) -> list:
    return [int(v["capacity"]) for v in vehicles]


def _build_max_durations(vehicles: list) -> list:
    return [int(v.get("max_route_duration_h", 12) * 60) for v in vehicles]


def _build_time_windows(depot: dict, orders: list) -> list:
    """
    Fenêtres de temps. index 0 = dépôt, index 1..N = commandes.
    """
    depot_start = _time_to_minutes(depot.get("opening_time", "00:00"))
    depot_end   = _time_to_minutes(depot.get("closing_time", "23:59"))
    windows     = [(depot_start, depot_end)]
    for o in orders:
        tw = o.get("time_window")
        if tw and tw.get("start") and tw.get("end"):
            windows.append((
                _time_to_minutes(tw["start"]),
                _time_to_minutes(tw["end"]),
            ))
        else:
            windows.append((0, 1440))
    return windows


def _build_time_windows_multi_depot(depots: list, orders: list) -> list:
    """
    Time windows en multi-dépôt.
    index 0..D-1 = dépôts, index D..D+N-1 = commandes.
    """
    windows = []
    for d in depots:
        start = _time_to_minutes(d.get("opening_time", "00:00"))
        end   = _time_to_minutes(d.get("closing_time", "23:59"))
        windows.append((start, end))
    for o in orders:
        tw = o.get("time_window")
        if tw and tw.get("start") and tw.get("end"):
            windows.append((
                _time_to_minutes(tw["start"]),
                _time_to_minutes(tw["end"]),
            ))
        else:
            windows.append((0, 1440))
    return windows


def _build_service_times(orders: list, nb_depots: int = 1) -> list:
    
    return [0] * nb_depots + [int(o.get("service_time_min", 0)) for o in orders]


def _build_vehicle_allowed(
    vehicles  : list,
    orders    : list,
    nb_depots : int = 1,
) -> dict:
    
    fridge_indices = [
        i for i, v in enumerate(vehicles)
        if v.get("type", "standard") in FRIDGE_TYPES
    ]
    all_indices = list(range(len(vehicles)))

    needs_fridge = any(
        o.get("requires_refrigeration", False) for o in orders
    )
    if needs_fridge and not fridge_indices:
        raise ConstraintError(
            f"Commandes frigo sans véhicule frigo disponible. "
            f"Types reconnus : {FRIDGE_TYPES}"
        )

    allowed = {}
    for i, o in enumerate(orders):
        node_idx = nb_depots + i   # ← décalage correct selon nb dépôts
        if o.get("requires_refrigeration", False):
            allowed[node_idx] = fridge_indices
        else:
            allowed[node_idx] = all_indices

    return allowed


def _build_priorities(orders: list) -> Optional[dict]:
    has_priorities = any("priority" in o for o in orders)
    if not has_priorities:
        return None
    return {
        i + 1: int(o.get("priority", 3))
        for i, o in enumerate(orders)
        if "priority" in o
    }


# ─── Fonction principale ──────────────────────────────────────────────────────

def build_constraints(profile, dataset: dict) -> ConstraintConfig:
    
    vehicles = dataset["vehicles"]
    orders   = dataset["orders"]

    if not vehicles:
        raise ConstraintError("Aucun véhicule dans ce cluster.")
    if not orders:
        raise ConstraintError("Aucune commande dans ce cluster.")

    config          = ConstraintConfig()
    config.vehicles = vehicles
    config.orders   = orders
    config.flags    = profile.flags

    # ── 1. Matrice distances + indices dépôts ─────────────────────────────────
    if profile.is_multi_depot and "depots" in dataset:
        depots                 = dataset["depots"]
        # dépôt principal = premier dépôt (pour compatibilité)
        depot                  = depots[0]
        config.depot           = depot
        config.depots          = depots
        config.distance_matrix = _build_distance_matrix_multi_depot(
            depots, orders
        )
        config.depot_indices   = list(range(len(depots)))
        nb_depots              = len(depots)
    else:
        # dépôt unique — chercher dans "depot", sinon erreur claire
        depot = dataset.get("depot")
        if not depot:
            raise ConstraintError(
                "Dépôt introuvable dans le dataset. "
                "Vérifier que 'depot' ou 'depots' est présent."
            )
        config.depot           = depot
        config.distance_matrix = _build_distance_matrix(depot, orders)
        config.depot_indices   = [0]
        nb_depots              = 1

    # ── 2. Capacités (toujours) ───────────────────────────────────────────────
    config.capacities = _build_capacities(vehicles)

    # ── 3. Durée max tournée (toujours) ───────────────────────────────────────
    config.max_durations = _build_max_durations(vehicles)

    # ── 4. Time windows ───────────────────────────────────────────────────────
    if profile.has_time_windows:
        if profile.is_multi_depot and "depots" in dataset:
            config.time_windows = _build_time_windows_multi_depot(
                dataset["depots"], orders
            )
        else:
            config.time_windows = _build_time_windows(depot, orders)

    # ── 5. Temps de service ───────────────────────────────────────────────────
    config.service_times = _build_service_times(orders, nb_depots)

    # ── 6. Règles d'autorisation véhicule → commande ──────────────────────────
    config.vehicle_allowed = _build_vehicle_allowed(
        vehicles, orders, nb_depots
    )

    # ── 7. Priorités ──────────────────────────────────────────────────────────
    if profile.has_priorities:
        config.priorities = _build_priorities(orders)

    print(config)
    return config