"""
core/classification/vrp_classifier.py
---------------------------------------
Scanne un dataset propre et retourne un ProblemProfile —
l'ensemble complet des flags actifs dans les données.

Principe fondamental :
    Le classifier ne choisit PAS un type unique (CVRP, VRPTW...).
    Ces types ne sont PAS des solvers différents.
    Ce sont des configurations d'un même problème VRP.

    Le classifier répond à UNE seule question :
        "Quelles contraintes sont présentes dans ces données ?"

    Ensuite :
        strategy_selector  → lit le profil, gère le clustering
        constraint_manager → lit le profil, construit les blocs OR-Tools
        vrp_solver         → UN SEUL solver, reçoit les contraintes

Règle clustering :
    < 500    commandes → VRP direct
    500-1000 commandes → clustering recommandé
    > 1000   commandes → clustering obligatoire
"""

# ─── Seuils clustering ────────────────────────────────────────────────────────

CLUSTERING_RECOMMENDED = 500
CLUSTERING_MANDATORY   = 1000


# ─── Profil du problème ───────────────────────────────────────────────────────

class ProblemProfile:
    """
    Résultat du classifier.
    Contient TOUS les flags actifs dans les données.

    Transmis à :
        strategy_selector  → décide clustering ou direct
        constraint_manager → construit les contraintes OR-Tools
        vrp_solver         → reçoit les contraintes construites
    """

    def __init__(self, flags: dict, clustering: dict, meta: dict):
        self.flags      = flags
        self.clustering = clustering
        self.meta       = meta

    # ── Accès direct aux flags ────────────────────────────────────────────────

    @property
    def has_time_windows(self) -> bool:
        return self.flags["has_time_windows"]

    @property
    def has_pickup_delivery(self) -> bool:
        return self.flags["has_pickup_delivery"]

  

    @property
    def is_multi_depot(self) -> bool:
        return self.flags["is_multi_depot"]

    @property
    def needs_refrigeration(self) -> bool:
        return self.flags["needs_refrigeration"]

    @property
    def has_priorities(self) -> bool:
        return self.flags["has_priorities"]

    @property
    def has_service_times(self) -> bool:
        return self.flags["has_service_times"]

    @property
    def needs_clustering(self) -> bool:
        return self.clustering["needed"]

    @property
    def nb_clusters(self) -> int:
        return self.clustering["nb_clusters"]

    def active_flags(self) -> list:
        """Retourne uniquement les flags True."""
        return [k for k, v in self.flags.items() if v is True]

    def summary(self) -> str:
        """Résumé en une ligne pour les logs."""
        active = self.active_flags()
        clustering_info = (
            f"clustering={self.clustering['nb_clusters']} clusters"
            if self.clustering["needed"]
            else "direct"
        )
        return f"flags={active} | {clustering_info}"

    def __repr__(self):
        active = self.active_flags()
        lines = [
            f"\n{'─'*54}",
            f"  🔎 Profil VRP — scanner complet",
            f"{'─'*54}",
            f"  📦 Commandes          : {self.meta['nb_orders']}",
            f"  🚛 Véhicules          : {self.meta['nb_vehicles']}",
            f"  📊 Types véhicules    : {self.meta['vehicle_types']}",
            f"{'─'*54}",
            f"  — Contraintes structurelles —",
            f"  ✅ Capacité           : toujours active",
            f"  ⏰ Time windows       : {self.flags['has_time_windows']}",
            f"  🔄 Pickup & Delivery  : {self.flags['has_pickup_delivery']}",
         
            f"  🏭 Multi-dépôt        : {self.flags['is_multi_depot']}",
            f"{'─'*54}",
            f"  — Contraintes métier —",
            f"  🧊 Chaîne du froid    : {self.flags['needs_refrigeration']}",
            f"  ⭐ Priorités clients  : {self.flags['has_priorities']}",
            f"  ⏱️  Temps de service   : {self.flags['has_service_times']}",
            f"{'─'*54}",
            f"  🟢 Flags actifs       : {active if active else ['capacity only']}",
            f"{'─'*54}",
            f"  🗺️  Clustering         : {self.clustering['mode']}",
        ]
        if self.clustering["needed"]:
            lines.append(
                f"  🔢 Nb clusters        : {self.clustering['nb_clusters']}"
            )
        if self.meta.get("overloaded_orders"):
            lines.append(
                f"  ⚠️  Commandes trop lourdes : "
                f"{self.meta['overloaded_orders'][:5]}"
            )
        lines.append(f"{'─'*54}")
        return "\n".join(lines)


# ─── Fonctions de détection ───────────────────────────────────────────────────

def _detect_time_windows(orders: list) -> bool:
    """True si au moins une commande a un créneau horaire."""
    return any(o.get("time_window") is not None for o in orders)


def _detect_pickup_delivery(orders: list) -> bool:
    """
    True si au moins une commande a un point de ramassage distinct du dépôt.
    Ex: enlever chez client A, livrer chez client B.
    """
    return any("pickup_lat" in o or "pickup" in o for o in orders)





def _detect_multi_depot(dataset: dict) -> bool:
    """
    True si le dataset contient plusieurs dépôts.
    Addinn peut envoyer "depots": [...] au lieu d'un seul "depot".
    """
    return (
        isinstance(dataset.get("depots"), list)
        and len(dataset["depots"]) > 1
    )


def _detect_refrigeration(orders: list) -> bool:
    """True si au moins une commande nécessite un véhicule frigorifique."""
    return any(o.get("requires_refrigeration", False) for o in orders)


def _detect_priorities(orders: list) -> bool:
    """True si au moins une commande a un champ priorité."""
    return any("priority" in o for o in orders)


def _detect_service_times(orders: list) -> bool:
    """True si au moins une commande a un temps de service > 0."""
    return any(o.get("service_time_min", 0) > 0 for o in orders)


def _detect_vehicle_types(vehicles: list) -> set:
    return set(v.get("type", "standard") for v in vehicles)


def _detect_overloaded(orders: list, vehicles: list) -> list:
    """Commandes impossibles à livrer (poids > capacité max véhicule)."""
    max_cap = max(v["capacity"] for v in vehicles)
    return [o["id"] for o in orders if o["weight"] > max_cap]


# ─── Décision clustering ──────────────────────────────────────────────────────

def _decide_clustering(nb_orders: int, nb_vehicles: int) -> dict:
    """
    Décide si KMeans est nécessaire avant résolution OR-Tools.

        < 500    → VRP direct
        500-1000 → clustering recommandé
        > 1000   → clustering obligatoire

    Nb clusters ≈ nb_orders // 50 (vise ~50 commandes par cluster)
    plafonné au nombre de véhicules disponibles.
    """
    if nb_orders < CLUSTERING_RECOMMENDED:
        return {
            "needed"     : False,
            "mode"       : "Non nécessaire — VRP direct",
            "nb_clusters": 0,
        }

    nb_clusters = min(nb_vehicles, max(2, nb_orders // 50))

    if nb_orders < CLUSTERING_MANDATORY:
        return {
            "needed"     : True,
            "mode"       : "Recommandé",
            "nb_clusters": nb_clusters,
        }

    return {
        "needed"     : True,
        "mode"       : "Obligatoire",
        "nb_clusters": nb_clusters,
    }


# ─── Fonction principale ──────────────────────────────────────────────────────

def classify(dataset: dict) -> ProblemProfile:
    """
    Scanne un dataset propre et retourne un ProblemProfile complet.

    Le classifier coche TOUS les flags présents dans les données.
    Il ne choisit PAS un type unique — il laisse
    strategy_selector et constraint_manager décider quoi faire.

    Parameters
    ----------
    dataset : dict
        Sorti de cleaner.load_and_clean().

    Returns
    -------
    ProblemProfile
        .flags      → tous les booléens détectés
        .clustering → { needed, mode, nb_clusters }
        .meta       → { nb_orders, nb_vehicles, vehicle_types, ... }
    """

    vehicles = dataset["vehicles"]
    orders   = dataset["orders"]
    nb_orders   = len(orders)
    nb_vehicles = len(vehicles)

    # ── Scan complet — chaque flag est indépendant ────────────────────────────
    flags = {
        # contraintes structurelles
        "has_capacity"        : True,
        "has_time_windows"    : _detect_time_windows(orders),
        "has_pickup_delivery" : _detect_pickup_delivery(orders),
    
        "is_multi_depot"      : _detect_multi_depot(dataset),
        # contraintes métier → constraint_manager les applique
        "needs_refrigeration" : _detect_refrigeration(orders),
        "has_priorities"      : _detect_priorities(orders),
        "has_service_times"   : _detect_service_times(orders),
    }

    clustering = _decide_clustering(nb_orders, nb_vehicles)

    vehicle_types = _detect_vehicle_types(vehicles)
    meta = {
        "nb_orders"        : nb_orders,
        "nb_vehicles"      : nb_vehicles,
        "vehicle_types"    : vehicle_types,
        "nb_vehicle_types" : len(vehicle_types),
        "overloaded_orders": _detect_overloaded(orders, vehicles),
    }

    profile = ProblemProfile(flags, clustering, meta)
    print(profile)
    return profile