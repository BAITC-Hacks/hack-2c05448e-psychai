"""Local, read-only viewer for an arbitrary gid and its directed neighbors."""

from __future__ import annotations

import argparse
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

COLORS = {
    "consolidator": "#2563eb",
    "transit": "#7c3aed",
    "distributor": "#ea580c",
    "terminal": "#16a34a",
    "coordinator": "#dc2626",
    "peripheral": "#64748b",
}


def load_view(data_dir: Path, out_dir: Path):
    nodes = pd.read_csv(out_dir / "nodes_roles.csv").set_index("gid", drop=False)
    edges = pd.read_parquet(data_dir / "edges.parquet")
    clusters = pd.read_csv(out_dir / "clusters.csv")
    top = pd.read_csv(out_dir / "top_nodes.csv")
    if nodes.index.has_duplicates:
        raise ValueError("Duplicate gid in nodes_roles.csv")
    return nodes, edges, clusters, top


def svg_for(gid: int, nodes: pd.DataFrame, edges: pd.DataFrame) -> str:
    incoming = edges.loc[edges.dst == gid].sort_values(["sum_kzt", "src"], ascending=[False, True])
    outgoing = edges.loc[edges.src == gid].sort_values(["sum_kzt", "dst"], ascending=[False, True])
    # Full neighbor counts remain visible in text. Limit plotted edges only to
    # keep a 2,248-node network legible on an ordinary laptop.
    left = list(incoming.head(16).itertuples(index=False))
    right = list(outgoing.head(16).itertuples(index=False))
    height = max(340, 95 + 44 * max(len(left), len(right)))
    center_y = height / 2
    parts = [
        f'<svg viewBox="0 0 1000 {height}" role="img" aria-label="Направленные связи узла {gid}">',
        '<defs><marker id="arrow" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto">'
        '<polygon points="0 0,9 3.5,0 7" fill="#64748b"/></marker></defs>',
        f'<text x="80" y="35" fill="#334155">Входящие: {len(incoming)}</text>',
        f'<text x="735" y="35" fill="#334155">Исходящие: {len(outgoing)}</text>',
    ]
    def node(x: int, y: float, value: int, radius: int = 17) -> None:
        role = str(nodes.loc[value, "role"]) if value in nodes.index else "peripheral"
        color = COLORS.get(role, COLORS["peripheral"])
        same_cluster = value in nodes.index and nodes.loc[value, "cluster_id"] == nodes.loc[gid, "cluster_id"]
        outline = "#eab308" if same_cluster else "#cbd5e1"
        parts.append(f'<a href="/?gid={value}"><circle cx="{x}" cy="{y:.1f}" r="{radius}" '
                     f'fill="{color}" stroke="{outline}" stroke-width="4">'
                     f'<title>gid {value}: {html.escape(role)}</title></circle></a>')
        label_x = 28 if x < 300 else (845 if x > 700 else x)
        label_y = y + 4 if x != 500 else y + 48
        anchor = "middle" if x == 500 else "start"
        parts.append(f'<text x="{label_x}" y="{label_y:.1f}" text-anchor="{anchor}" '
                     f'font-size="11" fill="#172033">{value}</text>')
    for index, row in enumerate(left):
        y = 70 + index * 44
        parts.append(f'<line x1="210" y1="{y}" x2="472" y2="{center_y:.1f}" stroke="#64748b" '
                     'stroke-width="2" marker-end="url(#arrow)"/>')
        parts.append(f'<text x="285" y="{(y + center_y) / 2 - 5:.1f}" font-size="11" fill="#475569">'
                     f'{row.sum_kzt:,.0f} KZT</text>')
        node(175, y, int(row.src))
    for index, row in enumerate(right):
        y = 70 + index * 44
        parts.append(f'<line x1="528" y1="{center_y:.1f}" x2="790" y2="{y}" stroke="#64748b" '
                     'stroke-width="2" marker-end="url(#arrow)"/>')
        parts.append(f'<text x="650" y="{(y + center_y) / 2 - 5:.1f}" font-size="11" fill="#475569">'
                     f'{row.sum_kzt:,.0f} KZT</text>')
        node(825, y, int(row.dst))
    node(500, center_y, gid, 28)
    parts.append("</svg>")
    return "".join(parts)


def page(gid: int, nodes: pd.DataFrame, edges: pd.DataFrame, clusters: pd.DataFrame,
         top: pd.DataFrame) -> str:
    if gid not in nodes.index:
        body = f"<p>gid {gid} отсутствует в данных. Введите gid из nodes_roles.csv.</p>"
    else:
        row = nodes.loc[gid]
        details = [
            ("Роль", row.role), ("Сила ролевого сигнала", f"{row.role_score:.3f}"),
            ("Приоритет", f"{row.priority_score:.3f}"), ("Кластер", int(row.cluster_id)),
            ("Входящие связи", int(row.in_deg)), ("Исходящие связи", int(row.out_deg)),
            ("Видимый вход, KZT", f"{row.in_kzt:,.0f}"),
            ("Видимый выход, KZT", f"{row.out_kzt:,.0f}"),
            ("Входящих переводов", int(row.in_tx)), ("Исходящих переводов", int(row.out_tx)),
            ("Достижим от seed", int(row.seed_reach)), ("Глубина", int(row.depth)),
        ]
        cells = "".join(f"<tr><th>{html.escape(str(label))}</th><td>{html.escape(str(value))}</td></tr>"
                        for label, value in details)
        body = (f'<h2>gid {gid}</h2><p class="note">{html.escape(str(row.evidence))}</p>'
                f'<table>{cells}</table><h3>Направленные связи</h3>'
                '<p>Показаны до 16 крупнейших входящих и исходящих рёбер; числа в таблице учитывают все рёбра.</p>'
                f'{svg_for(gid, nodes, edges)}')
    links = " · ".join(f'<a href="/?gid={int(r.gid)}">{int(r.gid)} ({r.priority_score:.3f})</a>'
                       for r in top.head(20).itertuples(index=False))
    legend = " · ".join(f'<span style="color:{color}">● {html.escape(role)}</span>'
                        for role, color in COLORS.items())
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Граф денег — просмотр узла</title>
<style>body{{font:15px system-ui;margin:2rem auto;max-width:1050px;color:#172033}}
h1{{margin-bottom:.2rem}}form{{margin:1.2rem 0}}input{{font:inherit;padding:.45rem}}
button{{font:inherit;padding:.45rem .8rem}}table{{border-collapse:collapse;margin:1rem 0}}
th,td{{border:1px solid #d8e0eb;padding:.45rem .7rem;text-align:left}}
.note{{background:#eef4fa;padding:.8rem;border-radius:.35rem}}svg{{width:100%;border:1px solid #d8e0eb}}
a{{color:#1d4ed8}}</style>
<h1>Граф денег</h1><p>Локальная схема направленных переводов · {len(nodes)} узлов ·
{len(edges)} рёбер · {len(clusters)} кластеров. Роли — гипотезы для проверки аналитиком.</p>
<form method="get"><label for="gid">Поиск gid: </label>
<input id="gid" name="gid" type="text" inputmode="numeric" pattern="[0-9]+" value="{gid}" required>
<button type="submit">Показать</button></form>
<p>{legend} · <span style="color:#b45309">◉ жёлтая обводка: кластер выбранного узла</span></p>{body}
<h3>Топ-20 для проверки</h3><p>{links}</p>
<p>Видимые суммы не являются полным балансом. Узлы на глубине 4 обрезаны границей обхода;
переводы ниже 5000 KZT отсутствуют.</p></html>"""


def serve(data_dir: Path, out_dir: Path, host: str, port: int) -> None:
    nodes, edges, clusters, top = load_view(data_dir, out_dir)
    default_gid = int(top.iloc[0].gid)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            try:
                gid = int(query.get("gid", [default_gid])[0])
            except ValueError:
                gid = default_gid
            content = page(gid, nodes, edges, clusters, top).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
    with ThreadingHTTPServer((host, port), Handler) as server:
        print(f"Viewer: http://{host}:{port}/?gid={default_gid}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.data, args.out, args.host, args.port)
