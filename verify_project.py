"""One-command, offline check of the published HackAlem submission."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
RESULTS = ("nodes_roles.csv", "clusters.csv", "top_nodes.csv")
INPUTS = ("nodes.parquet", "edges.parquet", "transactions.parquet")


def verify() -> None:
    if sys.version_info[:2] != (3, 10):
        raise RuntimeError("Python 3.10.x is required; check python --version in README.md.")
    print("[1/4] Python 3.10: OK")

    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        package, expected = line.split("==", 1)
        try:
            installed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(
                f"Missing {package}. Run python -m pip install -r requirements.txt"
            ) from exc
        if installed != expected:
            raise RuntimeError(
                f"Version of {package}: installed {installed}, required {expected}. "
                "Run python -m pip install -r requirements.txt"
            )
    print("[2/4] Dependencies: OK")

    for name in INPUTS:
        if not (ROOT / "data" / name).is_file():
            raise RuntimeError(f"Missing input file data/{name}")
    for name in RESULTS:
        if not (ROOT / "submission" / name).is_file():
            raise RuntimeError(f"Missing published file submission/{name}")
    print("[3/4] Input data and published outputs: OK")

    # Imports happen after preflight so a fresh machine gets an actionable
    # dependency message instead of an import traceback.
    from run_pipeline import run
    from viewer import load_view, page

    with tempfile.TemporaryDirectory() as temporary:
        fresh = Path(temporary)
        run(ROOT / "data", fresh)
        for name in RESULTS:
            actual = (fresh / name).read_text(encoding="utf-8").splitlines()
            published = (ROOT / "submission" / name).read_text(encoding="utf-8").splitlines()
            if actual != published:
                raise RuntimeError(
                    f"Fresh {name} differs from submission/{name}. "
                    "Published outputs are stale or data/code changed."
                )
        nodes, edges, clusters, top = load_view(ROOT / "data", fresh)
        gid = int(top.iloc[0].gid)
        rendered = page(gid, nodes, edges, clusters, top)
        for marker in (f"gid {gid}", "Обзор видимой сети", "<svg", "Почему выбрана эта роль"):
            if marker not in rendered:
                raise RuntimeError(f"Viewer page is missing expected element: {marker}")
    print("[4/4] Pipeline, CSV comparison and viewer page: OK")
    print("PASS. For interactive viewing: python run_pipeline.py, then python viewer.py")


if __name__ == "__main__":
    try:
        verify()
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
