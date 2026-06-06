

from collections import defaultdict

from core.clustering.order_clustering     import cluster_orders
from core.constraints.constraint_manager  import build_constraints
from core.solvers.vrp_solver              import solve


# ─── Résultat final ───────────────────────────────────────────────────────────

class StrategyResult:
    def __init__(self, routes: list, meta: dict):
        self.routes = routes
        self.meta   = meta

    def __repr__(self):
        lines = [
            f"\n{'─'*54}",
            f"  ✅ Solution finale",
            f"{'─'*54}",
            f"  🚛 Routes générées    : {len(self.routes)}",
            f"  📦 Commandes résolues : {self.meta.get('nb_orders_solved', '?')}",
            f"  📏 Distance totale    : {self.meta.get('total_distance_km', '?')} km",
            f"  🔢 Clusters résolus   : {self.meta.get('nb_clusters_solved', 1)}",
            f"{'─'*54}",
        ]
        return "\n".join(lines)


# ─── Assemblage ───────────────────────────────────────────────────────────────

def _assemble_solutions(cluster_solutions: list) -> StrategyResult:
    all_routes     = []
    total_orders   = 0
    total_distance = 0.0

    for sol in cluster_solutions:
        all_routes.extend(sol.get("routes", []))
        total_orders   += sol.get("nb_orders", 0)
        total_distance += sol.get("total_distance_km", 0.0)

    return StrategyResult(
        routes = all_routes,
        meta   = {
            "nb_orders_solved"  : total_orders,
            "total_distance_km" : round(total_distance, 2),
            "nb_clusters_solved": len(cluster_solutions),
        }
    )


# ─── Distribution des véhicules ───────────────────────────────────────────────

def _assign_vehicles_to_cluster(
    all_vehicles : list,
    cluster_idx  : int,
    nb_clusters  : int,
) -> list:
 

    # grouper par type dynamiquement — aucun type supposé
    by_type = defaultdict(list)
    for v in all_vehicles:
        vtype = v.get("type", "standard")
        by_type[vtype].append(v)

    assigned = []

    for vtype, vehicles in by_type.items():
        nb    = len(vehicles)
        base  = nb // nb_clusters
        extra = nb % nb_clusters
        start = cluster_idx * base + min(cluster_idx, extra)
        end   = start + base + (1 if cluster_idx < extra else 0)
        chunk = vehicles[start:end]
        assigned.extend(chunk)

    # garantir au moins 1 véhicule par cluster
    if not assigned:
        assigned = [all_vehicles[cluster_idx % len(all_vehicles)]]

    return assigned


# ─── Résolution directe ───────────────────────────────────────────────────────

def _solve_direct(dataset: dict, profile) -> StrategyResult:
    """Résout en une seule passe OR-Tools. Utilisé si nb_orders < 500."""
    print("\n  🚀 Résolution directe — pas de clustering")
    constraints = build_constraints(profile, dataset)
    solution    = solve(dataset, constraints)
    return _assemble_solutions([solution])


# ─── Résolution avec clustering ──────────────────────────────────────────────

def _solve_with_clustering(dataset: dict, profile) -> StrategyResult:
    """
    Découpe les commandes en clusters puis résout chaque cluster.
    Chaque véhicule est assigné à un seul cluster.
    """
    nb_clusters = profile.nb_clusters
    print(f"\n  🗺️  Clustering → {nb_clusters} clusters")

    # ── Étape 1 : découper les commandes ──────────────────────────────────────
    clusters = cluster_orders(
        orders      = dataset["orders"],
        nb_clusters = nb_clusters,
    )
    print(f"  ✅ {len(clusters)} clusters créés")

    # ── Étape 2 : résoudre chaque cluster ─────────────────────────────────────
    cluster_solutions = []

    for i, cluster_orders_list in enumerate(clusters):
        print(f"\n  🔄 Cluster {i+1}/{len(clusters)} "
              f"— {len(cluster_orders_list)} commandes")

        # distribuer les véhicules : chaque véhicule dans 1 seul cluster
        assigned_vehicles = _assign_vehicles_to_cluster(
            all_vehicles = dataset["vehicles"],
            cluster_idx  = i,
            nb_clusters  = len(clusters),
        )

        print(f"     Véhicules assignés : {len(assigned_vehicles)} "
              f"({[v['id'] for v in assigned_vehicles]})")

        cluster_dataset = {
            "scenario" : dataset.get("scenario", "CLUSTER"),
            "depot"    : dataset["depot"],
            "vehicles" : assigned_vehicles,
            "orders"   : cluster_orders_list,
        }

        if profile.is_multi_depot and "depots" in dataset:
            cluster_dataset["depots"] = dataset["depots"]

        constraints = build_constraints(profile, cluster_dataset)
        solution    = solve(cluster_dataset, constraints)
        cluster_solutions.append(solution)

    # ── Étape 3 : assembler ───────────────────────────────────────────────────
    return _assemble_solutions(cluster_solutions)


# ─── Fonction principale ──────────────────────────────────────────────────────

def run(dataset: dict, profile) -> StrategyResult:

    nb_orders = profile.meta["nb_orders"]

    print(f"\n{'─'*54}")
    print(f"  ⚙️  Strategy Selector")
    print(f"  📦 {nb_orders} commandes | "
          f"clustering : {profile.clustering['mode']}")
    print(f"{'─'*54}")

    if profile.needs_clustering:
        return _solve_with_clustering(dataset, profile)
    else:
        return _solve_direct(dataset, profile)