"""Deterministic, explainable analysis of the organizer's four-hop money graph."""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

ROLES = {"consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"}
NODE_COLUMNS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
CLUSTER_COLUMNS = ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]
TOP_COLUMNS = ["rank", "gid", "role", "priority_score", "why"]


def load_and_validate(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    paths = [data_dir / name for name in ("nodes.parquet", "edges.parquet", "transactions.parquet")]
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Missing input: {path}")
    nodes, edges, tx = (pd.read_parquet(path) for path in paths)
    expected = (
        (nodes, {"gid", "depth", "is_seed"}, 2248, "nodes"),
        (edges, {"src", "dst", "sum_kzt", "n_tx", "depth"}, 3119, "edges"),
        (tx, {"src", "dst", "date", "sum_kzt"}, 4840, "transactions"),
    )
    for frame, columns, count, name in expected:
        if not columns.issubset(frame.columns) or len(frame) != count or frame[list(columns)].isna().any().any():
            raise ValueError(f"{name}: expected {count} rows and non-null columns {sorted(columns)}")
    if nodes.gid.duplicated().any() or edges.duplicated(["src", "dst"]).any():
        raise ValueError("Duplicate gid or aggregated edge")
    gids = set(nodes.gid)
    if not set(edges.src).issubset(gids) or not set(edges.dst).issubset(gids):
        raise ValueError("Edge endpoint missing from nodes")
    if int(nodes.is_seed.sum()) != 81 or not nodes.depth.between(0, 4).all():
        raise ValueError("Unexpected seed count or depth")
    if (edges.sum_kzt <= 0).any() or (edges.n_tx <= 0).any() or (tx.sum_kzt <= 0).any():
        raise ValueError("Non-positive transfer amount or count")
    aggregate = tx.groupby(["src", "dst"], as_index=False).agg(sum_check=("sum_kzt", "sum"), count_check=("sum_kzt", "size"))
    check = edges.merge(aggregate, on=["src", "dst"], how="outer", indicator=True)
    if (check._merge != "both").any() or not np.allclose(check.sum_kzt, check.sum_check, rtol=1e-9, atol=0.01) or not (check.n_tx == check.count_check).all():
        raise ValueError("Aggregated edges disagree with transactions")
    return nodes, edges, tx


def build_graph(nodes: pd.DataFrame, edges: pd.DataFrame) -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_nodes_from(int(gid) for gid in nodes.gid)  # includes isolated seeds
    for row in edges.itertuples(index=False):
        graph.add_edge(int(row.src), int(row.dst), sum_kzt=float(row.sum_kzt), n_tx=int(row.n_tx))
    return graph


def features(nodes: pd.DataFrame, graph: nx.DiGraph) -> pd.DataFrame:
    df = nodes[["gid", "depth", "is_seed"]].copy().sort_values("gid").reset_index(drop=True)
    columns = {
        "in_deg": dict(graph.in_degree()),
        "out_deg": dict(graph.out_degree()),
        "in_kzt": dict(graph.in_degree(weight="sum_kzt")),
        "out_kzt": dict(graph.out_degree(weight="sum_kzt")),
        "in_tx": dict(graph.in_degree(weight="n_tx")),
        "out_tx": dict(graph.out_degree(weight="n_tx")),
        "pagerank": nx.pagerank(graph, weight="sum_kzt"),
    }
    for name, values in columns.items():
        df[name] = df.gid.map(values).fillna(0)
    for name in ("in_deg", "out_deg", "in_tx", "out_tx"):
        df[name] = df[name].astype(int)
    df["seed_reach"] = 0
    reach = {int(gid): 0 for gid in df.gid}
    for seed in sorted(int(gid) for gid in df.loc[df.is_seed, "gid"]):
        for gid in nx.descendants(graph, seed) | {seed}:
            reach[gid] += 1
    df["seed_reach"] = df.gid.map(reach).astype(int)
    df["pass_through"] = np.where(df.in_kzt > 0, df.out_kzt / df.in_kzt.replace(0, np.nan), np.nan)
    df["truncated_by_depth"] = (df.depth == 4) & (df.out_deg == 0)
    return df


def cluster_graph(graph: nx.DiGraph) -> dict[int, int]:
    undirected = nx.Graph()
    undirected.add_nodes_from(graph.nodes)
    for src, dst, data in graph.edges(data=True):
        weight = math.log1p(data["sum_kzt"])
        if undirected.has_edge(src, dst):
            undirected[src][dst]["weight"] += weight
        else:
            undirected.add_edge(src, dst, weight=weight)
    communities = nx.community.louvain_communities(undirected, weight="weight", seed=42)
    ordered = sorted((sorted(group) for group in communities), key=lambda group: group[0])
    return {gid: cluster_id for cluster_id, group in enumerate(ordered) for gid in group}


def percentile(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True).fillna(0.0)


def classify(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    in_positive = df.loc[df.in_deg > 0, "in_deg"]
    out_positive = df.loc[df.out_deg > 0, "out_deg"]
    thresholds = {
        "fan_in": max(3, math.ceil(in_positive.quantile(0.90))),
        "fan_out": max(3, math.ceil(out_positive.quantile(0.90))),
        "in_kzt": float(df.loc[df.in_kzt > 0, "in_kzt"].quantile(0.75)),
        "out_kzt": float(df.loc[df.out_kzt > 0, "out_kzt"].quantile(0.75)),
        "pagerank": float(df.pagerank.quantile(0.98)),
        "flow": float(df.loc[(df.in_kzt > 0) & (df.out_kzt > 0), ["in_kzt", "out_kzt"]].min(axis=1).quantile(0.50)),
    }
    in_rank, out_rank = percentile(df.in_deg), percentile(df.out_deg)
    in_volume_rank, out_volume_rank = percentile(df.in_kzt), percentile(df.out_kzt)
    pr_rank = percentile(df.pagerank)
    roles: list[str] = []
    scores: list[float] = []
    evidence: list[str] = []
    for i, r in enumerate(df.itertuples(index=False)):
        candidates: list[tuple[float, int, str, str]] = []
        if r.in_deg >= thresholds["fan_in"] and r.in_kzt >= thresholds["in_kzt"]:
            score = 0.5 * (in_rank[i] + in_volume_rank[i])
            if r.is_seed:
                score = min(score, 0.65)
            candidates.append((score, 4, "consolidator", f"Получает от {r.in_deg} плательщиков, видимый вход {r.in_kzt:,.0f} KZT; depth={r.depth}."))
        if r.out_deg >= thresholds["fan_out"] and r.out_kzt >= thresholds["out_kzt"]:
            score = 0.5 * (out_rank[i] + out_volume_rank[i])
            candidates.append((score, 3, "distributor", f"Отправляет {r.out_deg} получателям, видимый выход {r.out_kzt:,.0f} KZT; depth={r.depth}."))
        if (not r.is_seed and r.in_deg > 0 and r.out_deg > 0 and
                min(r.in_kzt, r.out_kzt) >= thresholds["flow"] and
                0.8 <= r.pass_through <= 1.2):
            closeness = 1 - min(1, abs(math.log(r.pass_through)) / math.log(1.25))
            score = 0.6 + 0.4 * closeness
            candidates.append((score, 2, "transit", f"Видимый вход {r.in_kzt:,.0f}, выход {r.out_kzt:,.0f} KZT; выход/вход={r.pass_through:.2f}."))
        if (r.in_deg >= 2 and r.out_deg >= 2 and r.seed_reach >= 2 and
                r.pagerank >= thresholds["pagerank"]):
            score = 0.8 + 0.2 * pr_rank[i]
            candidates.append((score, 5, "coordinator", f"Структурный узел: {r.in_deg} входящих, {r.out_deg} исходящих связей; достижим от {r.seed_reach} seed."))
        if r.in_deg > 0 and r.out_deg == 0 and r.depth < 4 and not r.is_seed:
            score = min(0.8, 0.4 + 0.4 * in_volume_rank[i])
            candidates.append((score, 1, "terminal", f"Видимый вход от {r.in_deg} узлов ({r.in_kzt:,.0f} KZT), выхода нет; depth={r.depth}<4."))
        if candidates:
            score, _, role, note = max(candidates)
        else:
            role = "peripheral"
            score = 0.2 if r.truncated_by_depth else 0.35
            note = (f"depth=4: обход обрывается; видимый вход от {r.in_deg} узлов, исходящие неизвестны."
                    if r.truncated_by_depth else
                    f"Недостаточно ролевых признаков: входящих {r.in_deg}, исходящих {r.out_deg}, depth={r.depth}.")
        roles.append(role)
        scores.append(round(float(score), 6))
        evidence.append(note[:200])
    df = df.copy()
    df["role"] = roles
    df["role_score"] = scores
    df["evidence"] = evidence
    return df, thresholds


def rank_nodes(df: pd.DataFrame) -> pd.DataFrame:
    counterparties = df.in_deg + df.out_deg
    volume = np.log1p(df.in_kzt + df.out_kzt)
    # Equal-weight rank aggregation: pattern strength, counterparties, volume,
    # and directed structural position/seed connection. No crime probability.
    structural = 0.5 * (percentile(df.pagerank) + percentile(df.seed_reach))
    raw = (percentile(df.role_score) + percentile(counterparties) +
           percentile(volume) + structural) / 4
    df = df.copy()
    df["priority_score"] = percentile(raw).round(6)
    df.loc[df.truncated_by_depth, "priority_score"] *= 0.75
    df["priority_score"] = df.priority_score.round(6)
    df["why"] = df.apply(
        lambda r: f"{r.role}: {r.in_deg} входящих / {r.out_deg} исходящих связей, "
                  f"видимый оборот {r.in_kzt + r.out_kzt:,.0f} KZT, связь с {r.seed_reach} seed"
                  + ("; граница 4-го колена" if r.truncated_by_depth else ""),
        axis=1,
    )
    return df


def outputs(df: pd.DataFrame, edges: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    roles = df[NODE_COLUMNS + ["depth", "is_seed", "in_deg", "out_deg", "in_kzt", "out_kzt",
                               "in_tx", "out_tx", "pagerank", "seed_reach", "pass_through",
                               "truncated_by_depth"]].copy()
    grouped = edges.assign(src_cluster=edges.src.map(dict(zip(df.gid, df.cluster_id))),
                           dst_cluster=edges.dst.map(dict(zip(df.gid, df.cluster_id))))
    internal = grouped.loc[grouped.src_cluster == grouped.dst_cluster].groupby("src_cluster").sum_kzt.sum()
    clusters = []
    for cid, group in df.groupby("cluster_id", sort=True):
        leaders = group.sort_values(["priority_score", "gid"], ascending=[False, True]).head(3)
        clusters.append({
            "cluster_id": int(cid), "n_nodes": len(group), "n_seed": int(group.is_seed.sum()),
            "sum_kzt_internal": round(float(internal.get(cid, 0)), 2),
            "top_gids": ";".join(str(gid) for gid in leaders.gid),
            "hypothesis": f"Группа для проверки: {len(group)} узлов, {int(group.is_seed.sum())} seed; видимый внутренний оборот {internal.get(cid, 0):,.0f} KZT.",
        })
    cluster_frame = pd.DataFrame(clusters, columns=CLUSTER_COLUMNS)
    top = df.sort_values(["priority_score", "gid"], ascending=[False, True]).head(20).copy()
    top.insert(0, "rank", range(1, len(top) + 1))
    return roles, cluster_frame, top[TOP_COLUMNS]


def validate_outputs(roles: pd.DataFrame, clusters: pd.DataFrame, top: pd.DataFrame, nodes: pd.DataFrame) -> None:
    if len(roles) != 2248 or roles.gid.duplicated().any() or set(roles.gid) != set(nodes.gid):
        raise ValueError("nodes_roles.csv does not cover all unique input gid")
    if not set(roles.role).issubset(ROLES):
        raise ValueError("Invalid role")
    if not roles.role_score.between(0, 1).all() or not roles.priority_score.between(0, 1).all():
        raise ValueError("Score outside [0,1]")
    if roles.evidence.isna().any() or not roles.evidence.str.len().between(1, 200).all():
        raise ValueError("Missing or oversized evidence")
    if clusters.empty or clusters.cluster_id.duplicated().any() or set(roles.cluster_id) != set(clusters.cluster_id):
        raise ValueError("Invalid clusters")
    if int(clusters.n_nodes.sum()) != len(nodes) or clusters[CLUSTER_COLUMNS].isna().any().any():
        raise ValueError("Cluster totals or fields invalid")
    if len(top) < 20 or top.gid.duplicated().any() or not set(top.gid).issubset(set(nodes.gid)):
        raise ValueError("Invalid top nodes")
    if list(top["rank"]) != list(range(1, len(top) + 1)) or top.why.isna().any() or (top.why.str.len() == 0).any():
        raise ValueError("Invalid top rank or explanation")


def run(data_dir: Path, out_dir: Path) -> dict[str, float]:
    started = time.perf_counter()
    nodes, edges, _ = load_and_validate(data_dir)
    graph = build_graph(nodes, edges)
    df = features(nodes, graph)
    clusters = cluster_graph(graph)
    df["cluster_id"] = df.gid.map(clusters).astype(int)
    df, thresholds = classify(df)
    df = rank_nodes(df)
    role_rows, cluster_rows, top_rows = outputs(df, edges)
    validate_outputs(role_rows, cluster_rows, top_rows, nodes)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in (("nodes_roles.csv", role_rows), ("clusters.csv", cluster_rows),
                        ("top_nodes.csv", top_rows)):
        frame.to_csv(out_dir / name, index=False, encoding="utf-8")
    elapsed = time.perf_counter() - started
    print(f"Validated {len(nodes)} nodes, {len(edges)} edges; {len(cluster_rows)} clusters.")
    print(f"Role counts: {df.role.value_counts().to_dict()}")
    print(f"Thresholds: {thresholds}")
    print(f"Outputs: {out_dir.resolve()}; runtime: {elapsed:.2f}s")
    if elapsed >= 300:
        raise RuntimeError("Pipeline exceeded the five-minute limit")
    return thresholds


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("out"))
    args = parser.parse_args()
    run(args.data, args.out)
