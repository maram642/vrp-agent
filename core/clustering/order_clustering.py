"""
core/clustering/order_clustering.py
--------------------------------------
Découpe une liste de commandes en N clusters géographiques
via KMeans (scikit-learn).

Responsabilité unique :
    Recevoir une liste de commandes + nb_clusters
    → retourner N groupes de commandes

Pourquoi KMeans ?
    Les commandes proches géographiquement forment
    naturellement de bonnes tournées locales.
    KMeans minimise la distance intra-cluster.

Utilisé par :
    strategy_selector._solve_with_clustering()

Règle clustering (définie dans vrp_classifier) :
    < 500    commandes → pas appelé (VRP direct)
    500-1000 commandes → appelé (recommandé)
    > 1000   commandes → appelé (obligatoire)
"""

import numpy as np
from sklearn.cluster import KMeans


# ─── Erreur personnalisée ─────────────────────────────────────────────────────

class ClusteringError(Exception):
    pass


# ─── Fonction principale ──────────────────────────────────────────────────────

def cluster_orders(orders: list, nb_clusters: int) -> list:
    """
    Découpe les commandes en N clusters géographiques via KMeans.

    Parameters
    ----------
    orders      : liste de commandes (format interne cleaner)
                  chaque commande doit avoir "lat" et "lng"
    nb_clusters : nombre de clusters souhaités
                  calculé par vrp_classifier._decide_clustering()

    Returns
    -------
    list de N listes de commandes
    Exemple :
        [
            [order1, order5, order8, ...],   # cluster 0
            [order2, order4, order9, ...],   # cluster 1
            ...
        ]

    Raises
    ------
    ClusteringError : si les données sont insuffisantes
    """

    # ── Validations ───────────────────────────────────────────────────────────
    if not orders:
        raise ClusteringError("La liste des commandes est vide.")

    if nb_clusters < 2:
        raise ClusteringError(
            f"nb_clusters doit être >= 2. Reçu : {nb_clusters}"
        )

    if nb_clusters > len(orders):
        # plus de clusters que de commandes → ajuster
        nb_clusters = len(orders)
        print(f"  ⚠️  nb_clusters ajusté à {nb_clusters} "
              f"(= nb de commandes)")

    # ── Extraction des coordonnées GPS ────────────────────────────────────────
    coords = np.array([
        [o["lat"], o["lng"]]
        for o in orders
    ])

    # ── KMeans ────────────────────────────────────────────────────────────────
    # n_init=10  → lance 10 initialisations aléatoires, garde la meilleure
    # random_state=42 → résultats reproductibles
    kmeans = KMeans(
        n_clusters   = nb_clusters,
        n_init       = 10,
        random_state = 42,
    )
    kmeans.fit(coords)

    # ── Regroupement des commandes par cluster ────────────────────────────────
    clusters = [[] for _ in range(nb_clusters)]

    for i, order in enumerate(orders):
        cluster_id = int(kmeans.labels_[i])
        clusters[cluster_id].append(order)

    # ── Nettoyage : supprimer les clusters vides ──────────────────────────────
    # (rare mais possible si toutes les commandes ont les mêmes coords)
    clusters = [c for c in clusters if c]

    # ── Stats console ─────────────────────────────────────────────────────────
    sizes = [len(c) for c in clusters]
    print(f"\n  📊 Clustering terminé")
    print(f"     Clusters créés  : {len(clusters)}")
    print(f"     Taille min      : {min(sizes)} commandes")
    print(f"     Taille max      : {max(sizes)} commandes")
    print(f"     Taille moyenne  : {sum(sizes)//len(sizes)} commandes")

    return clusters


# ─── Utilitaire : afficher la répartition ────────────────────────────────────

def describe_clusters(clusters: list) -> None:
    """
    Affiche un résumé de chaque cluster.
    Utile pour déboguer ou vérifier la qualité du clustering.
    """
    print(f"\n  🗺️  Répartition des clusters :")
    for i, cluster in enumerate(clusters):
        total_weight = sum(o["weight"] for o in cluster)
        lats = [o["lat"] for o in cluster]
        lngs = [o["lng"] for o in cluster]
        center_lat = sum(lats) / len(lats)
        center_lng = sum(lngs) / len(lngs)
        print(
            f"     Cluster {i+1:02d} : "
            f"{len(cluster):3d} commandes | "
            f"poids total : {total_weight:.0f} kg | "
            f"centre : ({center_lat:.4f}, {center_lng:.4f})"
        )