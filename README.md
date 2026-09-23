# Money Graph / Граф денег

HackAlem AI case: **«Граф денег: восстановление финансовой структуры организованной группы по транзакционной сети»**.

## Problem

An AML analyst knows 81 seed clients connected to an investigation but must manually trace outgoing transfers to identify potential consolidation, transit and distribution points. The supplied four-hop transaction network contains 2,248 nodes. This prototype is intended to prioritize **further analyst review**, not to determine anyone's guilt.

## Goal

Build a locally reproducible pipeline and graph viewer that assign an explainable primary role to every node, group nodes into clusters, and rank clients for analyst review. Outputs are three CSV files plus a viewer in which an analyst can search for an arbitrary `gid` and inspect directed links, role and evidence.

## Input

The organizer's dataset is included in `data/`. Its schema is documented in `data/README.md`:

| File | Specified fields | Specified size |
| --- | --- | ---: |
| `edges.parquet` | `src`, `dst`, `sum_kzt`, `n_tx`, `depth` | 3,119 aggregated directed edges |
| `nodes.parquet` | `gid`, `depth`, `is_seed` | 2,248 nodes |
| `transactions.parquet` | `src`, `dst`, `date`, `sum_kzt` | 4,840 transactions |

The supplied files were checked for row counts, unique identifiers, non-null required fields, and agreement between aggregated edges and individual transactions.

## Required outputs

| Artifact | Required fields / behavior |
| --- | --- |
| `nodes_roles.csv` | `gid`, `role`, `role_score`, `cluster_id`, `priority_score`, `evidence`; one row for each of the 2,248 nodes; `evidence` is human-readable and at most 200 characters |
| `clusters.csv` | `cluster_id`, `n_nodes`, `n_seed`, `sum_kzt_internal`, `top_gids`, `hypothesis` |
| `top_nodes.csv` | `rank`, `gid`, `role`, `priority_score`, `why`; at least 20 ranked nodes |
| Graph viewer | Directed network view with roles/clusters and search by `gid`, showing the selected node's links |

## Required roles

Every node receives exactly one primary role from this vocabulary:

| Role | Meaning in the case specification |
| --- | --- |
| `consolidator` | Receives funds from multiple participants |
| `transit` | Passes funds onward rather than retaining them |
| `distributor` | Sends funds to many recipients |
| `terminal` | Visible endpoint where funds appear to remain |
| `coordinator` | Structurally important node that may warrant organizer-focused review |
| `peripheral` | No stronger role signal identified |

These are **analytical hypotheses**, not statements that a client committed a crime.

## Core constraints

- All **2,248** nodes must receive a role, `role_score`, `cluster_id`, `priority_score` and nonempty evidence.
- `role_score` and `priority_score` must each be within `[0, 1]`.
- Every role and priority must be explainable from calculated graph features. Formal role criteria and thresholds must be documented before submission.
- `top_nodes.csv` must contain at least **20** nodes with a human-readable reason.
- The complete pipeline from raw Parquet files to the three CSV outputs must run in **under five minutes** on an ordinary laptop.
- Execution must be local and reproducible from the README, without a paid service, GPU cluster or manual data edits.
- No hardcoded `gid` results, black-box role assignment or invented client attributes.
- AML conclusions must be phrased as **hypotheses for analyst review**, never assertions of guilt.

## Known data limitations

These are properties of the supplied graph described in the case specification and considered by the implementation.

- **Depth-4 truncation:** traversal stops after four hops. The 444 nodes at `depth=4` with no visible outgoing edge cannot automatically be treated as true terminal recipients.
- **Outgoing-only collection:** the export follows outgoing transfers from seeds. Visible incoming and outgoing amounts do not establish full account balances.
- **Incomplete seed inflow:** money received by seed clients from outside the sampled graph is not fully visible; flow ratios for seeds can be misleading.
- **5,000 KZT threshold:** transfers below this threshold are absent from the export.
- **Disconnected components:** the specification reports 16 weakly connected components; analysis must not assume one connected network.
- **No role ground truth:** the dataset has no labeled true roles. Role quality is judged by transparent, defensible criteria rather than classification accuracy.

## Architecture

```text
Parquet → input validation → directed graph → graph features
        → deterministic role rules → clustering → priority scoring
        → evidence generation → CSV validation/export → lightweight graph viewer
```

**The mandatory analytical core is deterministic and does not depend on an LLM.** Every assigned role and priority must be traceable to calculated graph features. The viewer and any optional AI assistant must not be required for generating the CSVs.

## System requirements and dependencies

- **Verified environment:** 64-bit Windows 10 and 64-bit Python 3.10.11. The macOS/Linux commands below use the same Python code but have not been independently verified on those systems.
- **Python:** use a 64-bit Python 3.10 installation and its `venv`/`pip` modules. A standard web browser is needed for the viewer.
- **Install-time access:** `pip install` needs access to the Python package index or an equivalent local wheel cache. After installation, the pipeline and viewer run locally without internet access.
- **Input files:** `data/nodes.parquet`, `data/edges.parquet`, and `data/transactions.parquet` are committed to this repository. No separate dataset download is needed.
- **Python packages:** exact versions of pandas, pyarrow, NetworkX, NumPy and SciPy are pinned in `requirements.txt`. SciPy is used by NetworkX's PageRank.
- **Configuration:** no environment variables, API keys, model downloads, personal accounts, subscriptions, or external services are required. The viewer listens only on `127.0.0.1:8765` by default. `--data`, `--out`, `--host`, and `--port` are optional command-line parameters where applicable.

No LLM or GPU is needed.

## Install, run and verify

Run these commands from the repository root, which contains `README.md`, `requirements.txt`, `run_pipeline.py`, `viewer.py`, and `data/`. On Windows PowerShell:

```powershell
python --version
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run_pipeline.py
.venv\Scripts\python -m unittest discover -s tests -v
```

Expected result: `run_pipeline.py` prints `Validated 2248 nodes, 3119 edges`, a runtime under 300 seconds, and the absolute output path. It creates `out/nodes_roles.csv` (2,248 data rows), `out/clusters.csv` (66 data rows on the supplied dataset), and `out/top_nodes.csv` (20 data rows). The test command must finish with `Ran 4 tests` and `OK`. It reruns the pipeline in temporary directories and verifies CSV schema, determinism, depth-4 handling, temporal ordering and arbitrary `gid` lookup. `out/` is generated locally and intentionally excluded from Git.

Then start the viewer in the same terminal; leave it running while using the browser:

```powershell
.venv\Scripts\python viewer.py
```

Open the local URL printed by the viewer (normally `http://127.0.0.1:8765/`). The page opens a top-ranked node by default. Enter any exact `gid` copied from `out/nodes_roles.csv`, press **Показать**, and verify that the node's role, numerical evidence, cluster and directed incoming/outgoing links appear. The search field is text so 18-digit IDs are not rounded by the browser. Stop the viewer with `Ctrl+C`. No login or network connection is involved.

On macOS/Linux, use `python3 -m venv .venv`, then replace `.venv\Scripts\python` in the commands above with `.venv/bin/python`. If port 8765 is occupied, start `viewer.py --port 8766` and open the URL it prints. To use nondefault folders, run `run_pipeline.py --data PATH --out PATH` and then `viewer.py --data PATH --out PATH` with the same paths. If an input file is missing or malformed, the pipeline exits with an explanatory error; it does not silently generate placeholder results.

## Role rules and explanation

The pipeline calculates visible in/out degrees, KZT totals, transaction counts, weighted PageRank, seed reach, depth, `out_kzt / in_kzt`, and later-day flow support from individual transaction dates. Only observed transfers are described. Role cutoffs are derived from the input distribution and printed at each run. For the supplied dataset, the measured cutoffs are: fan-in ≥3, fan-out ≥8, incoming KZT ≥166,819.7, outgoing KZT ≥397,500, PageRank ≥0.00180444, and minimum two-sided flow ≥43,500 KZT.

| Role | Deterministic candidate rule |
| --- | --- |
| `consolidator` | Fan-in at/above the 90th percentile of positive in-degrees (minimum 3) **and** visible incoming sum at/above the 75th percentile. A seed's role score is capped because its incoming flow is incomplete. |
| `distributor` | Fan-out at/above the 90th percentile of positive out-degrees (minimum 3) **and** visible outgoing sum at/above the 75th percentile. |
| `transit` | Non-seed with visible input and output, minimum of those amounts at/above the median two-sided flow, `out_kzt / in_kzt` in `[0.8, 1.2]`, and later-day supported outflow at least 50% of the smaller visible in/out total. |
| `terminal` | Non-seed at depth below 4, with a visible incoming edge and no visible outgoing edge. This is only a possible endpoint *within the export*. |
| `coordinator` | At least two incoming and two outgoing counterparties, reachable from at least two seeds, and PageRank at/above its 98th percentile. This indicates structural importance, not an identified organizer. |
| `peripheral` | No stronger candidate; depth-4 truncated nodes with no outgoing edge stay here rather than becoming `terminal`. |

For later-day support, the pipeline processes each node's daily transaction totals in date order. An outgoing amount can use only previously observed incoming amount from an earlier **calendar day**; same-day ordering is unknown and provides no support. This is a conservative structural check, not a tracing of individual banknotes or proof that the funds are identical. The 50% cutoff is an explicit heuristic, not a learned or regulatory threshold. `nodes_roles.csv` includes `temporal_support_kzt` and `temporal_support_ratio` for inspection.

When multiple rules match, the strongest bounded role signal wins with a fixed tie order. `role_score` is the strength of visible evidence, **not a calibrated probability**. Every row includes numbers in `evidence`. The score and evidence do not imply guilt.

Louvain partitions an undirected projection using log-scaled transfer weights and a fixed seed. Direction is retained in role features, internal cluster sums, and the viewer. Cluster IDs are ordered by their smallest `gid`. The cluster `hypothesis` is generated from observed size, seed count and internal volume; it is not a criminal allegation.

`priority_score` aggregates equal-weight percentile ranks of role signal, counterparties, visible volume and structural position/seed reach; the final score is ranked to `[0,1]`. Depth-4 truncated endpoints receive a reduction because downstream activity is unknown. Ties use ascending `gid`. `top_nodes.csv` includes concrete values in `why`. Equal weights are a transparent starting assumption, not domain-calibrated risk weights.

## Research-informed interpretation

The [IBM AMLworld paper](https://proceedings.neurips.cc/paper_files/paper/2023/file/5f38404edff6f3f642d6fa5892479c42-Paper-Datasets_and_Benchmarks.pdf) defines fan-in, fan-out, gather-scatter and other **transaction subgraph patterns**. They help describe why our visible in/out-degree rules are useful, but they are not labels for individual clients and do not establish laundering. In particular, `transit` combines a similar *monthly total* with later-day support; it does not prove that the same funds moved onward. `coordinator` is based on seed reach and PageRank; the pipeline does not claim to detect cycles or ownership. The [IBM dataset description](https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml) also explains why a bank's partial view matters, supporting our explicit depth and seed caveats.

IBM AMLworld and [SAML-D](https://www.kaggle.com/datasets/berkanoztas/synthetic-transaction-monitoring-dataset-aml/versions/2) contain synthetic suspicious-transaction labels. They are potential **separate** stress-test data, not a ground truth for this case's six roles. A valid transfer test would need to recreate this case's one-month, outgoing-only, four-hop, 5,000-KZT observation window and separately define what a flagged *node* means before reporting precision or recall. No such external benchmark has been run here, and neither dataset is required to reproduce the submission.

## Scalability

The supplied 2,248-node graph runs locally in seconds. At about one million nodes, NetworkX object overhead, PageRank, Louvain and rendering would need replacement with chunked Parquet processing, a compact graph engine such as igraph, and indexed neighborhood queries. The current viewer intentionally draws at most 16 edges in each direction for a selected node while reporting full counts.

## Definition of Done

- [x] One command runs from raw Parquet to three validated CSVs in under five minutes (measured 3.95 seconds on the development machine).
- [x] `nodes_roles.csv` covers exactly 2,248 unique `gid` values with required fields, valid roles, bounded scores and evidence.
- [x] All six role rules and measured thresholds are documented; numerical evidence is available for arbitrary nodes.
- [x] Every node has a cluster; `clusters.csv` reports size, seed count, internal volume, top nodes and a cautious hypothesis.
- [x] `top_nodes.csv` contains 20 deterministically ranked nodes with reasons.
- [x] The local viewer finds arbitrary `gid` values and shows directed incoming/outgoing links, roles and clusters.
- [x] A one-page pipeline diagram is available in `ARCHITECTURE.md`.
- [ ] A timed five-minute team demo remains to be rehearsed.

## Development status

The deterministic pipeline and local viewer are implemented. On the provided data, the pipeline produces 2,248 role rows, 66 clusters and 20 top rows in seconds. Four unittest cases passed, including deterministic reruns, depth-4 protection, later-day transit checks and arbitrary-`gid` viewer rendering; one HTTP request to the viewer returned status 200. These checks establish basic operation, not expert validation of AML role quality.

## Sources and attribution

- `data/` and `data/README.md`: anonymized HackAlem AI organizer dataset, supplied for this competition.
- `starter/`: organizer-provided starter code and instructions. It loads Parquet, builds a directed graph and calculates baseline metrics; its CSV role/cluster/priority values are placeholders. This project's `run_pipeline.py`, role rules, validation and viewer were developed during the competition.
- Python dependencies and exact installed versions are listed in `requirements.txt`; their respective open-source licenses apply.
