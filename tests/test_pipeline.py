"""Behavior checks for the required Money Graph outputs and data traps."""

from pathlib import Path
import tempfile
import unittest

import networkx as nx
import pandas as pd

from run_pipeline import (
    build_graph, classify, cluster_graph, features, load_and_validate,
    outputs, rank_nodes, run, validate_outputs,
)
from viewer import page

ROOT = Path(__file__).resolve().parents[1]


class SyntheticGraphTests(unittest.TestCase):
    def test_isolated_node_and_depth_four_are_not_lost(self):
        nodes = pd.DataFrame({
            "gid": [1, 2, 3, 4, 5],
            "depth": [0, 1, 2, 4, 0],
            "is_seed": [True, False, False, False, True],
        })
        edges = pd.DataFrame({
            "src": [1, 2, 3],
            "dst": [2, 3, 4],
            "sum_kzt": [10000.0, 9000.0, 8000.0],
            "n_tx": [1, 1, 1],
        })
        graph = build_graph(nodes, edges)
        self.assertEqual(set(graph.nodes), set(nodes.gid))
        self.assertEqual(len(list(nx.weakly_connected_components(graph))), 2)
        tx = edges[["src", "dst", "sum_kzt"]].copy()
        tx["date"] = "2026-07-01"
        df = features(nodes, graph, tx)
        self.assertTrue(bool(df.set_index("gid").loc[4, "truncated_by_depth"]))
        self.assertEqual(int(df.set_index("gid").loc[5, "in_deg"]), 0)
        df["cluster_id"] = df.gid.map(cluster_graph(graph))
        df, _ = classify(df)
        self.assertNotEqual(df.set_index("gid").loc[4, "role"], "terminal")
        self.assertNotEqual(df.set_index("gid").loc[1, "role"], "transit")

    def test_chain_transit_and_fan_patterns_have_valid_evidence(self):
        nodes = pd.DataFrame({
            "gid": list(range(1, 11)),
            "depth": [0, 1, 1, 1, 2, 2, 2, 3, 3, 3],
            "is_seed": [True] + [False] * 9,
        })
        edges = pd.DataFrame({
            "src": [1, 2, 3, 4, 5, 5, 5, 6, 7],
            "dst": [5, 5, 5, 5, 6, 7, 8, 9, 10],
            "sum_kzt": [10000.0] * 9,
            "n_tx": [1] * 9,
        })
        graph = build_graph(nodes, edges)
        tx = edges[["src", "dst", "sum_kzt"]].copy()
        tx["date"] = "2026-07-01"
        df = features(nodes, graph, tx)
        df["cluster_id"] = df.gid.map(cluster_graph(graph))
        df, _ = classify(df)
        self.assertEqual(df.set_index("gid").loc[5, "role"], "consolidator")
        self.assertTrue(df.evidence.str.len().between(1, 200).all())
        self.assertTrue(df.role_score.between(0, 1).all())

    def test_transit_requires_later_day_outflow(self):
        nodes = pd.DataFrame({"gid": [1, 2, 3], "depth": [0, 1, 2],
                              "is_seed": [True, False, False]})
        edges = pd.DataFrame({"src": [1, 2], "dst": [2, 3],
                              "sum_kzt": [10000.0, 10000.0], "n_tx": [1, 1]})
        graph = build_graph(nodes, edges)
        for incoming, outgoing, expected in (
            ("2026-07-01", "2026-07-02", True),
            ("2026-07-02", "2026-07-01", False),
            ("2026-07-01", "2026-07-01", False),
        ):
            with self.subTest(incoming=incoming, outgoing=outgoing):
                tx = edges[["src", "dst", "sum_kzt"]].copy()
                tx["date"] = [incoming, outgoing]
                df = features(nodes, graph, tx)
                df, _ = classify(df)
                middle = df.set_index("gid").loc[2]
                self.assertEqual(middle.role == "transit", expected)
                self.assertEqual(middle.temporal_support_kzt, 10000.0 if expected else 0.0)


class FullDatasetTests(unittest.TestCase):
    def test_dataset_pipeline_is_deterministic_and_viewer_accepts_arbitrary_gid(self):
        if not (ROOT / "data" / "nodes.parquet").exists():
            self.skipTest("Organizer dataset not present")
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            run(ROOT / "data", Path(first))
            run(ROOT / "data", Path(second))
            for name in ("nodes_roles.csv", "clusters.csv", "top_nodes.csv"):
                self.assertEqual((Path(first) / name).read_bytes(), (Path(second) / name).read_bytes())
            self.assertTrue((Path(first) / "nodes_roles.csv").read_bytes().startswith(b"gid,"))
            roles = pd.read_csv(Path(first) / "nodes_roles.csv")
            clusters = pd.read_csv(Path(first) / "clusters.csv")
            top = pd.read_csv(Path(first) / "top_nodes.csv")
            nodes, edges, _ = load_and_validate(ROOT / "data")
            validate_outputs(roles, clusters, top, nodes)
            self.assertTrue(clusters.hypothesis.str.contains("Требуется проверка аналитиком").all())
            self.assertTrue(clusters.hypothesis.str.contains("Признаки|Возможный|Структурный|Назначение").all())
            self.assertFalse(((roles.depth == 4) & (roles.role == "terminal")).any())
            arbitrary_gid = int(nodes.iloc[-1].gid)
            rendered = page(arbitrary_gid, roles.set_index("gid", drop=False), edges, clusters, top)
            self.assertIn(f"gid {arbitrary_gid}", rendered)
            self.assertIn("<svg", rendered)
            self.assertIn('type="text" inputmode="numeric"', rendered)
            self.assertIn("Почему выбрана эта роль", rendered)
            self.assertIn("Группа связей №", rendered)
            self.assertIn("Гипотеза о группе", rendered)
            self.assertIn("Как читать схему и термины", rendered)
            self.assertIn("Почему в топе", rendered)


if __name__ == "__main__":
    unittest.main()
