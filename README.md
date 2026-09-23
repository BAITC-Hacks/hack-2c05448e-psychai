# Money Graph / Граф денег

HackAlem AI case: **«Граф денег: восстановление финансовой структуры организованной группы по транзакционной сети»**.

## Problem

An AML analyst knows 81 seed clients connected to an investigation but must manually trace outgoing transfers to identify potential consolidation, transit and distribution points. The supplied four-hop transaction network contains 2,248 nodes. This prototype is intended to prioritize **further analyst review**, not to determine anyone's guilt.

## Goal

Build a locally reproducible pipeline and graph viewer that assign an explainable primary role to every node, group nodes into clusters, and rank clients for analyst review. Outputs are three CSV files plus a viewer in which an analyst can search for an arbitrary `gid` and inspect directed links, role and evidence.

## Input

The organizer's dataset is expected in `data/`; it is **not yet present in this repository**. The case specification describes:

| File | Specified fields | Specified size |
| --- | --- | ---: |
| `edges.parquet` | `src`, `dst`, `sum_kzt`, `n_tx`, `depth` | 3,119 aggregated directed edges |
| `nodes.parquet` | `gid`, `depth`, `is_seed` | 2,248 nodes |
| `transactions.parquet` | `src`, `dst`, `date`, `sum_kzt` | 4,840 transactions |

The dataset README and exact file schemas must be checked when the starter kit arrives.

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

These are properties of the supplied graph described in the case specification; they have not yet been checked against the actual files.

- **Depth-4 truncation:** traversal stops after four hops. The 444 nodes at `depth=4` with no visible outgoing edge cannot automatically be treated as true terminal recipients.
- **Outgoing-only collection:** the export follows outgoing transfers from seeds. Visible incoming and outgoing amounts do not establish full account balances.
- **Incomplete seed inflow:** money received by seed clients from outside the sampled graph is not fully visible; flow ratios for seeds can be misleading.
- **5,000 KZT threshold:** transfers below this threshold are absent from the export.
- **Disconnected components:** the specification reports 16 weakly connected components; analysis must not assume one connected network.
- **No role ground truth:** the dataset has no labeled true roles. Role quality is judged by transparent, defensible criteria rather than classification accuracy.

## Proposed minimal architecture

```text
Parquet → input validation → directed graph → graph features
        → deterministic role rules → clustering → priority scoring
        → evidence generation → CSV validation/export → lightweight graph viewer
```

**The mandatory analytical core is deterministic and does not depend on an LLM.** Every assigned role and priority must be traceable to calculated graph features. The viewer and any optional AI assistant must not be required for generating the CSVs.

## Planned stack

- **Python:** one-command local pipeline and validation.
- **pandas + pyarrow:** reading the specified Parquet inputs and writing tabular outputs.
- **NetworkX:** directed graph metrics and initial clustering on the specified 2,248-node network. Performance will be measured against the five-minute limit.
- **Viewer:** lightweight implementation to be chosen after inspecting the organizer's starter kit; no frontend framework is committed yet.

Only dependencies justified by the actual starter kit and implementation will be added.

## Definition of Done

- [ ] One README command runs from the raw Parquet files to all three CSVs in under five minutes, with no manual steps.
- [ ] `nodes_roles.csv` has exactly 2,248 unique `gid` values, required fields, one valid role per node, bounded scores and nonempty evidence.
- [ ] Formal metrics, criteria and thresholds for all roles are documented; the team can explain the roles of three arbitrary `gid` values within one minute using those metrics.
- [ ] Every node has a consistent `cluster_id`; `clusters.csv` reports cluster size, seed count, internal volume, top nodes and a hypothesis.
- [ ] `top_nodes.csv` contains at least 20 deterministically ranked nodes with reasons.
- [ ] The viewer shows directed edges, roles and clusters; an arbitrary jury-provided `gid` can be found and its links inspected.
- [ ] README documents startup, outputs, limitations, role criteria, thresholds and how the approach would change at approximately one million nodes; a one-slide pipeline diagram and a five-minute live demo are ready.

## Development status

The official team repository is initialized and the Money Graph requirements have been analyzed. **Implementation and testing have not started.** The organizer's starter kit and dataset are not in this repository yet; they must be inspected before implementation choices are finalized. There is currently no runnable pipeline or viewer.
