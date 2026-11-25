# -*- coding: utf-8 -*-
"""スピン相互作用と頂点模型（資料 p.13・p.15〜17）。先生の式が出るまでの暫定の形。

資料p.15の図は上向き三角を縮約したハニカム格子。本モジュールの面の組は
縮約前のカゴメ格子上の実装仮定であり、その図との同一性は確認していない。

■ スピン
  三角形・六角形ごとの正味の回転量 S ＝ 時計回り − 反時計回り（分解の s・σ）。

■ 4 種のスピン相互作用（資料 p.13「1 種類の反強磁性型、2 種類の強磁性型、1 種類の 4 重極型」）
  カゴメ格子の交差点には、三角形 2 つと六角形 2 つが「三角形・六角形・三角形・六角形」の順に集まる。
  その組み合わせを、資料の数に合わせて次のように置く。
    反強磁性型  三角形と六角形（辺を共有）  … 辺を流れる量は、片方には時計回り、もう片方には反時計回りに効く
    強磁性型①  三角形と三角形（交差点を共有）
    強磁性型②  六角形と六角形（交差点を共有）
    4 重極型    交差点の周りの 4 つ（三角形 2・六角形 2）
  相互作用の量（その型の状態にどれだけ合っているか。大きいほど合っている）：
    強磁性型   q ＝ S_i·S_j          反強磁性型 q ＝ −S_i·S_j          4 重極型 q ＝ S_1·S_2·S_3·S_4
  S は標準状態の |S| の平均で割って無次元にする。結合の強さはすべて 1（先生の式を受けて置き換える）。
  資料 p.16「標準交通状況における反磁性・強磁性・4 重極状態からの差の総量」として、
  型ごとに Σ(今 − 標準)（符号つき）と Σ|今 − 標準|（差の総量）を出す。

■ 頂点模型（資料 p.17 の 8 頂点模型）
  交差点は 2 本の紐の交わり（腕 4 本）。腕ごとの正味の流れ（出る量 − 入る量）の向きで分類する。
    a（dipole、双極）      流れ込む 2 本の腕が 60° …… 流れがそろって通り抜ける
    b（saddle、鞍点）      流れ込む 2 本の腕が 120° … 流れが曲がって分かれる
    c（quadrupole、4 重極） 同じ紐の両側から流れ込み、もう 1 本の紐の両側へ出る
    d（singular、特異）    4 本とも流れ込む（吸い込み）か、4 本とも出る（湧き出し）
    odd                    1 本だけ流れ込む・1 本だけ出る（8 頂点模型の外。資料 p.18 の 32・64 頂点模型の側）
  添字 i（資料の w_i）は交差点の種類 C・D・E（どの 2 本の紐の交わりか）にあたる。
"""
import math
from typing import Dict, List, Optional, Tuple

from . import _engine as E

INTERACTIONS = ("antiferro_tri_hex", "ferro_tri_tri", "ferro_hex_hex", "quadrupole")
INTERACTION_NAMES = {
    "antiferro_tri_hex": "反強磁性型（三角形と六角形・辺を共有）",
    "ferro_tri_tri": "強磁性型（三角形と三角形・交差点を共有）",
    "ferro_hex_hex": "強磁性型（六角形と六角形・交差点を共有）",
    "quadrupole": "4 重極型（交差点の周りの 4 つ）",
}
INTERACTION_SHORT = {"antiferro_tri_hex": "反強磁性（三角・六角）", "ferro_tri_tri": "強磁性（三角・三角）",
                     "ferro_hex_hex": "強磁性（六角・六角）", "quadrupole": "4 重極"}
VERTEX_TYPES = ("a", "b", "c", "d", "odd", "zero")
VERTEX_NAMES = {"a": "a 双極（dipole）", "b": "b 鞍点（saddle）", "c": "c 4 重極（quadrupole）",
                "d": "d 特異（湧き出し・吸い込み）", "odd": "8 頂点の外（1 本だけ入る・出る）", "zero": "流れなし"}


def _opp(r: int) -> int:
    return (r + 2) % 6 + 1


def faces(m, dec) -> List[dict]:
    """三角形・六角形ごとの頂点と正味の回転量。頂点がすべて格子にあるものだけ。"""
    out = []
    nodes = set(m.nodes)
    for (i, j) in sorted({(n[1], n[2]) for n in m.nodes}):
        for kind, vs in (("d", [("C", i, j), ("E", i, j), ("D", i, j)]),
                         ("u", [("C", i, j), ("E", i, j - 1), ("D", i + 1, j - 1)]),
                         ("h", [("C", i, j), ("E", i, j - 1), ("D", i, j),
                                ("C", i - 1, j), ("E", i - 1, j), ("D", i, j - 1)])):
            if not all(v in nodes for v in vs):
                continue
            if kind == "h":
                net = dec["sigma"][("+", i, j)] - dec["sigma"][("-", i, j)]
            else:
                net = dec["s"][(kind, "+", i, j)] - dec["s"][(kind, "-", i, j)]
            out.append({"key": (kind, i, j), "tri": kind != "h", "vs": vs, "net": float(net)})
    return out


def interaction_sets(m, dec) -> Dict[str, List[Tuple]]:
    """型ごとの、相互作用する図形の組。周りの 4 つの図形がそろう交差点だけを使う。

    m.halo のときは内側の交差点だけ（端の影響を避ける）。
    """
    fs = faces(m, dec)
    at = {}
    for f in fs:
        for v in f["vs"]:
            at.setdefault(v, []).append(f)
    use = m.inner_nodes if m.halo else m.nodes
    sets = {k: set() for k in INTERACTIONS}
    for n in use:
        fl = at.get(n, [])
        tri = [f["key"] for f in fl if f["tri"]]
        hexa = [f["key"] for f in fl if not f["tri"]]
        if len(tri) != 2 or len(hexa) != 2:
            continue
        sets["ferro_tri_tri"].add(tuple(sorted(tri)))
        sets["ferro_hex_hex"].add(tuple(sorted(hexa)))
        for t in tri:
            for h in hexa:
                sets["antiferro_tri_hex"].add((t, h))
        sets["quadrupole"].add((n,) + tuple(sorted(tri)) + tuple(sorted(hexa)))
    return {k: sorted(v) for k, v in sets.items()}


def hex_rotation_comparison(m, dec_now, dec_std):
    """内側の完全な六角形を対象に、標準状態の平均と現況との差を求める。"""
    coords = [f["key"][1:] for f in faces(m, dec_std)
              if not f["tri"] and all(v in m.inner_nodes for v in f["vs"])]
    if not coords:
        return None, {}

    def components(dec, i, j):
        cw = dec["sigma"][("+", i, j)]
        ccw = dec["sigma"][("-", i, j)]
        return {"cw": cw, "ccw": ccw, "net": cw - ccw}

    values = [components(dec_std, i, j) for i, j in coords]
    mean = {k: math.fsum(v[k] for v in values) / len(values) for k in values[0]}
    rows = {}
    for i, j in coords:
        now = components(dec_now, i, j)
        rows[i, j] = {"now": now, "difference": {k: v - mean[k] for k, v in now.items()}}
    return mean, rows


def _q(kind: str, S: Dict, g: Tuple, u: float) -> float:
    if kind == "quadrupole":
        _, a, b, c, d = g
        return S[a] * S[b] * S[c] * S[d] / u ** 4
    a, b = g
    return (-1.0 if kind.startswith("antiferro") else 1.0) * S[a] * S[b] / u ** 2


def spin_interactions(m, dec_now, dec_std) -> Dict[str, object]:
    """4 種のスピン相互作用について、今と標準状態の量、その差（符号つき・絶対値の総量）。"""
    S_now = {f["key"]: f["net"] for f in faces(m, dec_now)}
    S_std = {f["key"]: f["net"] for f in faces(m, dec_std)}
    sets = interaction_sets(m, dec_std)
    used = {k for g in sets["antiferro_tri_hex"] for k in g}
    u = sum(abs(S_std[k]) for k in used) / max(1, len(used))
    if u <= 0:
        u = 1.0
    out = {"scale": u, "types": {}, "rows": [], "trace": {
        "status": "provisional",
        "geometry": "uncontracted_kagome_faces",
        "source_geometry": "資料p.15：上向き三角を縮約したハニカム格子",
        "contraction_implemented": False,
        "formula_origin": "implementation_assumption",
        "spin": "S = clockwise - counterclockwise",
        "scale": u,
        "scale_definition": "対象面における標準状態のabs(S)の平均。0なら1を使用",
        "formulas": {
            "antiferro_tri_hex": "-S_a*S_b/scale**2",
            "ferro_tri_tri": "S_a*S_b/scale**2",
            "ferro_hex_hex": "S_a*S_b/scale**2",
            "quadrupole": "S_a*S_b*S_c*S_d/scale**4",
        },
        "rows": [],
    }}
    for kind in INTERACTIONS:
        tot_now = tot_std = d_sum = d_abs = 0.0
        for g in sets[kind]:
            qn, qs = _q(kind, S_now, g, u), _q(kind, S_std, g, u)
            tot_now += qn
            tot_std += qs
            d_sum += qn - qs
            d_abs += abs(qn - qs)
            out["rows"].append((kind, g, qn, qs))
            keys = g[1:] if kind == "quadrupole" else g
            out["trace"]["rows"].append({
                "type": kind,
                "node": list(g[0]) if kind == "quadrupole" else None,
                "faces": [{"key": list(k), "spin_now": S_now[k],
                           "spin_standard": S_std[k]} for k in keys],
                "q_now": qn, "q_standard": qs, "difference": qn - qs,
            })
        out["types"][kind] = {"name": INTERACTION_NAMES[kind], "count": len(sets[kind]),
                              "now": tot_now, "standard": tot_std,
                              "diff": d_sum, "diff_abs": d_abs}
    return out


def arm_net(m, V: Dict, node) -> Optional[Dict[int, float]]:
    """交差点の腕ごとの正味の流れ（出る量 − 入る量）。4 本の腕の行き・帰りがすべて格子にあるときだけ。"""
    out = {}
    for r in E.CONNECTED_ROADS[node[0]]:
        e_out = (node[0], node[1], node[2], r)
        e_in = m.upstream(node, _opp(r))
        if e_out not in V or e_in is None or e_in not in V:
            return None
        out[r] = V[e_out] - V[e_in]
    return out


def vertex_type(net: Dict[int, float], tol: float = 1e-9) -> str:
    """腕の正味の流れの向きから、8 頂点模型の型（a・b・c・d）を決める。"""
    scale = max((abs(x) for x in net.values()), default=0.0)
    if scale <= tol:
        return "zero"
    ins = [r for r, x in net.items() if x < -tol * scale]
    outs = [r for r, x in net.items() if x > tol * scale]
    if len(ins) + len(outs) < 4:
        return "odd" if len(ins) != len(outs) else "zero"
    if len(ins) in (0, 4):
        return "d"
    if len(ins) != 2:
        return "odd"
    a, b = ins
    ang = abs((a - b) * 60) % 360
    ang = min(ang, 360 - ang)
    return {60: "a", 120: "b", 180: "c"}[ang]


def vertices(m, V_now: Dict, V_std: Dict) -> Dict[str, object]:
    """交差点ごとの 8 頂点模型の型。今と標準状態。"""
    use = m.inner_nodes if m.halo else m.nodes
    rows, cnt_now, cnt_std = [], {}, {}
    for n in sorted(use):
        a, b = arm_net(m, V_now, n), arm_net(m, V_std, n)
        if a is None or b is None:
            continue
        tn, ts = vertex_type(a), vertex_type(b)
        rows.append((n, tn, ts))
        for t, c in ((tn, cnt_now), (ts, cnt_std)):
            c.setdefault(n[0], {k: 0 for k in VERTEX_TYPES})
            c[n[0]][t] += 1
    changed = sum(1 for _, tn, ts in rows if tn != ts)
    return {"rows": rows, "now": cnt_now, "standard": cnt_std, "changed": changed, "nodes": len(rows)}
