"""
core/solvers/vrp_solver.py
----------------------------
Solver VRP universel basé sur Google OR-Tools.

Correction multi-dépôt :
    starts/ends utilisent config.depot_indices — les vrais indices
    des dépôts dans la matrice de distances.

    Dépôt unique  : depot_indices = [0]
    Multi-dépôt   : depot_indices = [0, 1, 2, ...]

    Chaque véhicule est assigné à un dépôt réel.
    Les callbacks tiennent compte du décalage nb_depots.
"""

from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp


# ─── Paramètres ───────────────────────────────────────────────────────────────

TIME_LIMIT_SECONDS         = 30
HORIZON_MINUTES            = 1440
FIRST_SOLUTION_STRATEGY    = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
LOCAL_SEARCH_METAHEURISTIC = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH


class SolverError(Exception):
    pass


# ─── Callbacks ────────────────────────────────────────────────────────────────

def _make_distance_callback(config, manager):
    matrix = config.distance_matrix

    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node   = manager.IndexToNode(to_index)
        return int(matrix[from_node][to_node] * 1000)

    return distance_callback


def _make_demand_callback(config, manager, nb_depots: int):
    """
    Demande (poids) par noeud.
    Les dépôts (index 0..nb_depots-1) ont demande = 0.
    Les commandes (index nb_depots..N) ont leur poids.
    """
    demands = [0] * nb_depots + [int(o["weight"]) for o in config.orders]

    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return demands[from_node]

    return demand_callback


def _make_time_callback(config, manager, nb_depots: int):
    """
    Temps de trajet + service.
    Tient compte du décalage nb_depots dans service_times.
    """
    matrix        = config.distance_matrix
    service_times = config.service_times
    speed_kmh     = 30.0

    def time_callback(from_index, to_index):
        from_node  = manager.IndexToNode(from_index)
        to_node    = manager.IndexToNode(to_index)
        travel_min = (matrix[from_node][to_node] / speed_kmh) * 60
        service    = service_times[to_node] if  to_node < len(service_times) else 0
        return int(travel_min + service)

    return time_callback


# ─── Construction du modèle ───────────────────────────────────────────────────

def _build_model(config):
    """
    Construit le modèle OR-Tools.

    Multi-dépôt :
        starts/ends = vrais indices des dépôts dans la matrice
        chaque véhicule est assigné à un dépôt réel
        les callbacks tiennent compte du décalage nb_depots

    Dépôt unique :
        comportement classique, nb_depots = 1
    """
    nb_orders   = len(config.orders)
    nb_vehicles = len(config.vehicles)
    nb_depots   = len(config.depot_indices)
    nb_locs     = nb_depots + nb_orders

    # ── 1. Manager ────────────────────────────────────────────────────────────
    if nb_depots > 1:
        # multi-dépôt : chaque véhicule part et revient à son dépôt réel
        starts = []
        ends   = []
        for i in range(nb_vehicles):
            # assigner les véhicules aux dépôts en round-robin
            depot_real_idx = config.depot_indices[i % nb_depots]
            starts.append(depot_real_idx)
            ends.append(depot_real_idx)

        manager = pywrapcp.RoutingIndexManager(
            nb_locs,
            nb_vehicles,
            starts,
            ends,
        )
    else:
        # dépôt unique — comportement classique
        manager = pywrapcp.RoutingIndexManager(
            nb_locs,
            nb_vehicles,
            0,  # depot index = 0
        )

    routing = pywrapcp.RoutingModel(manager)

    # ── 2. Distance + coût ────────────────────────────────────────────────────
    dist_cb_idx = routing.RegisterTransitCallback(
        _make_distance_callback(config, manager)
    )
    routing.SetArcCostEvaluatorOfAllVehicles(dist_cb_idx)

    # ── 3. Capacité (toujours) ────────────────────────────────────────────────
    demand_cb_idx = routing.RegisterUnaryTransitCallback(
        _make_demand_callback(config, manager, nb_depots)
    )
    routing.AddDimensionWithVehicleCapacity(
        demand_cb_idx,
        0,
        config.capacities,
        True,
        "Capacity",
    )

    # ── 4. Time windows ───────────────────────────────────────────────────────
    if config.time_windows:
        time_cb_idx = routing.RegisterTransitCallback(
            _make_time_callback(config, manager, nb_depots)
        )
        routing.AddDimension(
            time_cb_idx,
            HORIZON_MINUTES,
            HORIZON_MINUTES,
            False,
            "Time",
        )
        time_dimension = routing.GetDimensionOrDie("Time")

        for node_idx, (start, end) in enumerate(config.time_windows):
            index = manager.NodeToIndex(node_idx)
            time_dimension.CumulVar(index).SetRange(start, end)

        max_durations = config.max_durations
        if max_durations:
            for v_idx in range(nb_vehicles):
                max_min   = max_durations[v_idx] if v_idx < len(max_durations) else HORIZON_MINUTES
                start_var = time_dimension.CumulVar(routing.Start(v_idx))
                end_var   = time_dimension.CumulVar(routing.End(v_idx))
                routing.solver().Add(end_var - start_var <= max_min)
                routing.AddVariableMinimizedByFinalizer(start_var)
                routing.AddVariableMinimizedByFinalizer(end_var)

    # ── 5. Restrictions véhicules ─────────────────────────────────────────────
    if config.vehicle_allowed:
        for node_idx, allowed_vehicles in config.vehicle_allowed.items():
            index = manager.NodeToIndex(node_idx)
            for v_idx in range(nb_vehicles):
                if v_idx not in allowed_vehicles:
                    routing.VehicleVar(index).RemoveValue(v_idx)

    # ── 6. Pénalités ──────────────────────────────────────────────────────────
    priority_map = {1: 10_000_000, 2: 5_000_000, 3: 1_000_000}

    for i in range(nb_orders):
        node_idx = nb_depots + i   # ← décalage correct
        index    = manager.NodeToIndex(node_idx)

        if config.priorities and node_idx in config.priorities:
            level   = config.priorities[node_idx]
            penalty = priority_map.get(level, 1_000_000)
        else:
            penalty = 1_000_000

        routing.AddDisjunction([index], penalty)

    return manager, routing, nb_depots


# ─── Extraction ───────────────────────────────────────────────────────────────

def _extract_solution(manager, routing, solution, config, nb_depots) -> dict:
    """
    Extrait la solution. Tient compte du décalage nb_depots
    pour retrouver la commande correcte depuis son index dans la matrice.
    """
    routes           = []
    total_distance   = 0.0
    served_order_ids = set()

    for v_idx, vehicle in enumerate(config.vehicles):
        # dans _extract_solution, au début de la boucle véhicule
        start_node   = manager.IndexToNode(routing.Start(v_idx))
        depot_id     = "depot_0"  # défaut

        if config.depots and start_node < len(config.depots):
            depot_id = config.depots[start_node]["id"]
        elif config.depot:
            depot_id = config.depot.get("id", "depot_0")
        index = routing.Start(v_idx)

        if routing.IsEnd(solution.Value(routing.NextVar(index))):
            continue

        route        = []
        route_dist   = 0.0
        route_weight = 0.0

        while not routing.IsEnd(index):
            node       = manager.IndexToNode(index)
            next_index = solution.Value(routing.NextVar(index))

            arc_dist    = routing.GetArcCostForVehicle(index, next_index, v_idx) / 1000.0
            route_dist += arc_dist

            # les dépôts ont index < nb_depots → ignorer
            if node >= nb_depots:
                order_idx = node - nb_depots   # ← décalage correct
                order     = config.orders[order_idx]
                served_order_ids.add(order["id"])

                arrival_min = None
                if config.time_windows:
                    time_dim    = routing.GetDimensionOrDie("Time")
                    arrival_min = solution.Min(time_dim.CumulVar(index))

                route.append({
                    "order_id"   : order["id"],
                    "client"     : order.get("client", ""),
                    "lat"        : order["lat"],
                    "lng"        : order["lng"],
                    "weight_kg"  : order["weight"],
                    "arrival_min": arrival_min,
                })
                route_weight += order["weight"]

            index = next_index

        total_distance += route_dist

        routes.append({
            "vehicle_id"        : vehicle["id"],
            "vehicle_type"      : vehicle.get("type", "standard"),
            "vehicle_capacity"  : vehicle["capacity"],
            "depot_id"          : depot_id,  
            "stops"             : route,
            "total_distance_km" : round(route_dist, 2),
            "total_weight_kg"   : round(route_weight, 1),
            "nb_stops"          : len(route),
        })

    all_order_ids   = {o["id"] for o in config.orders}
    unserved_orders = list(all_order_ids - served_order_ids)

    return {
        "routes"            : routes,
        "nb_orders"         : len(served_order_ids),
        "total_distance_km" : round(total_distance, 2),
        "unserved_orders"   : unserved_orders,
    }


# ─── Fonction principale ──────────────────────────────────────────────────────

def solve(dataset: dict, config) -> dict:
    """
    Résout le VRP avec OR-Tools selon le ConstraintConfig.
    Gère dépôt unique et multi-dépôt via config.depot_indices.
    """
    nb_orders   = len(config.orders)
    nb_vehicles = len(config.vehicles)

    print(f"\n  🔧 OR-Tools — {nb_orders} commandes, "
          f"{nb_vehicles} véhicules, "
          f"{len(config.depot_indices)} dépôt(s)")

    manager, routing, nb_depots = _build_model(config)

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy    = FIRST_SOLUTION_STRATEGY
    search_params.local_search_metaheuristic = LOCAL_SEARCH_METAHEURISTIC
    search_params.time_limit.FromSeconds(TIME_LIMIT_SECONDS)

    solution = routing.SolveWithParameters(search_params)

    if not solution:
        raise SolverError(
            f"OR-Tools n'a pas trouvé de solution "
            f"({nb_orders} commandes, {nb_vehicles} véhicules, "
            f"{len(config.depot_indices)} dépôts)."
        )

    result = _extract_solution(manager, routing, solution, config, nb_depots)

    print(f"  ✅ Solution trouvée")
    print(f"     Routes           : {len(result['routes'])}")
    print(f"     Commandes livrées: {result['nb_orders']} / {nb_orders}")
    print(f"     Distance totale  : {result['total_distance_km']} km")

    if result["unserved_orders"]:
        print(f"  ⚠️  Non livrées ({len(result['unserved_orders'])}) : "
              f"{result['unserved_orders'][:5]}")

    return result