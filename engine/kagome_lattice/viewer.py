# -*- coding: utf-8 -*-
"""結果を見る画面（viewer.html）。外部ファイルもネット接続も要らない 1 枚の HTML。"""
import json
import math

from .io import edge_id
from .profiles import presentation_text, profile_info

LABELS = {
    "V": "流量 V",
    "dV": "流量の変化",
    "unexplained": "入口からの流れで説明できない分",
    "J": "規格化した流れ J",
    "J_straight": "直進成分",
    "ratio": "臨界量に対する比 ε/ε*",
    "usage": "容量に対する流量 V/c",
    "margin": "臨界量までの余裕 ε* − ε",
    "dev_std": "標準状態（全素辺が臨界）からのずれ V − V_std",
    "f": "増加型の分布値 f（良否は用途側で定める）",
}


def _num(x):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else round(x, 6)


def write_viewer(path, m, V, cmp, J, dec, crit, cap, limit, ops, issues, report,
                 unexplained=None, std=None, hex_rows=None, trace=None):
    """cmp: 比べる相手 {"V": {素辺: 流量}, "label": 名前}（操作の前、またはシナリオのもとの条件）。"""
    V_raw = cmp["V"] if cmp else None
    profile = report.get("profile", "traffic")
    info = report.get("profile_info") or profile_info(profile, report.get("norm", "k"))
    labels = dict(LABELS)
    labels["J"] = "原資料の流量 j = V/m（CSV列J）" if report.get("norm") == "m" else "規格化した流れ J"
    labels["J_straight"] = "直進ポテンシャル"
    if cmp:
        labels["dV"] = f"{cmp['label']}からの流量の変化"
    gcut = set((ops or {}).get("global", {}).get("cut", []))
    dcut = {d: set(v["bottlenecks"]) for d, v in (report.get("limit_detail") or {}).items()}
    if gcut:
        labels["cut_g"] = "受け入れを決めた細い所（全体の最小カット）"
    RN = {1: "→", 2: "↗", 3: "↖", 4: "←", 5: "↙", 6: "↘"}
    if report.get("limit_rule") == "through_maxflow":
        for d in sorted(dcut):
            labels[f"cut_{d}"] = f"向き {d} {RN[int(d)]} の細い所（通り抜けの最小カット）"
    edges = []
    for e in m.edges:
        a = m.position(e[:3])
        b = m.position(m.target(e))
        q = {"V": V[e], "J": J[e], "J_straight": dec["straight"][e]["J_straight"]}
        q.update({k: getattr(m.values[e], k) for k in ("m", "L", "v", "T", "mu")})
        if gcut:
            q["cut_g"] = 1.0 if edge_id(e) in gcut else 0.0
        if report.get("limit_rule") == "through_maxflow":
            for d, cs in dcut.items():
                q[f"cut_{d}"] = 1.0 if edge_id(e) in cs else 0.0
        if V_raw is not None:
            q["dV"] = V[e] - V_raw[e]
            q["V_before"] = V_raw[e]
        if unexplained is not None:
            q["unexplained"] = unexplained[e]
        if crit:
            q.update(ratio=crit[e]["ratio"], margin=crit[e]["margin"], eps_star=crit[e]["eps_star"],
                     f=crit[e]["f"])
        if std is not None:
            q["dev_std"] = V[e] - std["V"][e]
        if cap:
            q["capacity"] = cap[e]
            q["usage"] = V[e] / cap[e] if cap[e] else None
        edges.append({"id": edge_id(e), "road": e[3], "a": a, "b": b,
                      "complete": dec["straight"][e]["complete"], "inner": m.is_inner(e),
                      "q": {k: _num(v) for k, v in q.items()}})
    nodes = [{"id": "%s(%d,%d)" % n, "t": n[0], "p": m.position(n)} for n in m.nodes]
    rot = rotation_polygons(m, dec)
    hex_summary = report.get("standard", {}).get("hex_rotation")
    if std is not None:                       # 標準状態の回転量（同じ図形の並び）
        rs = {(p["kind"], p["i"], p["j"]): p for p in rotation_polygons(m, std["dec"])}
        for p in rot:
            q = rs.get((p["kind"], p["i"], p["j"]))
            for component in ("cw", "ccw", "net"):
                p["std_" + component] = q[component] if q else None
            row = (hex_rows or {}).get((p["i"], p["j"])) if p["kind"] == "h" else None
            if row is not None:
                p["minus_mean"] = {k: _num(v) for k, v in row["difference"].items()}
    available = [k for k in labels if any(ed["q"].get(k) is not None for ed in edges)]
    data = {
        "edges": edges, "nodes": nodes, "rot": rot, "hex_rotation": hex_summary,
        "profile_info": info, "geometry": report.get("geometry", {}),
        "trace": trace,
        "provenance": report.get('provenance'),
        "direction_comparison": report.get("direction_comparison"),
        "hex_scenario_comparison": report.get("hex_scenario_comparison", []),
        "spin_interactions": report.get("standard", {}).get("spin_interactions"),
        "comparison_summary": report.get('comparison_summary'),
        "labels": labels, "cmp_label": cmp["label"] if cmp else None,
        "estimate": report.get("estimate"), "changes": report.get("changes") or [], "available": available,
        "settings": {k: report.get(k) for k in ("n", "halo", "compared_with", "mode", "norm", "tau_mode", "eps", "theta", "limit_rule")},
        "limit": {str(d): _num(v) for d, v in (limit or {}).items()},
        "limit_detail": {str(d): {"line_min_sum": _num(v["line_min_sum"]), "cut": v["bottlenecks"],
                                  "total_now": _num(v.get("total_now")), "critical_total": _num(v.get("critical_total")),
                                  "total_now_minus_standard": _num(v.get("total_now_minus_standard"))}
                         for d, v in (report.get("limit_detail") or {}).items()},
        "ops": ops or {}, "propagation": report.get("propagation"),
        "basis": report.get("guarantee", {}),
        "issues": [[s, str(w), msg] for s, w, msg in issues],
    }
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    with open(path, "w", encoding="utf-8") as f:
        f.write(presentation_text(TEMPLATE, profile).replace("__DATA__", js))


def rotation_polygons(m, dec):
    """三角形・六角形ごとの回転量。頂点がすべて格子にあるものだけ。

    s⁺・σ⁺ は時計回り（右回り）、s⁻・σ⁻ は反時計回り（左回り）の回転量（エンジンの定義）。
    正味 = 時計回り − 反時計回り。
    """
    out = []
    shapes = []
    for (i, j) in sorted({(n[1], n[2]) for n in m.nodes}):
        shapes.append(("d", i, j, [("C", i, j), ("E", i, j), ("D", i, j)]))
        shapes.append(("u", i, j, [("C", i, j), ("E", i, j - 1), ("D", i + 1, j - 1)]))
        shapes.append(("h", i, j, [("C", i, j), ("E", i, j - 1), ("D", i, j),
                                   ("C", i - 1, j), ("E", i - 1, j), ("D", i, j - 1)]))
    nodes = set(m.nodes)
    for kind, i, j, vs in shapes:
        if not all(v in nodes for v in vs):
            continue
        if kind == "h":
            cw, ccw = dec["sigma"][("+", i, j)], dec["sigma"][("-", i, j)]
        else:
            cw, ccw = dec["s"][(kind, "+", i, j)], dec["s"][(kind, "-", i, j)]
        pts = [m.position(v) for v in vs]
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
        inner = all(v in m.inner_nodes for v in vs)
        out.append({"kind": kind, "i": i, "j": j, "pts": [[round(x, 6), round(y, 6)] for x, y in pts],
                    "c": [round(cx, 6), round(cy, 6)], "cw": _num(cw), "ccw": _num(ccw),
                    "net": _num(cw - ccw), "inner": inner})
    return out


TEMPLATE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>カゴメ格子解析の結果</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202c;--sub:#5d6b7a;--line:#dde3ea;--accent:#2a6fb0;--warn:#b65b13;--err:#b42318}
@media (prefers-color-scheme: dark){:root{--bg:#12161c;--card:#1b2129;--ink:#e6ebf1;--sub:#9aa7b4;--line:#2c3540;--accent:#6aa7e6;--warn:#e0a060;--err:#f08a80}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "BIZ UDPGothic","Hiragino Sans","Yu Gothic UI","Noto Sans JP",sans-serif}
header{padding:20px 24px 8px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--sub);font-size:13px}
.wrap{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:16px;padding:12px 24px 24px;align-items:start}
@media (max-width:980px){.wrap{grid-template-columns:minmax(0,1fr);padding:12px 16px}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card h2{font-size:15px;margin:0 0 8px}
.controls{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-bottom:8px}
select{font:inherit;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink)}
svg{width:100%;height:auto;display:block}
.legend{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--sub)}
.bar{height:10px;width:180px;border-radius:5px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:right;padding:4px 6px;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--sub);font-weight:600}
.side{display:flex;flex-direction:column;gap:16px}
.diagnostics{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,620px),1fr));gap:16px;padding:0 24px 16px}
.diagnostics .card{min-width:0}
.note{color:var(--sub);font-size:12.5px;margin:6px 0 0}
.detail dt{color:var(--sub);font-size:12px}
.detail dd{margin:0 0 6px;font-variant-numeric:tabular-nums}
.tag{display:inline-block;padding:0 6px;border-radius:9px;font-size:12px;border:1px solid var(--line)}
.err{color:var(--err)}.warn{color:var(--warn)}
.scroll{max-height:300px;overflow:auto}
.tbl{overflow-x:auto}
.detail dl{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:6px 0 0}
.detail dd{text-align:right}
line.sel{stroke-width:0.12}
.theory{font-size:12.5px;color:var(--sub);margin:0;padding-left:18px}
</style>
</head>
<body>
<header>
  <h1>カゴメ格子解析の結果</h1>
  <div class="sub" id="settings"></div>
</header>
<div class="diagnostics">
    <section class="card" id="effectCard"><h2>条件変更で、何が変わったか</h2><p class="note">内側の素辺と完全な内側六角形の集計です。容量比は各時点の容量に対する値。変化した量と、固定した条件を合わせて読んでください。</p><div id="effectTable" class="tbl"></div><ul id="effectObservations" class="note"></ul></section>
    <section class="card" id="directionCard"><h2>6方向の区間流量合計と標準</h2>
      <label>集計範囲 <select id="directionScope"><option value="inner">解析範囲内</option><option value="all">余白を含む全体</option></select></label>
      <div id="directions"></div>
    </section>
    <section class="card" id="rotationComparisonCard"><h2>六角形の回転量：2つの基準で比較</h2>
      <label>成分 <select id="rotationComparisonComponent"><option value="net">正味（右回り − 左回り）</option><option value="cw">右回り</option><option value="ccw">左回り</option></select></label>
      <p class="note">「同じ面の標準との差」はその場所の基準からの変化。「標準平均との差」は全体の基準に対する分布です。現況が標準そのものでも、後者は0とは限りません。差の正負は良否や実際の回転方向を意味しません。</p>
      <div id="rotationComparison" class="tbl"></div>
    </section>
    <section class="card" id="hexCompareCard"><h2>変更前後の六角形の回転量</h2>
      <label>成分 <select id="hexCompareComponent"><option value="cw">右回り</option><option value="ccw">左回り</option><option value="net">正味（右回り − 左回り）</option></select></label>
      <div id="hexCompare"></div>
    </section>
</div>
<div class="wrap">
  <main class="card">
    <div class="controls">
      <label>色分けする量 <select id="qty"></select></label>
      <div class="legend"><span id="lo"></span><div class="bar" id="bar"></div><span id="hi"></span></div>
    </div>
    <div class="controls">
      <label>回転量を重ねる <select id="rotSel"><option value="none">重ねない</option><option value="tri">三角形</option><option value="hex">六角形</option><option value="both">三角形と六角形</option></select></label>
      <label id="rotModeL">値 <select id="rotMode"><option value="now">現在の回転量</option><option value="std">同じ面の標準回転量</option><option value="dev">同じ面の標準との差</option></select></label>
      <label>回転の成分 <select id="rotComponent"><option value="net">正味（右回り − 左回り）</option><option value="cw">右回り</option><option value="ccw">左回り</option></select></label>
      <div class="legend" id="rotLegend"><span id="rneg"></span><span id="rlo"></span><div class="bar" id="rbar"></div><span id="rhi"></span><span id="rpos"></span></div>
    </div>
    <p class="note" id="rotMeanNote" hidden></p>
    <svg id="lat" role="img" aria-label="カゴメ格子の図"></svg>
    <p class="note">素辺は進む向きの左側にずらして描いている（行きと帰りを分けるため）。点線は、格子の端で直進成分が計算しきれない素辺。<span id="haloNote"></span>素辺を押すと、その値が「選んだ素辺」に出る。</p>
    <ul class="theory">
      <li>直進ポテンシャル：規格化量から対応する三角形のs/3・六角形のσ/6を差し引くモデル上の量。実測した直進の輸送量へ直接読み替えるには対応の確認が必要</li>
      <li>臨界量 ε*：フェルミ・ディラック分布の値が θ になる量（θ ＝ 0.5 ならフェルミ準位 μ）。臨界交通量 c はそれを交通量の単位に戻したもの</li>
      <li>標準状態：各素辺の臨界量をそのまま比較基準にする。節点でつり合わなくても基準を補正しない。実際の配分案では保存則と各素辺の容量を別途確認する。調和・基底状態との対応は先生に確認待ち</li>
      <li>各変数にどの物理量を当てはめるかは使う側が決める。このツールは判定や良し悪しの評価をしない</li>
    </ul>
    <details style="margin-top:12px"><summary>計算の前提と確認事項</summary><dl id="basis" class="note"></dl></details>
    <details style="margin-top:12px" id="interactionCard"><summary>参考：仮のスピン積（良否の判定には使わない）</summary><p id="interactionNote" class="note"></p><div id="interactionValues" class="tbl"></div><p class="note">標準(10,10)と現況(20,5)の積は共に100ですが、回転量は変わっています。積と回転の一致・過不足は別に読みます。右・左の成分と2つの標準との差を基本表示で確認してください。</p></details>
    <details style="margin-top:12px"><summary>共通パラメータとこの版での意味</summary><p id="geometry" class="note"></p><dl id="parameters" class="note"></dl></details>
    <details style="margin-top:12px"><summary>計算の版と再現記録</summary><pre id="provenanceInfo" class="note" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre><p class="note"><a href="provenance.json" target="_blank">識別情報と環境</a> ／ <a href="engine_snapshot.zip">当時の実装ZIP</a> ／ <a href="REPRODUCE.txt" target="_blank">再実行の手順</a></p></details>
    <details style="margin-top:12px" id="tracePanel"><summary>計算過程を見る（入力 → 規格化 → 臨界量・回転量 → 出力）</summary>
      <p class="note" id="traceNote"></p><label>状態 <select id="traceState"><option value="now">現況</option><option value="standard">標準</option></select></label>
      <div id="traceEdge" class="note">素辺をクリックすると、その計算過程を表示します。</div>
      <label>回転の内訳 <select id="traceRing"></select></label><div id="traceTerms" class="tbl"></div>
    </details>
  </main>
  <aside class="side">
    <section class="card" id="chgCard"><h2>シナリオで変えた値</h2><div id="chg" class="scroll"></div></section>
    <section class="card"><h2>選んだ素辺</h2><div id="detail" class="detail note">素辺を押すと値が出る。</div></section>
    <section class="card" id="limitCard"><details><summary>操作に用いる全体の上限・参考値</summary><div id="limit"></div></details></section>
    <section class="card" id="globalCard"><h2>グローバルの操作（入口での受け入れ）</h2><div id="global"></div></section>
    <section class="card" id="localCard"><h2>ローカルの操作（格子の中でずらす）</h2><div id="local"></div></section>
    <section class="card"><h2>入力の検査</h2><div id="issues" class="scroll"></div></section>
  </aside>
</div>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const fmt = (x, d=2) => (x === null || x === undefined) ? "–" : (Math.abs(Number(x)) < 0.5 * 10 ** (-d) ? 0 : Number(x)).toLocaleString("ja-JP", {maximumFractionDigits: d});
const RN = {1:"→",2:"↗",3:"↖",4:"←",5:"↙",6:"↘"};
const EM={mean_j:'規格化量J・平均',hex_cw_mean:'右回り・平均',hex_ccw_mean:'左回り・平均',hex_net_mean:'正味回転・平均',standard_net_mean:'標準の正味回転・平均',max_usage:'最大容量比 V/c',over_capacity_edges:'容量超過の素辺数',equivalent_occupancy_mean:'換算した素片内の量n・平均',inflow_requested:'入口の要求量',inflow_total:'入口から入った量',outflow_total:'出口から出た量'};
if(D.comparison_summary){const comparison=D.comparison_summary;
  const display=(key,value)=>value==null?'–':key==='max_usage'?fmt(value*100,3)+'%':fmt(value,6);
  $('effectTable').innerHTML='<table><thead><tr><th>量</th><th>変更前</th><th>変更後</th><th>後−前</th></tr></thead><tbody>'+Object.entries(EM).filter(([key])=>comparison.values[key]?.before!=null||comparison.values[key]?.after!=null).map(([key,label])=>{const row=comparison.values[key];return `<tr><td>${label}</td><td>${display(key,row.before)}</td><td>${display(key,row.after)}</td><td>${key==='max_usage'?(row.change==null?'–':fmt(row.change*100,3)+'ポイント'):display(key,row.change)}</td></tr>`;}).join('')+'</tbody></table>';
  $('effectObservations').replaceChildren(...[...comparison.observations,comparison.note].map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));
  if(comparison.changed_parameters?.length){const li=document.createElement('li');li.textContent='変更した入力：'+comparison.changed_parameters.map(row=>`${row.source}.${row.parameter} ${row.before} → ${row.after}（${row.rows}行）`).join(' ／ ')+'。一覧にない入力列は変更なしです。';$('effectObservations').prepend(li);}
}else $('effectCard').hidden=true;
const BASIS_NAMES = {normalization:"規格化",source_formula:"原資料との式の対応",routing_convention:"進行方向と回転の規約",decomposition:"回転量と分解",propagation:"流れの伝播",estimate:"入口の推定",halo:"余白",critical:"臨界量",standard:"標準状態",limit:"向きごとの上限",hex_rotation:"六角形の標準平均との差",spin_interactions:"スピン相互作用（暫定）",vertex_model:"頂点模型（暫定）",global:"グローバル操作",local:"ローカル操作"};
document.title = `${D.profile_info.name} — カゴメ格子解析`;
document.querySelector("h1").textContent = `${D.profile_info.name} — カゴメ格子解析の結果`;
$("provenanceInfo").textContent=D.provenance?`ソフト ${D.provenance.software_version}\n式の版 ${D.provenance.formula_version}\n計算実装 SHA-256 ${D.provenance.engine_sha256}\n入力 SHA-256 ${D.provenance.input_sha256}\n${D.provenance.note}`:"この保存結果には識別記録がありません（旧版）。";
for(const [key,param] of Object.entries(D.profile_info.parameters)){
  const dt=document.createElement("dt"), dd=document.createElement("dd");
  dt.textContent=`${key}：${param.label} [${param.unit}]`;
  dd.textContent=param.meaning; $("parameters").append(dt,dd);
}
$("geometry").textContent=`解析範囲の節点 ${fmt(D.geometry.inner_nodes,0)} 個、有向素辺 ${fmt(D.geometry.inner_directed_edges,0)} 本。各素辺の並列経路数 m と格子の接続本数は別。図は接続関係を示し、入力した長さ L を縮尺で描くものではない。 ${D.profile_info.note}`;
for(const [key,note] of Object.entries(D.basis||{})){
  const dt=document.createElement("dt"),dd=document.createElement("dd");
  dt.textContent=BASIS_NAMES[key]||key; dd.textContent=note; dd.style.margin="0 0 8px";
  $("basis").append(dt,dd);
}

// 設定
const s = D.settings, pr = D.propagation;
const NAMES={norm:{k:"V/(v·m)（1 車線あたりの密度）",m:"V/m（原資料のj）","mvl":"V·v/(L·m)"},tau:{count:"総流量Vから（比較用）",engine:D.settings.norm==="m"?"jから（原資料の式）":"規格化量Jから（比較用）"},eps:{straight:"直進成分",total:"規格化した交通量"},lim:{critical_total:"臨界交通量の総和",through_maxflow:"通り抜けの最大流",line_min_sum:"紐の上は最小・平行な紐は和"}};
$("settings").textContent = `N=${s.n}${s.halo?"（周りに余白 1 リング）":""}・${s.mode === "propagate" ? "伝播モード" : "観測モード"}・規格化 ${NAMES.norm[s.norm]}・τ ${NAMES.tau[s.tau_mode]}・臨界点と比べる量 ${NAMES.eps[s.eps]}・θ=${s.theta}・向きごとの上限 ${NAMES.lim[s.limit_rule]}` +
  (D.estimate ? `・流量から求めた入口の流入量の合計 ${fmt(D.estimate.inflow_total,1)}（説明できない分 ${fmt(100*D.estimate.unexplained_share,2)}%）` : "") +
  (s.compared_with ? `・比べる相手：${s.compared_with}` : "") +
  (pr ? `・入口から入った量 ${fmt(pr.inflow_total,1)}（求められた量 ${fmt(pr.inflow_requested,1)}）／出口から出た量 ${fmt(pr.outflow_total,1)}` : "");

if (s.halo) $("haloNote").textContent = "薄い素辺は余白（解析の対象は内側。色の範囲も内側の値で決める）。";
// 色
const SEQ = ["#0d0887","#5b02a3","#9a179b","#cb4678","#eb7852","#fbb32f","#f0f921"];
const DIV = ["#2166ac","#67a9cf","#a9c6dc","#c3c9d1","#e8b9a2","#ef8a62","#b2182b"];
function lerp(c1,c2,t){const a=parseInt(c1.slice(1),16),b=parseInt(c2.slice(1),16);
  const r=Math.round(((a>>16)&255)+(((b>>16)&255)-((a>>16)&255))*t), g=Math.round(((a>>8)&255)+(((b>>8)&255)-((a>>8)&255))*t), bl=Math.round((a&255)+((b&255)-(a&255))*t);
  return `rgb(${r},${g},${bl})`;}
function ramp(stops,t){t=Math.max(0,Math.min(1,t));const k=t*(stops.length-1),i=Math.min(stops.length-2,Math.floor(k));return lerp(stops[i],stops[i+1],k-i);}

// 格子
const svg = $("lat"), NS = "http://www.w3.org/2000/svg";
const xs = D.nodes.map(n=>n.p[0]), ys = D.nodes.map(n=>n.p[1]);
const minx=Math.min(...xs)-0.6, maxx=Math.max(...xs)+0.6, miny=Math.min(...ys)-0.6, maxy=Math.max(...ys)+0.6;
svg.setAttribute("viewBox", `${minx} ${-maxy} ${maxx-minx} ${maxy-miny}`);
const rotLayer=document.createElementNS(NS,"g"); svg.append(rotLayer);
const polys=[];
for (const r of D.rot){
  const g=document.createElementNS(NS,"g"); g.style.cursor="pointer";
  const pg=document.createElementNS(NS,"polygon"); pg.setAttribute("points", r.pts.map(([x,y])=>`${x},${-y}`).join(" "));
  pg.setAttribute("stroke","none");
  const tx=document.createElementNS(NS,"text"); Object.entries({x:r.c[0],y:-r.c[1]+0.07,"text-anchor":"middle","font-size":r.kind==="h"?0.32:0.2,fill:"var(--ink)",opacity:0.75}).forEach(([k,v])=>tx.setAttribute(k,v));
  const tt=document.createElementNS(NS,"title");
  g.append(pg,tx,tt); if(!r.inner) g.setAttribute("opacity","0.35"); rotLayer.append(g);
  g.addEventListener("click",()=>showRot(r));
  polys.push({r,g,pg,tx,tt});
}
const segs = [];
for (const e of D.edges){
  const [ax,ay]=e.a,[bx,by]=e.b, dx=bx-ax, dy=by-ay, n=Math.hypot(dx,dy), ox=-dy/n*0.07, oy=dx/n*0.07;
  const x1=ax+0.16*dx+ox, y1=ay+0.16*dy+oy, x2=ax+0.84*dx+ox, y2=ay+0.84*dy+oy;
  const g=document.createElementNS(NS,"g"); g.style.cursor="pointer";
  const hit=document.createElementNS(NS,"line"); Object.entries({x1,y1:-y1,x2,y2:-y2,stroke:"transparent","stroke-width":0.16}).forEach(([k,v])=>hit.setAttribute(k,v));
  const ln=document.createElementNS(NS,"line"); Object.entries({x1,y1:-y1,x2,y2:-y2,"stroke-width":0.07,"stroke-linecap":"round"}).forEach(([k,v])=>ln.setAttribute(k,v));
  if(!e.complete) ln.setAttribute("stroke-dasharray","0.06 0.06");
  if(!e.inner) g.setAttribute("opacity","0.3");
  const hx=x2-0.1*dx/n, hy=y2-0.1*dy/n, px=-dy/n*0.04, py=dx/n*0.04;
  const head=document.createElementNS(NS,"polygon"); head.setAttribute("points",`${x2},${-y2} ${hx+px},${-(hy+py)} ${hx-px},${-(hy-py)}`); head.setAttribute("fill","#333"); head.setAttribute("opacity","0.55");
  g.append(hit,ln,head); svg.append(g);
  g.addEventListener("click",()=>{segs.forEach(z=>z.ln.classList.remove("sel")); ln.classList.add("sel"); show(e);});
  const title=document.createElementNS(NS,"title"); g.append(title);
  segs.push({e,ln,title});
}
for (const nd of D.nodes){
  const c=document.createElementNS(NS,"circle"); Object.entries({cx:nd.p[0],cy:-nd.p[1],r:0.13,fill:"var(--card)",stroke:"var(--sub)","stroke-width":0.02}).forEach(([k,v])=>c.setAttribute(k,v));
  const t=document.createElementNS(NS,"text"); Object.entries({x:nd.p[0],y:-nd.p[1]+0.045,"text-anchor":"middle","font-size":0.13,fill:"var(--ink)"}).forEach(([k,v])=>t.setAttribute(k,v)); t.textContent=nd.t;
  svg.append(c,t);
}

// 量の選択
const sel=$("qty");
for (const k of D.available){const o=document.createElement("option"); o.value=k; o.textContent=D.labels[k]; sel.append(o);}
if (D.available.includes("usage")) sel.value="usage";
if (s.compared_with && D.available.includes("dV")) sel.value="dV";
function paint(){
  const k=sel.value;
  if(k.startsWith("cut")){
    for (const {e,ln,title} of segs){const v=e.q[k]; ln.setAttribute("stroke", v? "#d62728" : "#c9ced6");
      title.textContent=`${e.id}（向き ${e.road} ${RN[e.road]}）${v?"：細い所":""}`;}
    $("lo").textContent="それ以外"; $("hi").textContent="細い所"; $("bar").style.background="linear-gradient(90deg,#c9ced6 50%,#d62728 50%)";
    return;
  }
  const vals=D.edges.filter(e=>e.inner).map(e=>e.q[k]).filter(v=>v!==null&&v!==undefined);
  let lo=Math.min(...vals), hi=Math.max(...vals); const div=(k==="dV"||k==="margin"||k==="unexplained"||k==="dev_std");
  if(div){const m=Math.max(Math.abs(lo),Math.abs(hi))||1; lo=-m; hi=m;}
  const stops=div?DIV:SEQ;
  for (const {e,ln,title} of segs){const v=e.q[k];
    ln.setAttribute("stroke", v===null||v===undefined ? "#aaa" : ramp(stops,(v-lo)/((hi-lo)||1)));
    title.textContent=`${e.id}（向き ${e.road} ${RN[e.road]}）  ${D.labels[k]}: ${fmt(v,3)}`;}
  $("lo").textContent=fmt(lo,2); $("hi").textContent=fmt(hi,2);
  $("bar").style.background=`linear-gradient(90deg,${stops.join(",")})`;
}
sel.addEventListener("change",paint); paint();

const KN={d:"下向きの三角形",u:"上向きの三角形",h:"六角形"};
const rsel=$("rotSel"), rmode=$("rotMode"), rcomponent=$("rotComponent");
const COMPONENTS={cw:"右回り",ccw:"左回り",net:"正味"};
const mean = D.hex_rotation?.standard_mean;
if(mean){
  for(const [k,label] of Object.entries(COMPONENTS)){
    const opt=document.createElement("option");
    opt.value=k; opt.textContent=`六角形の標準平均との差（${label}）`; rmode.append(opt);
  }
}
function rotationValue(r, mode, component){
  if(Object.hasOwn(COMPONENTS,mode)) return r.minus_mean?.[mode]??null;
  if(mode==="now") return r[component]??null;
  const standard=r["std_"+component];
  if(standard==null) return null;
  return mode==="std"?standard:r[component]-standard;
}
function paintRot(){
  const w=rsel.value, md=rmode.value, byMean=Object.hasOwn(COMPONENTS,md), component=byMean?md:rcomponent.value;
  rcomponent.disabled=byMean;
  const difference=byMean||md==="dev", signed=difference||component==="net";
  const show=r=>{
    if(byMean) return w!=="none"&&!!r.minus_mean;
    return w==="both"||(w==="tri"&&r.kind!=="h")||(w==="hex"&&r.kind==="h");
  };
  const vis=polys.filter(p=>show(p.r));
  const val=r=>rotationValue(r,md,component);
  const vals=vis.filter(p=>p.r.inner&&val(p.r)!==null).map(p=>Math.abs(val(p.r)));
  const mx=Math.max(1e-12,...vals);
  for(const p of polys){
    if(!show(p.r)){p.g.style.display="none";continue;}
    p.g.style.display="";
    const v=val(p.r); p.pg.setAttribute("fill", v===null?"transparent":ramp(signed?DIV:SEQ,signed?(v+mx)/(2*mx):v/mx));
    p.pg.setAttribute("fill-opacity","0.6");
    p.tx.textContent = v===null||Math.abs(v)<1e-9*mx ? "" : difference ? (v>0?"+":"−") : component==="ccw"?"↺":component==="cw"?"↻":(v>0?"↻":"↺");
    p.tt.textContent=byMean
      ? `六角形 (${p.r.i},${p.r.j})  ${COMPONENTS[md]}の標準平均との差 ${fmt(v,3)}`
      : `${KN[p.r.kind]} (${p.r.i},${p.r.j})  ${COMPONENTS[component]}：${rmode.selectedOptions[0].textContent} ${fmt(v,3)}／現況 ${fmt(p.r[component],3)}／同じ図形の標準 ${fmt(p.r["std_"+component],3)}`;
  }
  $("rotLegend").style.display = w==="none" ? "none" : "";
  $("rneg").textContent=difference?(byMean?"平均より少ない":"同じ図形の標準より少ない"):component==="net"?"反時計回り ↺":"回転量が少ない";
  $("rpos").textContent=difference?(byMean?"平均より多い":"同じ図形の標準より多い"):component==="net"?"↻ 時計回り":"回転量が多い";
  $("rotMeanNote").hidden=!byMean||w==="none";
  if(byMean) $("rotMeanNote").textContent=`標準状態の六角形 ${D.hex_rotation.count} 個の平均（${COMPONENTS[md]}） ${fmt(mean[md],3)}。色は現況からこの平均を引いた差。`;
  $("rlo").textContent=fmt(signed?-mx:0,1); $("rhi").textContent=fmt(mx,1);
  $("rbar").style.background=`linear-gradient(90deg,${(signed?DIV:SEQ).join(",")})`;
}
rsel.addEventListener("change",()=>{
  if(rsel.value!=="hex"&&Object.hasOwn(COMPONENTS,rmode.value)) rmode.value="now";
  paintRot();
});
rmode.addEventListener("change",()=>{
  if(Object.hasOwn(COMPONENTS,rmode.value)){rsel.value="hex";rcomponent.value=rmode.value;}
  paintRot();
});
rcomponent.addEventListener("change",paintRot);
if(!D.rot.some(r=>r.std_net!==undefined)) $("rotModeL").style.display="none";
paintRot();
function paintRotationComparison(){
  const component=$("rotationComparisonComponent").value;
  const rows=D.rot.filter(r=>r.kind==="h"&&r.minus_mean&&r["std_"+component]!=null);
  if(!rows.length){$("rotationComparison").textContent="解析範囲内の完全な六角形と標準状態がそろうと比較できます。";return;}
  const mean=D.hex_rotation.standard_mean[component];
  $("rotationComparison").innerHTML="<table><thead><tr><th>六角形</th><th>現在値</th><th>同じ面の標準</th><th>同じ面の標準との差</th><th>全体の標準平均</th><th>標準平均との差</th></tr></thead><tbody>"+
    rows.map(r=>`<tr><td>(${r.i},${r.j})</td><td>${fmt(r[component],6)}</td><td>${fmt(r["std_"+component],6)}</td><td>${fmt(r[component]-r["std_"+component],6)}</td><td>${fmt(mean,6)}</td><td>${fmt(r.minus_mean[component],6)}</td></tr>`).join("")+"</tbody></table>";
}
$("rotationComparisonComponent").onchange=paintRotationComparison;paintRotationComparison();
const interaction=D.spin_interactions;
if(interaction){
  $("interactionNote").textContent=interaction.available===false?"算定保留："+interaction.reason:interaction.note;
  const names={antiferro_tri_hex:"三角形と六角形",ferro_tri_tri:"三角形同士",ferro_hex_hex:"六角形同士",quadrupole:"4面の積"};
  $("interactionValues").innerHTML="<table><thead><tr><th>対象</th><th>組数</th><th>現在の積の合計</th><th>標準の積の合計</th><th>差の合計</th></tr></thead><tbody>"+
    Object.entries(interaction.types).map(([key,row])=>`<tr><td>${names[key]||key}</td><td>${row.count}</td><td>${fmt(row.now,6)}</td><td>${fmt(row.standard,6)}</td><td>${fmt(row.diff,6)}</td></tr>`).join("")+"</tbody></table>";
}else $("interactionCard").hidden=true;
function showRot(r){
  const rows=[["時計回りの回転量",fmt(r.cw,3)],["反時計回りの回転量",fmt(r.ccw,3)],["正味（時計回り − 反時計回り）",fmt(r.net,3)]];
  for(const [key,label] of Object.entries(COMPONENTS)){
    rows.push([`同じ図形の標準（${label}）`,fmt(r["std_"+key],3)],
      [`同じ図形の標準値との差（${label}）`,r["std_"+key]==null?"–":fmt(r[key]-r["std_"+key],3)]);
  }
  if(r.minus_mean){
    for(const [k,label] of Object.entries(COMPONENTS)){
      rows.push([`${label}の標準平均との差`,fmt(r.minus_mean[k],3)]);
    }
  }
  $("detail").innerHTML=`<strong>${KN[r.kind]} (${r.i},${r.j})</strong>${r.inner?"":" <span class='tag'>余白</span>"}<dl>`+
    rows.map(x=>`<dt>${x[0]}</dt><dd>${x[1]}</dd>`).join("")+
    "</dl><p class='note'>回転量は、この図形の頂点で図形に沿って曲がる流れ（局所回転 τ）の合計。</p>";
}

function show(e){
  traceEdge(e.id);
  const q=e.q, rows=[["向き",`${e.road} ${RN[e.road]}`],["流量 V",fmt(q.V,2)],[(D.cmp_label||"操作の前")+"の流量",fmt(q.V_before,2)],["説明できない分",fmt(q.unexplained,2)],["規格化した流れ J",fmt(q.J,3)],
    ["直進成分",fmt(q.J_straight,3)+(e.complete?"":"（格子の端で計算しきれない）")],["臨界量 ε*",fmt(q.eps_star,3)],["臨界量に対する比",fmt(q.ratio,3)],
    ["増加型の分布値 f（大きさだけで良否を判定しない）",fmt(q.f,4)],["臨界交通量 c（標準状態の交通量）",fmt(q.capacity,2)],["臨界交通量に対する比",fmt(q.usage,3)],["同じ素辺の標準との差",fmt(q.dev_std,2)],
    ...["m","L","v","T","mu"].map(k=>[`${D.profile_info.parameters[k].label} ${k} [${D.profile_info.parameters[k].unit}]`,fmt(q[k],3)])];
  $("detail").innerHTML=`<strong>${e.id}</strong>${e.inner?"":" <span class='tag'>余白</span>"}<dl>`+rows.filter(r=>r[1]!=="–").map(r=>`<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join("")+"</dl>";
}

let selectedTraceEdge=null;
function traceEdge(id){
  selectedTraceEdge=id;
  const state=D.trace?.[$("traceState").value], row=state?.edges[id];
  if(!row) return;
  const q=row.inputs, st=row.straight, cr=row.critical;
  const lines=[`${id}：m=${fmt(q.m,6)}, L=${fmt(q.L,6)}, v=${fmt(q.v,6)}, V=${fmt(row.V,6)}`,
    `素片内の量：n=V×L/v=${fmt(row.n_equivalent,6)}、原資料の流量j=V/m=${fmt(row.j_source,6)}`,
    `規格化：D=${fmt(row.denormalize_factor,6)}、J=V/D=${fmt(row.J,6)}`];
  if(cr) lines.push(`臨界量：ε*=μ+T×ln(θ/(1−θ))=${fmt(cr.eps_star,6)}、比較量ε=${fmt(cr.eps,6)}、分布f=${fmt(cr.f,6)}`,
    `標準流量c=ε*×D=${fmt(row.standard_flow,6)}、現況−標準=${fmt(row.minus_standard,6)}、現況/標準=${fmt(row.usage,6)}`);
  lines.push(`直進成分：J−s/3−σ/6=${fmt(row.J,6)}−${fmt(st.s_over_3,6)}−${fmt(st.sigma_over_6,6)}=${fmt(st.recomputed,6)}`,
    `計算出力=${fmt(st.value,6)}。${st.complete?"必要な周囲の値がそろっています。":"格子の端で必要な値が不足しています。この値で内側の完全な計算を代用しないでください。"}`);
  $("traceEdge").textContent=lines.join("\n");$("traceEdge").style.whiteSpace="pre-wrap";
}
function traceTerms(){
  const rings=D.trace?.[$("traceState").value]?.rings||[], row=rings[Number($("traceRing").value)];
  $("traceTerms").replaceChildren();if(!row) return;
  const note=document.createElement("p");note.className="note";
  note.textContent=`各項は${D.trace.tau_mode==="count"?"V_in×β×L_in/(D_out×L_out)":"J_in×β×L_in/(m_out×L_out)"}。項の和=${fmt(row.recomputed,6)}、計算出力=${fmt(row.value,6)}。`;
  const table=document.createElement("table"), head=table.insertRow();
  ["節点","流入辺","流出辺","分子の流量","β","流入長","流出長","除数","τ"].forEach(t=>{const th=document.createElement("th");th.textContent=t;head.append(th);});
  for(const t of row.terms){const tr=table.insertRow();
    [t.node.join(","),t.incoming_edge||"不足",t.outgoing_edge||"不足",fmt(t.numerator_flow,6),fmt(t.beta,6),fmt(t.L_in,6),fmt(t.L_out,6),fmt(t.divisor,6),fmt(t.value,6)].forEach(value=>{tr.insertCell().textContent=value;});}
  $("traceTerms").append(note,table);
}
function traceState(){
  const previous=$("traceRing").value;
  const rings=D.trace?.[$("traceState").value]?.rings||[];
  $("traceRing").replaceChildren();rings.forEach((r,i)=>$("traceRing").add(new Option(`${KN[r.kind]} (${r.i},${r.j}) ${r.component==="cw"?"右回り":"左回り"}`,i)));
  if(previous!==""&&Number(previous)<rings.length) $("traceRing").value=previous;
  if(!rings.length) $("traceRing").add(new Option("解析範囲内の完全な図形がありません",""));
  traceTerms();if(selectedTraceEdge) traceEdge(selectedTraceEdge);
}
if(D.trace){$("traceNote").textContent=D.trace.note;$("traceState").options[1].disabled=!D.trace.standard;
  $("traceState").addEventListener("change",traceState);$("traceRing").addEventListener("change",traceTerms);traceState();
}else $("tracePanel").hidden=true;

// 解析範囲を選んだ方向別診断。操作の全体上限とは範囲を区別する。
function paintDirections(){
  const scope=$("directionScope").value, rows=D.direction_comparison.scopes[scope];
  $("directions").innerHTML=`<div class="tbl"><table><tr><th>向き</th><th>素辺数</th><th>標準</th><th>現況</th><th>現況 − 標準</th><th>現況/標準</th><th>臨界超過の素辺数</th></tr>`+
    Object.entries(rows).map(([d,v])=>`<tr><td>${d} ${RN[d]}</td><td>${v.edges}</td><td>${fmt(v.standard,1)}</td><td>${fmt(v.now,1)}</td><td>${fmt(v.difference,1)}</td><td>${v.ratio===null?"–":fmt(100*v.ratio,1)+"%"}</td><td>${v.over_capacity_edges}</td></tr>`).join("")+"</table></div>"+
    `<p class="note">${scope==="inner"?"両端が解析範囲内の素辺を集計。六角形の平均も同じ解析範囲内で求める。":"計算に使う余白も含めた全素辺を集計。入口の操作で用いる範囲。"} 方向の合計が標準以下でも、個々の素辺では臨界量を超える場合がある。直列の素辺もそれぞれ数える。</p>`;
}
if(D.direction_comparison){
  if(!s.halo) $("directionScope").options[1].textContent="全体（解析範囲と同じ）";
  $("directionScope").addEventListener("change",paintDirections); paintDirections();
} else $("directionCard").style.display="none";

function paintHexComparison(){
  const rows=D.hex_scenario_comparison.filter(r=>r.component===$("hexCompareComponent").value);
  $("hexCompare").innerHTML=`<p class="note">共通の基準：変更前の標準平均 ${fmt(rows[0].reference_mean,3)}。変更後の条件で求めた標準平均は ${fmt(rows[0].scenario_standard_mean,3)}。</p>`+
    `<div class="tbl"><table><tr><th>六角形</th><th>変更前</th><th>変更後</th><th>変化</th><th>前 − 共通基準</th><th>後 − 共通基準</th></tr>`+
    rows.map(r=>`<tr><td>(${r.i},${r.j})</td><td>${fmt(r.before,3)}</td><td>${fmt(r.after,3)}</td><td>${fmt(r.change,3)}</td><td>${fmt(r.before_minus_reference,3)}</td><td>${fmt(r.after_minus_reference,3)}</td></tr>`).join("")+"</table></div>"+
    `<p class="note">正味が同じでも右回り・左回りがともに変わる場合がある。3成分を切り替えて確認する。変化の良し悪しは、この差だけでは判定しない。</p>`;
}
if(D.hex_scenario_comparison.length){
  $("hexCompareComponent").addEventListener("change",paintHexComparison); paintHexComparison();
} else $("hexCompareCard").style.display="none";

// 上限
const L=D.limit, LD=D.limit_detail||{};
if(Object.keys(L).length){
  const RL={critical_total:"全素辺の臨界交通量の、向きごとの総和（資料 p.16）",through_maxflow:"参考：通り抜けの最大流",line_min_sum:"参考：紐ごとの最小の和"};
  const critical=s.limit_rule==="critical_total";
  $("limit").innerHTML=`<p class="note">${RL[s.limit_rule]||""}</p><div class="tbl"><table><tr><th>向き</th><th>標準</th><th>現況</th><th>現況 − 標準</th>${critical?"":"<th>参考上限</th>"}<th>割合</th></tr>`+
  Object.entries(L).map(([d,v])=>{
    const ld=LD[d]||{}, t=ld.total_now, diff=ld.total_now_minus_standard;
    return `<tr><td>${d} ${RN[d]}</td><td>${fmt(ld.critical_total,1)}</td><td>${fmt(t,1)}</td><td>${diff>0?"+":""}${fmt(diff,1)}</td>${critical?"":`<td>${fmt(v,1)}</td>`}<td>${v?fmt(100*t/v,1)+"%":"–"}</td></tr>`;
  }).join("")+"</table></div>"+
  `<p class='note'>余白を含む全素辺が対象。現況と標準は同じ向きの素辺の交通量の和。割合は現況を${critical?"標準":"参考上限"}で割った値。</p>`;
} else $("limitCard").style.display="none";

// グローバル
const G=D.ops.global;
if(G&&G.rule==="direction"){const ld=G.load;
  $("global").innerHTML=`<p class="note">向きごとの総交通量が道路インフラ限界を超えないように、全部の入口を同じ割合で上げていき、限界に達した向きに流れ込む入口から止める（資料 p.16 の限界を使う）。</p>`+
  `<div class="detail"><dl><dt>入りたい量</dt><dd>${fmt(G.requested,1)}</dd><dt>入れた量</dt><dd><strong>${fmt(G.admitted_total,1)}</strong>（${fmt(100*G.admitted_total/(G.requested||1),1)}%）</dd><dt>限界に達した向き</dt><dd>${G.tight.length?G.tight.map(d=>d+" "+RN[d]).join("、"):"なし"}</dd></dl></div>`+
  "<div class='tbl'><table><tr><th>向き</th><th>限界</th><th>入れる前</th><th>入れた後</th></tr>"+
  Object.entries(ld).map(([d,v])=>`<tr><td>${d} ${RN[d]}</td><td>${fmt(v.limit,1)}</td><td>${fmt(v.before,1)}</td><td>${fmt(v.after,1)}</td></tr>`).join("")+"</table></div>"+
  "<p class='note'>総交通量は向きごとの素辺の交通量の和。どの素辺が臨界を超えるかはローカルで扱う。</p>";
} else if(G){const bd=G.by_direction;
  $("global").innerHTML=`<p class="note">全体の最大流で、全部の入口を同じ割合で上げていき、詰まった入口から順に止める。出口は${G.exits==="keep"?"今の配分のまま":"どこから出てもよい"}。</p>`+
  `<div class="detail"><dl><dt>入りたい量</dt><dd>${fmt(G.requested,1)}</dd><dt>入れた量</dt><dd><strong>${fmt(G.admitted_total,1)}</strong>（${fmt(100*G.admitted_total/(G.requested||1),1)}%）</dd>`+
  `<dt>参考：全部同じ割合で絞ると</dt><dd>${fmt(100*G.uniform_ratio,1)}%</dd><dt>参考：ローカルを使わずに収まるのは</dt><dd>${fmt(100*G.no_local_ratio,1)}%</dd>`+
  `<dt>最大流の回し方の例で容量を超える素辺</dt><dd>${G.routing_over} 本</dd></dl></div>`+
  "<div class='tbl'><table><tr><th>向き</th><th>入りたい量</th><th>入れた量</th><th>入れず</th></tr>"+
  Object.entries(bd).filter(([d,v])=>v.demand>0).map(([d,v])=>`<tr><td>${d} ${RN[d]}</td><td>${fmt(v.demand,1)}</td><td>${fmt(v.admitted,1)}</td><td>${fmt(v.rejected,1)}</td></tr>`).join("")+"</table></div>"+
  (G.rejected_total>1e-6?`<p class="note">止めたのは細い所に詰まった入口。決め手になった細い所：素辺 ${G.cut.length} 本${G.cut_exits.length?`、出口 ${G.cut_exits.length} か所（出口の配分が決め手）`:""}（「色分けする量」の「受け入れを決めた細い所」）。</p>`:"")+
  "<p class='note'>入れた量なら、容量以内に収まる回し方が必ずある（例は branching_maxflow.csv）。</p>";
} else $("globalCard").style.display="none";

// ローカル
const Lo=D.ops.local;
if(Lo){const mv=Lo.moves.slice(0,30);
  const status=Lo.resolved?"<strong>すべての素辺が容量以内になった</strong>":`<span class="warn">操作は未解決。現在の容量超過は ${Object.keys(Lo.remaining).length} 本（${Lo.stop_reason}）</span>`;
  const spin=`回転量（スピン）の変化 ${fmt(100*Lo.spin_change/Math.max(Lo.spin_total,1e-12),1)}%`;
  if(Lo.rule==="lp"){
    const OBJ={tau:"局所回転 τ（スピンの素）の変更",flow:"流れの量の変更",branch:"分岐の割合の変更"};
    const p3=v=>v.map(x=>fmt(x,2)).join(" / ");
    $("local").innerHTML=`<p class="note">最小変更（線形計画）：<strong>${OBJ[Lo.objective]}</strong>が最小になる回し方。${status}。変えた交差点 ${Lo.nodes_changed} か所、${spin}。</p>`+
    "<div class='scroll tbl'><table><tr><th>交差点</th><th>来た向き</th><th>前 S/R/L</th><th>後 S/R/L</th></tr>"+
    mv.map(x=>`<tr><td>${x.node}</td><td>${x.in_road} ${RN[x.in_road]}</td><td>${p3(x.before)}</td><td>${p3(x.after)}</td></tr>`).join("")+"</table></div>"+
    (Lo.moves.length>30?`<p class="note">変化の大きい 30 件（全 ${Lo.moves.length} 件は local_changes.csv）。</p>`:"")+
    `<p class='note'>${D.basis.local||"指定した容量・出口条件を満たす解の有無を計算する。"}</p>`;
  } else {
  $("local").innerHTML=`<p class="note">規則：${Lo.rule==="spot"?"その場で振り分け":"三角形で迂回して戻る"}。${status}（${Lo.iterations} 回）。${spin}。</p>`+
  "<div class='scroll'><table><tr><th>超えた素辺</th><th>交差点</th><th>来た向き</th><th>回し方</th><th>量</th></tr>"+
  mv.map(x=>`<tr><td>${x.edge}</td><td>${x.node}</td><td>${x.in_road}</td><td>${x.kind==="spot"?"その場":"迂回"}</td><td>${fmt(x.amount,1)}</td></tr>`).join("")+"</table></div>"+
  (Lo.moves.length>30?`<p class="note">上位 30 件（全 ${Lo.moves.length} 件は local_moves.csv）。</p>`:"");
  }
} else $("localCard").style.display="none";

// シナリオ
const FN={edges:"素辺",branching:"分岐の割合",entrances:"入口の流入量",settings:"配分調整の設定"};
if(D.changes.length){$("chg").innerHTML="<table><tr><th>種類</th><th>場所</th><th>列</th><th>もと</th><th>変更後</th></tr>"+D.changes.map(c=>`<tr><td>${FN[c[0]]||c[0]}</td><td>${c[1]}</td><td>${c[2]}</td><td>${c[3]}</td><td>${c[4]}</td></tr>`).join("")+"</table><p class='note'>色分けの「もとの条件からの流量の変化」で、変更の影響が格子のどこまで及ぶかを見られる。</p>";} else $("chgCard").style.display="none";
// 検査
$("issues").innerHTML = D.issues.length ? "<table>"+D.issues.map(([s,w,m])=>`<tr><td class="${s==='error'?'err':'warn'}">${s==='error'?'誤り':'注意'}</td><td style="text-align:left;white-space:normal">${w}：${m}</td></tr>`).join("")+"</table>" : "<p class='note'>問題は見つからなかった。</p>";
</script>
</body>
</html>
"""
