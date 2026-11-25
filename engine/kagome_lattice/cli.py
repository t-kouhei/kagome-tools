# -*- coding: utf-8 -*-
"""コマンド：テンプレートの書き出し、例の作成、解析、シナリオの比較。

  python -m kagome_lattice template 3 work/          空の入力テンプレート（N=3）
  python -m kagome_lattice example  3 work/          動作確認用に値を埋めた例（「例」であって既定値ではない）
  python -m kagome_lattice analyze  3 work/ out/     解析（work/ の edges.csv・branching.csv を読む）
  python -m kagome_lattice scenario 3 work/ change/ out/
                                                     change/ に書いた値だけ変えて解析し、もとの条件との差を出す
  analyze・scenario の共通オプション
      --entrances      entrances.csv があれば伝播モード（流量 V は入口からの流入で計算する）
                       付けなければ観測モード（流量 V を入れる）。観測モードでは、流量と分岐の割合から
                       入口の流入量を逆に求め（entrances_estimated.csv）、説明できない分を素辺ごとに出す
      --halo           周りに 1 リングの余白を付けた格子（template・example と同じ指定にする）。
                       内側 N×N の素辺は端の影響を受けずに直進成分まで計算できる
      --norm k|m|mvl   規格化の式。新規の基本設定 m：V/m（原資料のj）。kはV/(v·m)による密度。
                       交通量＝密度×速度の関係で、臨界点 μ は臨界密度として入れる（資料 p.13
                       「車線数・素辺の距離・輸送速度…を規格化」。距離 L は τ の式に入る）。
                       m：V/m（台/時/車線）、mvl：V·v/(L·m)（設計書 P1 の候補）
      --eps total|straight  臨界点と比べる量（既定：規格化した交通量。資料 p.13「各道路素辺の…臨界点」）
      --theta 0.5      臨界点の取り方（f = θ。0.5 ならフェルミ準位）
      --limit critical_total|through_maxflow|line_min_sum  道路インフラ限界（資料 p.16）。既定 critical_total は
                       全素辺を渋滞臨界状態とした交通量の、向きごとの総和。他の 2 つは参考（最大流、紐ごとの最小の和）
      --tau count|engine  新規の基本設定 engine：j_in β L_in/(m_out L_out)。countは比較用。
      --plot QUANTITY  格子の図（lattice.png）を、指定した量で色分けして書き出す
                       J / J_straight / ratio（臨界量に対する比）/ V
      --global direction|maxflow  グローバルの操作（伝播モードのみ）。direction（既定の考え方。資料 p.16）は
                       向きごとの総交通量が道路インフラ限界を超えないように、全部の入口を同じ割合で上げていき、
                       限界に達した向きに流れ込む入口から止める。maxflow は参考（全体の最大流）
      --exits keep|free  最大流で、出口ごとの量を今の配分のまま保つか（keep）、どの出口でもよいか（free）
      --local lp|spot|detour ローカルの操作（容量を超えた素辺の分を格子の中で回す。伝播モードのみ）
                       lp は最小変更の線形計画（実行可能な解の有無も報告する）。spot・detour は比べるための規則
      --local-objective tau|flow|branch  lp で最小にする変更（τ＝スピンの素、流れの量、分岐の割合）。既定 tau
  結果を見る画面 viewer.html を書き出す（ブラウザで開く。ネット接続は要らない）。
"""
import argparse
import copy
import os
import random
import sys
import math
import csv

from .check import check
from .steady import SteadyFlowError, require_unique_steady
from .trace import calculation_trace
from .provenance import capture, write_bundle
from .profiles import PROFILE_NAMES, presentation_text, profile_info
from .semantics import (SOURCE_SETTINGS, LEGACY_SETTINGS, ROUTING_CONVENTION,
                        source_equivalent_occupancy, migrate_state_to_source, SOURCE_INDEX_INTERPRETATIONS)
from .diagnostics import DIRECTION_NOTE, direction_comparison, hex_scenario_comparison
from .basis import HEX_MEAN_NOTE, PROVISIONAL, SPIN_NOTE, STANDARD_NOTE, VERTEX_NOTE, calculation_basis
from .flow import global_direction, global_maxflow
from .ops import LP_OBJECTIVES, edge_capacity, local_lp, local_relief
from .viewer import write_viewer
from .spin import (INTERACTION_NAMES, INTERACTION_SHORT, VERTEX_NAMES,
                   hex_rotation_comparison, spin_interactions, vertices)
from .io import (BRANCH_COLS, ENTRANCE_COLS, apply_changes, edge_id, read_entrances, read_lattice_info,
                 read_model, write_csv, write_json, write_templates, EDGE_COLS)

def cmd_template(a):
    m = write_templates(a.n, a.outdir, halo=a.halo, profile=a.profile, calculation=SOURCE_SETTINGS)
    extra = f"（余白込み {m.size}×{m.size}。内側の素辺 {len(m.inner_edges)} 本）" if m.halo else ""
    print(f"N={a.n}: 素辺 {len(m.edges)} 本、交差点 {len(m.nodes)} 個、入口 {len(m.entrances)} か所{extra} → {a.outdir}")


def cmd_source_input(a):
    """旧入力の総流量を保ち、μ・Tの単位を原資料の流量jへそろえて別フォルダへ保存。"""
    if os.path.exists(a.outdir):
        print("移行先には新しいフォルダを指定してください。")
        return 2
    try:
        info = read_lattice_info(a.indir)
        if info and (info["n"] != a.n or info["halo"] != a.halo):
            raise ValueError("元の格子サイズ・余白と同じ指定が必要です。")
        settings = dict(info["calculation"] if info else LEGACY_SETTINGS)
        if a.from_norm:
            settings["norm"] = a.from_norm
        if a.from_tau:
            settings["tau"] = a.from_tau
        print(f"移行元の設定：norm={settings['norm']}、tau={settings['tau']}。μ・Tはこの単位として換算します。")
        tables = {}
        columns = {"edges": EDGE_COLS, "branching": BRANCH_COLS, "entrances": ENTRANCE_COLS}
        for name, fields in columns.items():
            path = os.path.join(a.indir, name + ".csv")
            if name == "entrances" and not os.path.exists(path):
                tables[name] = []
                continue
            with open(path, encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames != fields:
                    raise ValueError(f"{name}.csvの列と順序がテンプレートと一致しません。")
                tables[name] = list(reader)
        state = migrate_state_to_source({**settings, "tables": tables})
    except (ValueError, KeyError, OSError, TypeError) as ex:
        print(f"移行できませんでした：{ex}")
        return 2
    write_templates(a.n, a.outdir, halo=a.halo, profile=a.profile, calculation=SOURCE_SETTINGS)
    for name, fields in columns.items():
        write_csv(os.path.join(a.outdir, name + ".csv"), fields,
                  [[row[key] for key in fields] for row in state["tables"][name]])
    write_json(os.path.join(a.outdir, "migration.json"), state["migration"])
    print(f"原資料の設定へ移行しました：Vと臨界総流量を保持し、μ・Tを換算 → {a.outdir}")
    return 0


def cmd_example(a):
    """動作確認用の値を埋める（乱数。分野の既定値ではない）。"""
    m = write_templates(a.n, a.outdir, halo=a.halo, profile=a.profile, calculation=SOURCE_SETTINGS)
    rnd = random.Random(a.seed)
    rows = []
    for (t, i, j, r) in m.edges:
        if a.profile == "patent":
            # 任意の共通単位を使う合成例。速度や流量を交通の単位に固定しない。
            rows.append([t, i, j, r, rnd.choice([1, 2, 3]), round(rnd.uniform(1, 3), 3),
                         round(rnd.uniform(1, 2), 3), "", 1.0, round(rnd.uniform(10, 20), 3)])
            rows[-1][-2] *= rows[-1][6]
            rows[-1][-1] *= rows[-1][6]
            continue
        # 元の合成例の臨界密度を生成後、μ・Tを速度で掛けて原資料jの単位へそろえる。
        rows.append([t, i, j, r, rnd.choice([1, 2, 3]), round(rnd.uniform(0.2, 0.6), 3),
                     round(rnd.uniform(30, 50), 1), "", 2.5, round(rnd.uniform(20, 30), 1)])
        rows[-1][-2] *= rows[-1][6]
        rows[-1][-1] *= rows[-1][6]
    write_csv(os.path.join(a.outdir, "edges.csv"), ["node_type", "i", "j", "road", "m", "L", "v", "V", "T", "mu"], rows)
    rows = []
    for (t, i, j) in m.nodes:
        from . import _engine as E
        for r in E.CONNECTED_ROADS[t]:
            R, L = round(rnd.uniform(0.05, 0.3), 3), round(rnd.uniform(0.05, 0.3), 3)
            rows.append([t, i, j, r, round(1 - R - L, 3), R, L])
    write_csv(os.path.join(a.outdir, "branching.csv"), BRANCH_COLS, rows)
    flow_range = (3, 12) if a.profile == "patent" else (300, 1200)
    rows = [[t, i, j, r, round(rnd.uniform(*flow_range), 1)] for (t, i, j, r) in m.entrances]
    write_csv(os.path.join(a.outdir, "entrances.csv"), ENTRANCE_COLS, rows)
    print(f"例を書き出した（伝播モード用。流量 V は空欄）→ {a.outdir}")


# ═══════════════════════════════════════════════════════════
#  読み込みと解析の本体（analyze と scenario で共通）
# ═══════════════════════════════════════════════════════════

def _load(a, indir):
    """格子・値・入口の流入量を読む。形の誤りなら None。"""
    try:
        info = read_lattice_info(indir)
    except (ValueError, KeyError) as ex:
        print(ex)
        return None
    if info is not None and (info["n"] != a.n or info["halo"] != a.halo):
        print(f"格子の形がテンプレートと違う：テンプレートは N={info['n']}"
              f"{'・余白あり（--halo）' if info['halo'] else '・余白なし'}。同じ指定で実行する。")
        return None
    try:
        m = read_model(a.n, os.path.join(indir, "edges.csv"), os.path.join(indir, "branching.csv"),
                       halo=a.halo)
        inflow = read_entrances(os.path.join(indir, "entrances.csv")) if a.entrances else None
    except (ValueError, FileNotFoundError) as ex:
        print(ex)
        return None
    return m, inflow


def _run(m, inflow, a, outdir, ref=None, quiet=False, changes=None):
    """1 つの条件を解析して outdir に書き出す。入力に誤りがあれば None。

    ref: 比べる相手の流量 {"V": {素辺: 値}, "label": 名前}（シナリオでもとの条件と比べるとき）
    """
    mode = "propagate" if inflow is not None else "observe"
    issues = check(m, mode=mode, norm=a.norm, inflow=inflow)
    if not math.isfinite(a.theta) or not 0 < a.theta < 1:
        issues.append(("error", "theta", "臨界点θは0より大きく1より小さい有限数が必要"))
    for s, where, msg in issues:
        print(f"[{s}] {where}: {msg}")
    if any(s == "error" for s, _, _ in issues):
        print("入力に誤りがあるので計算しない。")
        return None
    if inflow is not None:
        require_unique_steady(m, inflow)
    os.makedirs(outdir, exist_ok=True)
    provenance_record = capture(m, inflow, a)
    report = {"n": a.n, "halo": m.halo, "profile": a.profile,
              "profile_info": profile_info(a.profile, a.norm), "routing_convention": ROUTING_CONVENTION,
              "source_index_interpretations": SOURCE_INDEX_INTERPRETATIONS,
              "calculation": {"norm": a.norm, "tau": a.tau},
              "geometry": {"inner_nodes": len(m.inner_nodes), "inner_directed_edges": len(m.inner_edges),
                           "all_nodes": len(m.nodes), "all_directed_edges": len(m.edges)},
              "mode": mode, "norm": a.norm, "eps": a.eps, "theta": a.theta,
              "limit_rule": a.limit, "tau_mode": a.tau, "exits": a.exits, "issues": [[s, str(w), msg] for s, w, msg in issues],
              "global_rule": a.global_rule, "local_rule": a.local_rule}

    have_fd = all(m.values[e].T is not None and m.values[e].mu is not None for e in m.edges)
    report["guarantee"] = calculation_basis(a, mode, have_fd)
    V, V_raw, final = None, None, m
    ops, est = {}, None
    if mode == "propagate":
        if (a.global_rule != "none" or a.local_rule != "none") and not have_fd:
            print("操作には温度 T とフェルミ準位 mu（容量を決める値）が要る。全素辺に入れてから実行する。")
            return None
        V_raw = m.propagate(inflow)["V"]
        used = inflow
        if a.global_rule == "direction":
            lim0 = m.infrastructure_limit(theta=a.theta, mode=a.norm, rule=a.limit)
            g = global_direction(m, inflow, {d: v["C"] for d, v in lim0.items()})
            used = g["admitted"]
            ops["global"] = {"rule": "direction", "limit_rule": a.limit, "requested": g["requested"],
                             "admitted_total": g["total"], "rejected_total": g["rejected_total"],
                             "uniform_ratio": g["uniform_ratio"], "by_direction": g["by_direction"],
                             "load": g["load"], "tight": g["tight"]}
            write_csv(os.path.join(outdir, "global.csv"),
                      ["direction", "limit", "load_before", "load_after", "entrance_demand", "entrance_admitted",
                       "entrance_rejected"],
                      [[d, round(g["load"][d]["limit"], 6), round(g["load"][d]["before"], 6),
                        round(g["load"][d]["after"], 6), *(round(g["by_direction"][d][k], 6)
                                                          for k in ("demand", "admitted", "rejected"))]
                       for d in range(1, 7)])
            write_csv(os.path.join(outdir, "entrances_admitted.csv"), ENTRANCE_COLS + ["requested", "ratio"],
                      [[*x, round(g["admitted"][x], 6), round(inflow[x], 6), round(g["ratio"][x], 6)]
                       for x in sorted(g["admitted"])])
        elif a.global_rule == "maxflow":
            capg = edge_capacity(m, a.theta, a.norm)
            g = global_maxflow(m, inflow, capg, exits=a.exits)
            used = g["admitted"]
            # 最大流の回し方の例：これで流すと、どの素辺も容量以内に収まる（あることの確かめ）
            ex = copy.deepcopy(m)
            ex.branching = g["routing"]
            Vr = ex.propagate(used)["V"]
            ops["global"] = {"rule": a.global_rule, "exits": a.exits, "requested": g["requested"],
                             "admitted_total": g["total"], "rejected_total": g["rejected_total"],
                             "uniform_ratio": g["uniform_ratio"], "no_local_ratio": g["no_local_ratio"],
                             "by_direction": g["by_direction"], "cut": [edge_id(e) for e in g["cut"]],
                             "cut_exits": ["%s(%d,%d)" % y[0] + f"→{y[1]}" for y in g["cut_exits"]],
                             "routing_over": sum(1 for e in m.edges if Vr[e] > capg[e] * (1 + 1e-6) + 1e-9)}
            write_csv(os.path.join(outdir, "global.csv"), ["direction", "demand", "admitted", "rejected"],
                      [[d, *(round(v[k], 6) for k in ("demand", "admitted", "rejected"))]
                       for d, v in sorted(g["by_direction"].items())])
            write_csv(os.path.join(outdir, "entrances_admitted.csv"), ENTRANCE_COLS + ["requested", "ratio"],
                      [[*x, round(g["admitted"][x], 6), round(inflow[x], 6), round(g["ratio"][x], 6)]
                       for x in sorted(g["admitted"])])
            write_csv(os.path.join(outdir, "branching_maxflow.csv"), BRANCH_COLS,
                      [[*k, *(round(v[t], 6) for t in ("S", "R", "L"))] for k, v in sorted(g["routing"].items())])
        if a.local_rule != "none":
            cap = edge_capacity(m, a.theta, a.norm)
            if a.local_rule == "lp":
                r = local_lp(m, used, cap, objective=a.local_objective, keep_exits=(a.exits == "keep"),
                             tau_mode=a.tau, norm=a.norm)
            else:
                r = local_relief(m, used, cap, rule=a.local_rule)
            final = r["model"]
            s0, s1 = _net_spins(m, used, a), _net_spins(final, used, a)
            ops["local"] = {"rule": a.local_rule, "objective": a.local_objective if a.local_rule == "lp" else None,
                            "resolved": r["resolved"], "iterations": r["iterations"],
                            "stop_reason": r["stop_reason"],
                            "remaining": {edge_id(e): v for e, v in r["remaining_excess"].items()},
                            "spin_change": sum(abs(s1[k] - s0[k]) for k in s0),
                            "spin_total": sum(abs(v) for v in s0.values())}
            if a.local_rule == "lp":
                ops["local"]["flow_change"] = r["flow_change"]
                ops["local"]["nodes_changed"] = r["nodes_changed"]
                ops["local"]["solver_status"] = r["solver_status"]
                ops["local"]["solver_message"] = r["solver_message"]
                ops["local"]["moves"] = [{"node": "%s(%d,%d)" % mv["node"], "in_road": mv["in_road"],
                                          "before": [mv["before"][t] for t in ("S", "R", "L")],
                                          "after": [mv["after"][t] for t in ("S", "R", "L")], "amount": mv["amount"]}
                                         for mv in r["moves"]]
                write_csv(os.path.join(outdir, "local_changes.csv"),
                          ["node", "in_road", "S_before", "R_before", "L_before", "S_after", "R_after", "L_after",
                           "flow_through"],
                          [[x["node"], x["in_road"], *(round(v, 6) for v in x["before"]),
                            *(round(v, 6) for v in x["after"]), round(x["amount"], 6)] for x in ops["local"]["moves"]])
            else:
                ops["local"]["moves"] = [{"edge": edge_id(mv["edge"]), "node": "%s(%d,%d)" % mv["node"],
                                          "in_road": mv["in_road"], "kind": mv["kind"], "amount": mv["amount"]}
                                         for mv in r["moves"]]
                write_csv(os.path.join(outdir, "local_moves.csv"),
                          ["edge", "node", "in_road", "kind", "amount"],
                          [[x["edge"], x["node"], x["in_road"], x["kind"], round(x["amount"], 6)]
                           for x in ops["local"]["moves"]])
        p = final.propagate(used)
        V = p["V"]
        report["propagation"] = {k: p[k] for k in ("inflow_total", "outflow_total", "residual", "balance_error")}
        report["propagation"]["inflow_requested"] = float(sum(inflow.values()))
        report["operations"] = ops
    else:
        # 観測モード：流量と分岐の割合から入口の流入量を逆に求める（伝播モードの入力にそのまま使える）
        est = m.estimate_inflow()
        write_csv(os.path.join(outdir, "entrances_estimated.csv"), ENTRANCE_COLS,
                  [[*x, "" if b is None else round(b, 6)] for x, b in est["inflow"].items()])
        report["estimate"] = {"inflow_total": float(sum(b for b in est["inflow"].values() if b is not None)),
                              "unexplained_share": est["unexplained_share"],
                              "identifiable": est["identifiable"]}
    Vfin = V if V is not None else {e: m.values[e].V for e in m.edges}
    J = final.normalize(V=V, mode=a.norm)
    dec = final.decompose(J, tau_mode=a.tau, norm=a.norm)
    eps = {e: (dec["straight"][e]["J_straight"] if a.eps == "straight" else J[e]) for e in m.edges}
    crit = final.critical(eps, theta=a.theta) if have_fd else None
    cap = edge_capacity(m, a.theta, a.norm) if have_fd else None
    # 標準状態（資料 p.16）：全ての素辺を渋滞臨界状態とした状態。入力の分岐の割合のまま分解する
    std = m.standard_state(theta=a.theta, mode=a.norm, tau_mode=a.tau) if have_fd else None
    hex_mean, hex_rows = None, {}
    if std is not None:
        T_now = m.direction_totals(Vfin)
        T_std = m.direction_totals(std["V"])
        T_diff = {d: T_now[d] - T_std[d] for d in T_std}
        report["standard"] = {
            "definition": "全ての素辺を渋滞臨界状態（f = θ）とした状態（資料 p.16）",
            "status": "reference", "note": STANDARD_NOTE,
            "direction_total_now": T_now, "direction_total_standard": T_std,
            "direction_total_minus_standard": T_diff,
            "edge_deviation_abs_sum": float(sum(abs(Vfin[e] - std["V"][e]) for e in m.edges)),
            "spin_deviation_abs_sum": float(sum(abs(dec["s"][k] - std["dec"]["s"][k]) for k in dec["s"])
                                            + sum(abs(dec["sigma"][k] - std["dec"]["sigma"][k]) for k in dec["sigma"])),
        }
        hex_mean, hex_rows = hex_rotation_comparison(m, dec, std["dec"])
        report["standard"]["hex_rotation"] = {
            "count": len(hex_rows), "standard_mean": hex_mean, "note": HEX_MEAN_NOTE}
        report["direction_comparison"] = {
            "note": DIRECTION_NOTE, "scopes": direction_comparison(m, Vfin, std["V"])}
        if ref is not None and "hex_rows" in ref:
            report["hex_scenario_comparison"] = hex_scenario_comparison(
                ref["hex_rows"], hex_rows, ref["hex_mean"], hex_mean)
        # 4 種のスピン相互作用（資料 p.13・p.16）と 8 頂点模型（資料 p.17）。先生の式が出るまでの暫定の形
        si = spin_interactions(m, dec, std["dec"])
        report["standard"]["spin_interactions"] = {
            "status": PROVISIONAL, "note": SPIN_NOTE,
            "trace_file": "spin_interaction_trace.json",
            "scale": si["scale"], "types": si["types"]}
        write_json(os.path.join(outdir, "spin_interaction_trace.json"), si["trace"])
        write_csv(os.path.join(outdir, "interactions.csv"),
                  ["type", "name", "shapes", "q_now", "q_standard", "q_minus_standard", "status"],
                  [[k, INTERACTION_NAMES[k], " ".join("".join(map(str, x)) if isinstance(x, tuple) else str(x) for x in g),
                    round(qn, 6), round(qs, 6), round(qn - qs, 6), PROVISIONAL] for k, g, qn, qs in si["rows"]])
        vx = vertices(m, Vfin, std["V"])
        report["vertex_model"] = {"status": PROVISIONAL, "note": VERTEX_NOTE,
                                  "names": VERTEX_NAMES, "now": vx["now"], "standard": vx["standard"],
                                  "changed": vx["changed"], "nodes": vx["nodes"]}
        write_csv(os.path.join(outdir, "vertices.csv"), ["node_type", "i", "j", "type_now", "type_standard", "status"],
                  [[*n, tn, ts, PROVISIONAL] for n, tn, ts in vx["rows"]])

    rows = []
    for e in m.edges:
        Ve = Vfin[e]
        st = dec["straight"][e]
        row = [edge_id(e), *e, int(m.is_inner(e)), round(Ve, 6), round(J[e], 6), round(st["J_straight"], 6),
               int(st["complete"])]
        if crit:
            c = crit[e]
            row += [round(c["f"], 6), round(c["eps_star"], 6), round(c["margin"], 6), round(c["ratio"], 6),
                    round(cap[e], 6), round(Ve / cap[e], 6) if cap[e] else ""]
        if std is not None:
            row += [round(std["V"][e], 6), round(Ve - std["V"][e], 6),
                    round(std["dec"]["straight"][e]["J_straight"], 6)]
        if V_raw is not None:
            row += [round(V_raw[e], 6)]
        if est is not None:
            row += [round(est["unexplained"][e], 6)]
        row += [getattr(final.values[e], k) for k in ("m", "L", "v", "T", "mu")]
        row += [source_equivalent_occupancy(Ve, final.values[e].L, final.values[e].v)]
        rows.append(row)
    head = ["edge", "node_type", "i", "j", "road", "inner", "V", "J", "J_straight", "complete"]
    if crit:
        head += ["f", "eps_star", "margin", "ratio", "capacity", "usage"]
    if std is not None:
        head += ["V_standard", "V_minus_standard", "J_straight_standard"]
    if V_raw is not None:
        head += ["V_before_operations"]
    if est is not None:
        head += ["unexplained"]
    head += ["m", "L", "v", "T", "mu", "n_equivalent"]
    write_csv(os.path.join(outdir, "edges_result.csv"), head, rows)

    write_csv(os.path.join(outdir, "tau.csv"), ["node_type", "i", "j", "triangle", "turn", "tau"],
              [[*k, round(v, 6)] for k, v in sorted(dec["tau"].items())])
    sd = std["dec"] if std is not None else None
    write_csv(os.path.join(outdir, "rotation.csv"),
              ["kind", "orientation", "sign", "i", "j", "value"] + (["standard", "minus_standard"] if sd else []),
              [["s", o, sg, i, j, round(v, 6)] + ([round(sd["s"][(o, sg, i, j)], 6),
                                                   round(v - sd["s"][(o, sg, i, j)], 6)] if sd else [])
               for (o, sg, i, j), v in sorted(dec["s"].items())] +
              [["sigma", "", sg, i, j, round(v, 6)] + ([round(sd["sigma"][(sg, i, j)], 6),
                                                       round(v - sd["sigma"][(sg, i, j)], 6)] if sd else [])
               for (sg, i, j), v in sorted(dec["sigma"].items())])
    write_csv(os.path.join(outdir, "hex_rotation.csv"),
              ["i", "j", "component", "now", "standard_mean", "minus_standard_mean"],
              [[i, j, k, round(v, 6), round(hex_mean[k], 6), round(row["difference"][k], 6)]
               for (i, j), row in hex_rows.items() for k, v in row["now"].items()])
    direction_columns = ["edges", "now", "standard", "difference", "ratio", "over_capacity_edges", "excess_total"]
    write_csv(os.path.join(outdir, "direction_comparison.csv"),
              ["scope", "direction"] + direction_columns,
              [[scope, d] + [row[k] for k in direction_columns]
               for scope, directions in report.get("direction_comparison", {}).get("scopes", {}).items()
               for d, row in directions.items()])

    if have_fd:
        lim = m.infrastructure_limit(theta=a.theta, mode=a.norm, rule=a.limit)
        write_csv(os.path.join(outdir, "limit.csv"),
                  ["direction", "C", "rule", "total_now", "total_now_over_C", "critical_total", "line_min_sum",
                   "lines", "bottlenecks", "total_now_minus_standard"],
                  [[d, round(v["C"], 6), a.limit, round(T_now[d], 6), round(T_now[d] / v["C"], 6) if v["C"] else "",
                    round(v["critical_total"], 6), round(v["line_min_sum"], 6), v["lines"],
                    " ".join(edge_id(e) for e in v["bottlenecks"]), round(T_diff[d], 6)]
                   for d, v in sorted(lim.items())])
        report["direction_total_now"] = T_now
        report["limit"] = {d: v["C"] for d, v in lim.items()}
        report["limit_detail"] = {d: {"line_min_sum": v["line_min_sum"], "critical_total": v["critical_total"],
                                      "total_now": T_now[d],
                                      "total_now_minus_standard": T_diff[d],
                                      "bottlenecks": [edge_id(e) for e in v["bottlenecks"]]}
                                  for d, v in lim.items()}
    if ref is not None:
        report["compared_with"] = ref["label"]
    if changes:
        report["changes"] = [[str(x) for x in c] for c in changes]
    trace = calculation_trace(final, Vfin, J, dec, a.norm, a.tau, crit, cap, std, m)
    write_json(os.path.join(outdir, "calculation_trace.json"), trace)
    report["calculation_trace"] = {"file": "calculation_trace.json", "note": trace["note"]}
    report["guarantee"] = {k: presentation_text(v, a.profile) for k, v in report["guarantee"].items()}
    if "standard" in report:
        report["standard"]["definition"] = presentation_text(report["standard"]["definition"], a.profile)
    if "vertex_model" in report:
        report["vertex_model"]["note"] = presentation_text(report["vertex_model"]["note"], a.profile)
    report['provenance'] = write_bundle(outdir, provenance_record)
    write_json(os.path.join(outdir, "report.json"), report)
    write_json(os.path.join(outdir, "parameters.json"), report["profile_info"])
    if ref is not None:
        cmp = {"V": ref["V"], "label": ref["label"]}
    elif V_raw is not None:
        cmp = {"V": V_raw, "label": "操作の前"}
    else:
        cmp = None
    write_viewer(os.path.join(outdir, "viewer.html"), final, Vfin, cmp, J, dec, crit, cap,
                 report.get("limit", {}), ops, issues, report,
                 unexplained=est["unexplained"] if est is not None else None, std=std, hex_rows=hex_rows,
                 trace=trace)
    if a.plot:
        from .plot import plot_lattice
        vals = {}
        for e in m.edges:
            if a.plot == "J":
                vals[e] = J[e]
            elif a.plot == "J_straight":
                vals[e] = dec["straight"][e]["J_straight"]
            elif a.plot == "V":
                vals[e] = Vfin[e]
            elif a.plot == "ratio" and crit:
                vals[e] = crit[e]["ratio"]
        if vals:
            plot_lattice(m, vals, os.path.join(outdir, "lattice.png"), label=a.plot,
                         incomplete={e for e in m.edges if not dec["straight"][e]["complete"]})
    if not quiet:
        n_inc = sum(1 for e in m.inner_edges if not dec["straight"][e]["complete"])
        where = (f"内側 {len(m.inner_edges)} 本・余白 {len(m.edges) - len(m.inner_edges)} 本"
                 if m.halo else f"{len(m.edges)} 本")
        print(f"解析した：素辺 {where}（内側で直進成分が計算しきれない素辺 {n_inc} 本）→ {outdir}")
        if mode == "propagate":
            pr = report["propagation"]
            print(f"  入口から入った量 {pr['inflow_total']:.1f} ／ 出口から出た量 {pr['outflow_total']:.1f}")
            g = ops.get("global")
            if g and g["rule"] == "direction":
                print(presentation_text(
                    f"  グローバル（向きごとの総交通量 ≤ 道路インフラ限界）：入りたい量 {g['requested']:.1f} のうち "
                    f"{g['admitted_total']:.1f} を入れた（限界に達した向き {g['tight'] or 'なし'}）", a.profile))
                g = None
            if g:
                print(f"  グローバル（最大流・出口{'の配分を保つ' if g['exits'] == 'keep' else 'は自由'}）："
                      f"入りたい量 {g['requested']:.1f} のうち {g['admitted_total']:.1f} を入れた"
                      f"（全部同じ割合なら {100 * g['uniform_ratio']:.1f}%、ローカルなしなら {100 * g['no_local_ratio']:.1f}%）")
            lo = ops.get("local")
            if lo:
                extra = (f"（変えた交差点 {lo['nodes_changed']} か所、" if "nodes_changed" in lo else "（") + \
                    f"回転量の変化 {100 * lo['spin_change'] / max(lo['spin_total'], 1e-12):.1f}%）"
                print(f"  ローカル：{'すべての素辺が容量以内' if lo['resolved'] else '容量を超えた素辺が ' + str(len(lo['remaining'])) + ' 本残った（' + lo['stop_reason'] + '）'}{extra}")
        st = report.get("standard", {}).get("spin_interactions")
        if st:
            parts = "・".join(f"{INTERACTION_SHORT[k]} {v['diff_abs']:.1f}" for k, v in st["types"].items())
            print(f"  暫定：標準状態からのずれ（スピン相互作用、型ごとの差の総量）：{parts} → interactions.csv")
            vm = report["vertex_model"]
            print(presentation_text(
                f"  暫定：8 頂点模型の型が標準状態と違う交差点 {vm['changed']} / {vm['nodes']} か所 → vertices.csv", a.profile))
        if mode != "propagate":
            es = report["estimate"]
            print(f"  入口の流入量を逆に求めた（合計 {es['inflow_total']:.1f}）。流量のうち説明できない分 "
                  f"{100 * es['unexplained_share']:.2f}% → entrances_estimated.csv")
            if not es["identifiable"]:
                print("  [注意] 入口どうしの分け方が一意に決まらない（分岐の割合が同じ入口がある）")
    return {"model": final, "V": Vfin, "J": J, "dec": dec, "crit": crit, "cap": cap,
            "report": report, "ops": ops, "hex_rows": hex_rows, "hex_mean": hex_mean}


def _net_spins(model, inflow, a):
    """三角形・六角形ごとの正味の回転量（時計回り − 反時計回り）。"""
    V = model.propagate(inflow)["V"]
    dec = model.decompose(model.normalize(V=V, mode=a.norm), tau_mode=a.tau, norm=a.norm)
    out = {}
    for (o, sg, i, j), v in dec["s"].items():
        out[("s", o, i, j)] = out.get(("s", o, i, j), 0.0) + (v if sg == "+" else -v)
    for (sg, i, j), v in dec["sigma"].items():
        out[("h", i, j)] = out.get(("h", i, j), 0.0) + (v if sg == "+" else -v)
    return out


def cmd_analyze(a):
    loaded = _load(a, a.indir)
    if loaded is None:
        return 2
    m, inflow = loaded
    return 0 if _run(m, inflow, a, a.outdir) is not None else 2


def cmd_scenario(a):
    """もとの条件と、change/ に書いた値だけ変えた条件を同じ設定で解析し、差を出す。"""
    loaded = _load(a, a.indir)
    if loaded is None:
        return 2
    base_m, base_in = loaded
    m2, in2 = copy.deepcopy(base_m), (dict(base_in) if base_in is not None else None)
    try:
        log = apply_changes(m2, in2 if in2 is not None else {}, a.changedir)
    except ValueError as ex:
        print(ex)
        return 2
    if not log:
        print("変更が 1 つも無い（change/ に edges.csv・branching.csv・entrances.csv のどれかを置く）。")
        return 2
    print(f"変更 {len(log)} か所")
    base = _run(base_m, base_in, a, os.path.join(a.outdir, "base"), quiet=True)
    if base is None:
        return 2
    scn = _run(m2, in2, a, os.path.join(a.outdir, "scenario"),
               ref={"V": base["V"], "label": "もとの条件", "hex_rows": base["hex_rows"],
                    "hex_mean": base["hex_mean"]}, quiet=True, changes=log)
    if scn is None:
        return 2
    rows = []
    for e in base_m.edges:
        vb, vs = base["V"][e], scn["V"][e]
        jb, js = base["dec"]["straight"][e]["J_straight"], scn["dec"]["straight"][e]["J_straight"]
        row = [edge_id(e), int(base_m.is_inner(e)), round(vb, 6), round(vs, 6), round(vs - vb, 6),
               round(jb, 6), round(js, 6), round(js - jb, 6)]
        if base["cap"] and scn["cap"]:
            row += [round(vb / base["cap"][e], 6), round(vs / scn["cap"][e], 6)]
        rows.append(row)
    head = ["edge", "inner", "V_base", "V_scenario", "dV", "J_straight_base", "J_straight_scenario",
            "dJ_straight"]
    if base["cap"] and scn["cap"]:
        head += ["usage_base", "usage_scenario"]
    write_csv(os.path.join(a.outdir, "diff.csv"), head, rows)
    write_csv(os.path.join(a.outdir, "changes.csv"), ["file", "where", "column", "before", "after"],
              [list(map(str, x)) for x in log])

    def over(res):
        if not res["cap"]:
            return None
        return sum(1 for e in base_m.inner_edges if res["V"][e] > res["cap"][e] * (1 + 1e-6) + 1e-9)

    def summary(res):
        r = res["report"]
        out = {"over_capacity_edges": over(res),
               "V_total_inner": float(sum(res["V"][e] for e in base_m.inner_edges))}
        if "propagation" in r:
            out.update(inflow_total=r["propagation"]["inflow_total"],
                       outflow_total=r["propagation"]["outflow_total"])
        g = res["ops"].get("global")
        if g:
            out["rejected_total"] = g["rejected_total"]
        lo = res["ops"].get("local")
        if lo:
            out["local_resolved"] = lo["resolved"]
        return out
    sb, ss = summary(base), summary(scn)
    hex_compare = hex_scenario_comparison(base["hex_rows"], scn["hex_rows"], base["hex_mean"], scn["hex_mean"])
    hex_columns = ["i", "j", "component", "before", "after", "change", "reference_mean",
                   "before_minus_reference", "after_minus_reference", "scenario_standard_mean"]
    write_csv(os.path.join(a.outdir, "hex_rotation_diff.csv"), hex_columns,
              [[row[k] for k in hex_columns] for row in hex_compare])
    dV = [abs(scn["V"][e] - base["V"][e]) for e in base_m.inner_edges]
    write_json(os.path.join(a.outdir, "compare.json"),
               {"profile": a.profile, "changes": len(log), "base": sb, "scenario": ss,
                "hex_rotation": {"reference": "base_standard_mean", "rows": hex_compare,
                                 "note": "変更前の標準平均を共通の基準とする。changeは回転量自体の変更後−変更前。"
                                         "scenario_standard_meanには変更後の条件による標準平均を別記する。"},
                "edges_changed": sum(1 for x in dV if x > 1e-9), "max_abs_dV": max(dV) if dV else 0.0})
    print(f"比べた（流量が変わった内側の素辺 {sum(1 for x in dV if x > 1e-9)} 本、"
          f"最大の変化 {max(dV) if dV else 0:.1f}）→ {a.outdir}")
    for k, label in (("over_capacity_edges", "容量を超えた内側の素辺"), ("rejected_total", "入れなかった量"),
                     ("inflow_total", "入口から入った量")):
        if sb.get(k) is not None or ss.get(k) is not None:
            f = (lambda v: "–" if v is None else (f"{v:.1f}" if isinstance(v, float) else str(v)))
            print(f"  {label}: もと {f(sb.get(k))} → 変更後 {f(ss.get(k))}")
    print(f"  画面: {os.path.join(a.outdir, 'scenario', 'viewer.html')}（「もとの条件からの変化」を選ぶ）")
    return 0


def _common(p):
    p.add_argument("--entrances", action="store_true")
    p.add_argument("--halo", action="store_true")
    p.add_argument("--norm", choices=["k", "m", "mvl"], default=None)
    p.add_argument("--eps", choices=["total", "straight"], default="total")
    p.add_argument("--theta", type=float, default=0.5)
    p.add_argument("--limit", choices=["critical_total", "through_maxflow", "line_min_sum"], default="critical_total")
    p.add_argument("--tau", choices=["count", "engine"], default=None)
    p.add_argument("--plot", choices=["J", "J_straight", "ratio", "V"], default=None)
    p.add_argument("--global", dest="global_rule", choices=["none", "direction", "maxflow"], default="none")
    p.add_argument("--exits", choices=["keep", "free"], default="keep")
    p.add_argument("--local", dest="local_rule", choices=["none", "lp", "spot", "detour"], default="none")
    p.add_argument("--local-objective", dest="local_objective", choices=list(LP_OBJECTIVES), default="tau")


def main(argv=None):
    # Windowsのリダイレクト先がCP932でも、数式記号の表示で計算を止めない。
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='backslashreplace')
    p = argparse.ArgumentParser(prog="kagome_lattice", description="カゴメ格子解析ツール")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("template"); t.add_argument("n", type=int); t.add_argument("outdir")
    t.add_argument("--halo", action="store_true"); t.set_defaults(f=cmd_template)
    x = sub.add_parser("example"); x.add_argument("n", type=int); x.add_argument("outdir")
    x.add_argument("--seed", type=int, default=0); x.add_argument("--halo", action="store_true")
    x.set_defaults(f=cmd_example)
    an = sub.add_parser("analyze"); an.add_argument("n", type=int); an.add_argument("indir")
    an.add_argument("outdir"); _common(an); an.set_defaults(f=cmd_analyze)
    sc = sub.add_parser("scenario"); sc.add_argument("n", type=int); sc.add_argument("indir")
    sc.add_argument("changedir"); sc.add_argument("outdir"); _common(sc); sc.set_defaults(f=cmd_scenario)
    convert = sub.add_parser("source-input", help="μ・Tも単位換算し、原資料の基本設定へ移行")
    convert.add_argument("n", type=int); convert.add_argument("indir"); convert.add_argument("outdir")
    convert.add_argument("--halo", action="store_true"); convert.set_defaults(f=cmd_source_input)
    convert.add_argument("--from-norm", choices=["k", "m", "mvl"])
    convert.add_argument("--from-tau", choices=["count", "engine"])
    for command in (t, x, an, sc, convert):
        command.add_argument("--profile", choices=list(PROFILE_NAMES), default=None,
                             help="patent=特許版の基本解析、traffic=交通版。省略時は入力の版を引き継ぐ")
    a = p.parse_args(argv)
    try:
        input_info = read_lattice_info(a.indir) if hasattr(a, "indir") else None
    except (ValueError, KeyError) as ex:
        print(ex)
        return 2
    if hasattr(a, "norm"):
        saved = input_info["calculation"] if input_info else LEGACY_SETTINGS
        a.norm = a.norm or saved["norm"]
        a.tau = a.tau or saved["tau"]
        if not input_info or input_info.get("legacy_settings"):
            print("旧入力の計算設定を維持：指定のない項目はnorm=k・tau=count。原資料の設定への移行ではμ・Tの単位も換算してください。")
    if a.profile is None:
        try:
            info = read_lattice_info(a.indir) if hasattr(a, "indir") else None
        except (ValueError, KeyError) as ex:
            print(ex)
            return 2
        a.profile = info["profile"] if info else "traffic"
    print(f"{PROFILE_NAMES[a.profile]}：共通パラメータ m・L・v・V・T・μを使用")
    try:
        return a.f(a) or 0
    except SteadyFlowError as ex:
        print(f"計算を停止しました。{ex}")
        return 2
    except (ValueError, KeyError, OSError) as ex:
        print(f"入力・ファイルを確認してください。{ex}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
