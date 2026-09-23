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

ROLE_INFO = {
    "consolidator": ("Сбор средств", "Получает переводы от нескольких разных клиентов; это повод проверить источник и дальнейший путь средств."),
    "transit": ("Возможный транзит", "Видимые вход и выход близки по сумме, а часть выхода произошла в более поздние дни. Это не доказывает движение тех же денег."),
    "distributor": ("Распределение", "Отправляет средства многим разным получателям; стоит проверить, куда ведут эти ветви."),
    "terminal": ("Видимый конечный получатель", "Получает переводы и не имеет исходящих связей внутри этой выгрузки. Вне выгрузки переводы возможны."),
    "coordinator": ("Структурный центр", "Связан с несколькими потоками и исходными клиентами. Это кандидат для углублённой проверки, а не установленный организатор."),
    "peripheral": ("Недостаточно признаков", "По доступной части графа ни одна более конкретная роль не обоснована."),
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
        body = f'<section class="card"><h2>Узел не найден</h2><p>gid {gid} отсутствует в данных. Скопируйте идентификатор из nodes_roles.csv или выберите строку топ-20 ниже.</p></section>'
    else:
        row = nodes.loc[gid]
        role_name, role_meaning = ROLE_INFO[str(row.role)]
        cluster = clusters.loc[clusters.cluster_id == row.cluster_id].iloc[0]
        details = [
            ("От скольких клиентов получал", int(row.in_deg)),
            ("Скольким клиентам отправлял", int(row.out_deg)),
            ("Видимая сумма полученных переводов", f"{row.in_kzt:,.0f} KZT"),
            ("Видимая сумма отправленных переводов", f"{row.out_kzt:,.0f} KZT"),
            ("Количество входящих / исходящих переводов", f"{int(row.in_tx)} / {int(row.out_tx)}"),
            ("Сколько исходных клиентов могут достичь узла", int(row.seed_reach)),
            ("Глубина от исходных клиентов", int(row.depth)),
        ]
        cells = "".join(f"<tr><th>{html.escape(str(label))}</th><td>{html.escape(str(value))}</td></tr>"
                        for label, value in details)
        temporal = (f'<p><strong>Временная опора:</strong> после видимых входящих переводов в более поздние дни '
                    f'могло уйти до {row.temporal_support_kzt:,.0f} KZT. Переводы в один день не учитываются: '
                    'их порядок неизвестен.</p>' if row.role == "transit" else "")
        depth_note = ('<p class="caution">Узел на четвёртом колене: обход здесь заканчивается. '
                      'Отсутствие исходящих стрелок не означает, что переводов дальше не было.</p>'
                      if bool(row.truncated_by_depth) else "")
        body = (f'<section class="card" id="node"><h2>Клиент gid {gid}</h2>'
                f'<p class="role"><span class="dot" style="background:{COLORS[str(row.role)]}"></span>'
                f'<strong>{html.escape(role_name)}</strong> <small>({html.escape(str(row.role))})</small></p>'
                f'<p>{html.escape(role_meaning)}</p>'
                f'<p class="evidence"><strong>Почему выбрана эта роль:</strong> {html.escape(str(row.evidence))}</p>'
                f'<div class="scores"><p><strong>Сила признаков роли: {row.role_score:.3f}</strong><br>'
                'Насколько явно проявились признаки выбранной роли. Это не вероятность преступления.</p>'
                f'<p><strong>Очередность проверки: {row.priority_score:.3f}</strong><br>'
                'Чем выше число, тем раньше мы предлагаем аналитику посмотреть узел. Это не оценка виновности.</p></div>'
                f'{temporal}{depth_note}<h3>Наблюдаемые данные</h3><table>{cells}</table>'
                f'<div class="cluster"><h3>Группа связей № {int(row.cluster_id)}</h3>'
                f'<p>В этой группе {int(cluster.n_nodes)} клиентов, из них {int(cluster.n_seed)} исходных. '
                f'Сумма переводов между клиентами группы: {cluster.sum_kzt_internal:,.0f} KZT. '
                'Группа выделена по связям графа; общая цель её участников неизвестна.</p>'
                f'<p><strong>Гипотеза о группе:</strong> {html.escape(str(cluster.hypothesis))}</p></div>'
                '<h3>Куда идут стрелки</h3><p>Слева — клиенты, от которых получены переводы. '
                'Справа — клиенты, которым отправлены переводы. Нажмите на круг, чтобы перейти к этому клиенту. '
                'Показаны до 16 крупнейших рёбер в каждом направлении; счётчики выше учитывают все связи.</p>'
                f'<div class="graph">{svg_for(gid, nodes, edges)}</div></section>')
    top_rows = "".join(
        f'<tr><td>{int(r.rank)}</td><td><a href="/?gid={int(r.gid)}">{int(r.gid)}</a></td>'
        f'<td>{html.escape(ROLE_INFO[str(r.role)][0])}</td><td>{r.priority_score:.3f}</td>'
        f'<td>{html.escape(str(r.why))}</td></tr>' for r in top.head(20).itertuples(index=False)
    )
    legend = " · ".join(
        f'<span><span class="dot" style="background:{color}"></span>{html.escape(ROLE_INFO[role][0])}</span>'
        for role, color in COLORS.items()
    )
    role_counts = nodes.role.value_counts()
    role_bars = "".join(
        f'<div class="role-row"><span><span class="dot" style="background:{color}"></span>'
        f'{html.escape(ROLE_INFO[role][0])}</span><div class="bar-track">'
        f'<div class="bar-fill" style="width:{100 * int(role_counts.get(role, 0)) / len(nodes):.1f}%;'
        f'background:{color}"></div></div><strong>{int(role_counts.get(role, 0))}</strong></div>'
        for role, color in COLORS.items()
    )
    # Turnover is a descriptive sort key, not a fraud score. Each transfer is
    # counted once in the source cluster's internal edges.
    largest_clusters = clusters.sort_values(
        ["sum_kzt_internal", "cluster_id"], ascending=[False, True]
    ).head(5)
    cluster_rows = "".join(
        f'<tr><td>{int(r.cluster_id)}</td><td>{int(r.n_nodes)}</td><td>{int(r.n_seed)}</td>'
        f'<td>{r.sum_kzt_internal:,.0f} KZT</td><td>'
        f'<a href="/?gid={int(str(r.top_gids).split(";")[0])}#node">Открыть участника</a></td></tr>'
        for r in largest_clusters.itertuples(index=False)
    )
    summary = (
        f'<section class="card" id="overview"><h2>Обзор видимой сети</h2>'
        '<p>Это объём загруженных данных и результаты группировки, а не оценка опасности людей.</p>'
        '<div class="stats">'
        f'<div><strong>{len(nodes):,}</strong><span>клиентов</span></div>'
        f'<div><strong>{len(edges):,}</strong><span>направленных связей</span></div>'
        f'<div><strong>{int(nodes.is_seed.sum()):,}</strong><span>исходных клиентов</span></div>'
        f'<div><strong>{len(clusters):,}</strong><span>групп связей</span></div>'
        '</div><div class="dashboard-grid"><div><h3>Роли в этой выгрузке</h3>'
        '<p>Каждый клиент отнесён к одной роли по наблюдаемым признакам.</p>'
        f'{role_bars}</div><div><h3>Группы с крупнейшим внутренним оборотом</h3>'
        '<p>Сумма видимых переводов между участниками группы. Это не баланс группы и не рейтинг угроз.</p>'
        '<div class="table-wrap"><table><thead><tr><th>Группа</th><th>Клиенты</th>'
        '<th>Исходные</th><th>Оборот</th><th></th></tr></thead>'
        f'<tbody>{cluster_rows}</tbody></table></div></div></div></section>'
    )
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Граф денег — разбор сети</title>
<style>body{{font:16px/1.5 system-ui;margin:0;background:#f3f6fb;color:#172033}}
main{{max-width:1120px;margin:auto;padding:1.5rem}}h1{{margin:.2rem 0}}h2{{margin-top:0}}
.card{{background:white;border:1px solid #d8e0eb;border-radius:12px;padding:1.2rem;margin:1rem 0}}
.intro{{background:#e7f0ff}}.caution{{background:#fff5dc;border-left:4px solid #b45309;padding:.7rem}}
.evidence,.cluster{{background:#eef4fa;padding:.8rem;border-radius:8px}}.scores{{display:flex;gap:1rem;flex-wrap:wrap}}
.scores p{{flex:1;min-width:240px;background:#f7f9fd;padding:.8rem;border-radius:8px}}
form{{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}}input,button{{font:inherit;padding:.5rem}}
input{{width:22ch;max-width:100%}}button{{background:#1d4ed8;color:white;border:0;border-radius:6px;cursor:pointer}}
table{{border-collapse:collapse;width:100%}}th,td{{border-bottom:1px solid #d8e0eb;padding:.5rem;text-align:left;vertical-align:top}}
th{{font-weight:600}}.table-wrap,.graph{{overflow-x:auto}}svg{{width:100%;min-width:680px;border:1px solid #d8e0eb}}
.dot{{display:inline-block;width:.8em;height:.8em;border-radius:50%;margin-right:.35em}}.legend{{display:flex;gap:.8rem;flex-wrap:wrap}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem}}
.stats div{{background:#eef4fa;border-radius:8px;padding:.8rem;display:flex;flex-direction:column}}
.stats strong{{font-size:1.6rem;font-variant-numeric:tabular-nums}}.stats span{{color:#52647c}}
.dashboard-grid{{display:grid;grid-template-columns:minmax(240px,1fr) minmax(0,2fr);gap:1.5rem}}
.role-row{{display:grid;grid-template-columns:165px 1fr 35px;gap:.5rem;align-items:center;margin:.45rem 0}}
.role-row strong{{text-align:right}}.bar-track{{height:.75rem;background:#e8edf5;border-radius:10px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:10px}}@media(max-width:780px){{.dashboard-grid{{grid-template-columns:1fr}}}}
a{{color:#1d4ed8}}small{{color:#52647c}}.role{{font-size:1.25rem}}</style>
<main><h1>Граф денег</h1><p>{len(nodes)} клиента · {len(edges)} направленных связей · {len(clusters)} групп</p>
<section class="card intro"><h2>Что показывает этот экран</h2>
<p>Это карта <strong>видимой части</strong> переводов. Выберите клиента по номеру gid, чтобы увидеть,
от кого ему поступали деньги, кому он отправлял их дальше и почему программа предложила его роль.
Результат — подсказка для проверки аналитиком, а не обвинение.</p></section>
{summary}
<section class="card"><form method="get"><label for="gid"><strong>Номер клиента (gid)</strong></label>
<input id="gid" name="gid" type="text" inputmode="numeric" pattern="[0-9]+" value="{gid}" required>
<button type="submit">Показать</button></form>
<p><small>Можно скопировать gid из таблицы ниже или из nodes_roles.csv. Длинный номер не округляется.</small></p></section>
{body}
<section class="card"><h2>Как читать схему и термины</h2><p class="legend">{legend}</p>
<p><strong>Стрелка</strong> показывает направление перевода. <strong>Жёлтая обводка</strong> означает,
что сосед находится в той же группе связей, что и выбранный клиент.</p>
<p><strong>Группа (кластер)</strong> — узлы, которые алгоритм объединил по связям; это не доказательство общей организации.
<strong>Исходные клиенты (seed)</strong> — 81 клиент, с которых начался обход графа.</p></section>
<section class="card" id="top"><h2>Кого посмотреть первым: топ-20</h2>
<p>Это порядок ручной проверки. Нажмите на gid, чтобы открыть его связи. Балл сравнивает узлы внутри этой выгрузки и не является вероятностью преступления.</p>
<div class="table-wrap"><table><thead><tr><th>№</th><th>gid</th><th>Роль</th><th>Приоритет</th><th>Почему в топе</th></tr></thead>
<tbody>{top_rows}</tbody></table></div></section>
<p class="caution">Данные неполные: обход обрывается на четвёртом колене, переводы меньше 5 000 KZT не видны,
а суммы внутри графа не показывают полный баланс клиента.</p></main></html>"""


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
