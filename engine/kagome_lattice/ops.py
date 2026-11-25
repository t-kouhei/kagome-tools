# -*- coding: utf-8 -*-
"""容量のもとでの操作（設計書 P5）。

グローバル：入口でどれだけ入れるか。flow.py の global_direction / global_maxflow。
ローカル  ：流した結果、容量 c_e を超えた素辺について、手前の交差点の分岐の割合を変えて
            超えた分を別の素辺へ回す。流し直して、超えた素辺が無くなるまで繰り返す（このファイル）。

ローカルの振り分けは最小変更の線形計画と、比較用の spot / detour から選べる。
どちらの操作も「こうしたら、こう流れる」を計算するだけで、使うべきかは判断しない。
"""
import copy
from typing import Dict, List

import numpy as np

from .model import KagomeModel, TURNS, EdgeKey

EPS = 1e-9


def edge_capacity(m: KagomeModel, theta: float = 0.5, mode: str = "m") -> Dict[EdgeKey, float]:
    """素辺の容量 c_e ＝ 臨界量 ε*（f = θ）を流量の単位に戻したもの。"""
    import math
    out = {}
    for e in m.edges:
        ev = m.values[e]
        es = ev.mu + ev.T * math.log(theta / (1.0 - theta))
        out[e] = es * m.denormalize_factor(e, mode)
    return out


# ═══════════════════════════════════════════════════════════
#  ローカル
# ═══════════════════════════════════════════════════════════

def _arrivals(m: KagomeModel, node, V, inflow):
    """交差点 node に向き r から入ってくる量（上流の素辺の流量、または入口の流入量）。"""
    out = {}
    from . import _engine as E
    for r in E.CONNECTED_ROADS[node[0]]:
        up = m.upstream(node, r)
        out[r] = V[up] if up is not None else inflow.get((*node, r), 0.0)
    return out


def _triangle_detour(m: KagomeModel, e: EdgeKey):
    """素辺 e（X→Y）の三角形の他の 2 辺 X→Z→Y。無ければ None。"""
    X = e[:3]
    Y = m.target(e)
    from . import _engine as E
    for ra in E.CONNECTED_ROADS[X[0]]:
        a = (*X, ra)
        if ra == e[3] or a not in m.index:
            continue
        Z = m.target(a)
        for rb in E.CONNECTED_ROADS[Z[0]]:
            b = (*Z, rb)
            if b in m.index and m.target(b) == Y:
                return a, b
    return None


def _turn_of(m, node, in_road, out_road):
    from .model import TURN_TABLE
    for t, r in TURN_TABLE[(node[0], in_road)].items():
        if r == out_road:
            return t
    return None


def local_relief(m: KagomeModel, inflow: Dict[EdgeKey, float], cap: Dict[EdgeKey, float],
                 rule: str = "spot", max_iter: int = 200, tol: float = 1e-6) -> Dict[str, object]:
    """容量を超えた素辺の手前で分岐の割合を変え、超えた分を回す。流し直して繰り返す。

    rule="spot"   : 同じ交差点の他の行き先へ回す（その場で振り分け）。空きのある素辺へ空きの比で回し、
                    空きのある素辺が無ければ、いまの分岐の割合の比で回す
    rule="detour" : 三角形の他の 2 辺を通って、もとの素辺の先の交差点へ回す（迂回して戻る）。
                    その先は、その交差点の分岐の割合に従って流れる。迂回できない分と、迂回で超えた量が
                    減らなくなった後は、その場で振り分ける
    各回の変更は、超えた量の合計が減るときだけ採る（増えたら取り消す）。
    もとの m は変えない（分岐の割合を変えた写しを返す）。
    """
    if rule not in ("spot", "detour"):
        raise ValueError(f"ローカルの規則が違う: {rule}")
    w = copy.deepcopy(m)
    moves: List[dict] = []
    V = w.propagate(inflow)["V"]

    def total_excess(V):
        return sum(max(V[e] - cap[e], 0.0) for e in w.edges)
    prev, stale, it = total_excess(V), 0, 0
    stop_reason = ""
    total0 = max(sum(V.values()), EPS)
    use = rule
    for it in range(1, max_iter + 1):
        over = sorted(((V[e] - cap[e], e) for e in w.edges if V[e] > cap[e] * (1 + tol) + EPS),
                      reverse=True)
        if not over:
            break
        snapshot = copy.deepcopy(w.branching)
        n_moves = len(moves)
        moved_any = False
        for _, e in over:                       # 超えている素辺すべてについて、手前の交差点で回す
            moved_any |= _relieve_edge(w, e, V, inflow, cap, use, moves, it)
        if not moved_any:
            stop_reason = "回す先が無い"
            break
        try:
            p = w.propagate(inflow)
            # 流れが出口へ抜けにくくなる（回り道を回り続ける）と、素辺の流量の合計が跳ね上がる
            ok = (p["residual"] < 1e-6 * max(1.0, sum(inflow.values()))
                  and min(p["V"].values()) > -1e-6
                  and sum(p["V"].values()) <= 3.0 * total0)
        except np.linalg.LinAlgError:
            ok = False
        now = total_excess(p["V"]) if ok else float("inf")
        if not ok or now > prev + tol:
            # この回の変更で超えた量が増えた（または閉じた回り道ができた）。取り消す
            w.branching = snapshot
            del moves[n_moves:]
            if use == "detour":                  # 迂回で減らないときは、その場で振り分けに切り替える
                use = "spot"
                continue
            stop_reason = "回しても超えた量が減らない"
            break
        V = p["V"]
        stale = stale + 1 if now > prev - tol else 0
        prev = now
        if stale >= 20:
            stop_reason = "20 回続けて超えた量がほとんど減らない"
            break
    remaining = {e: V[e] - cap[e] for e in w.edges if V[e] > cap[e] * (1 + tol) + EPS}
    # 記録は「どの素辺の分を、どの交差点の、どの向きから来た流れで、どう回したか」ごとにまとめる
    agg = {}
    for mv in moves:
        key = (mv["edge"], mv["node"], mv["in_road"], mv["kind"])
        agg[key] = agg.get(key, 0.0) + mv["amount"]
    summary = [{"edge": k[0], "node": k[1], "in_road": k[2], "kind": k[3], "amount": v}
               for k, v in sorted(agg.items(), key=lambda kv: -kv[1])]
    return {"model": w, "V": V, "moves": summary, "iterations": it,
            "remaining_excess": remaining, "resolved": not remaining,
            "stop_reason": "" if not remaining else (stop_reason or f"{max_iter} 回で打ち切り")}


def _relieve_edge(w, e, V, inflow, cap, rule, moves, it):
    """素辺 e の超えた分を、手前の交差点 X の分岐の割合を変えて回す。回したら True。"""
    X, r_out = e[:3], e[3]
    if V[e] <= cap[e] + EPS:
        return False
    arr = _arrivals(w, X, V, inflow)
    k = cap[e] / V[e]                          # この素辺へ向かう割合を一律 k 倍にする
    detour = _triangle_detour(w, e) if rule == "detour" else None
    moved_any = False
    for r_in, A in arr.items():
        t_e = _turn_of(w, X, r_in, r_out)
        if t_e is None or A <= EPS:
            continue
        b = dict(w.branching.get((*X, r_in), {}))
        if b.get(t_e, 0.0) <= EPS:
            continue
        freed = b[t_e] * (1 - k)
        target_turn = _turn_of(w, X, r_in, detour[0][3]) if detour is not None else None
        if target_turn is not None and target_turn != t_e:
            b[t_e] -= freed
            b[target_turn] = b.get(target_turn, 0.0) + freed
            # 迂回先の交差点 Z で、増えた分が Y へ向かうように割合を足す
            Z, ra, rb = detour[1][:3], detour[0][3], detour[1][3]
            tz = _turn_of(w, Z, ra, rb)
            AZ = _arrivals(w, Z, V, inflow)[ra]
            add = A * freed
            if tz is not None and AZ + add > EPS:
                bz = dict(w.branching.get((*Z, ra), {}))
                newA = AZ + add
                for t in TURNS:
                    bz[t] = bz.get(t, 0.0) * AZ / newA
                bz[tz] = bz.get(tz, 0.0) + add / newA
                w.branching[(*Z, ra)] = bz
            kind = "detour"
        else:
            # その場で振り分け：同じ交差点の他の行き先のうち、空き（容量 − 流量）のある素辺へ空きの比で回す。
            # 空きのある素辺が無ければ、いまの分岐の割合の比で回す（出口へ出る分も含む）
            others = [t for t in TURNS if t != t_e]
            room = {}
            for t in others:
                e2 = w.out_edge(X, r_in, t)
                if e2 is not None and cap[e2] - V[e2] > EPS:
                    room[t] = cap[e2] - V[e2]
            if room:
                tot = sum(room.values())
                share = {t: room[t] / tot for t in room}
            else:
                tot = sum(b.get(t, 0.0) for t in others)
                if tot <= EPS:
                    continue
                share = {t: b.get(t, 0.0) / tot for t in others}
            b[t_e] -= freed
            for t, sh in share.items():
                b[t] = b.get(t, 0.0) + freed * sh
            kind = "spot"
        w.branching[(*X, r_in)] = b
        moves.append({"edge": e, "node": X, "in_road": r_in, "kind": kind,
                      "amount": A * freed, "iteration": it})
        moved_any = True
    return moved_any


# ═══════════════════════════════════════════════════════════
#  ローカル：最小変更（線形計画）
# ═══════════════════════════════════════════════════════════

LP_OBJECTIVES = ("tau", "flow", "branch")


def local_lp(m: KagomeModel, inflow: Dict[EdgeKey, float], cap: Dict[EdgeKey, float],
             objective: str = "tau", keep_exits: bool = True, tau_mode: str = "engine",
             norm: str = "m") -> Dict[str, object]:
    """容量以内に収まる流し方のうち、今の状態からの変更が最小のものを線形計画で求め、分岐の割合に直す。

    条件：交差点ごとの保存則、どの素辺も容量以内、入口から入れる量は inflow のまま、
          （keep_exits なら）出口ごとの量は今の分岐の割合で流したときのまま。
    何の変更を最小にするか（objective）:
      "tau"    … 局所回転 τ（曲がる流れ × L_in / (m_out L_out)）の変更の和。スピンの配置をなるべく保つ。
                  先生の標準状態が決まれば、比べる相手を「今」から「標準状態」に置き換える
      "flow"   … 曲がり方ごとの流れの量の変更の和
      "branch" … 分岐の割合の変更（曲がり方ごとの量 − 今の割合 × その素辺の量）の和。変える交差点が少なくなりやすい
    最大流で受け入れた量には、同じ容量・出口条件なら実行可能な流し方がある。
    向きごとの総量による受け入れには、この保証はない。解なしと数値計算の失敗を区別して返す。
    """
    if objective not in LP_OBJECTIVES:
        raise ValueError(f"最小にする量の指定が違う: {objective}")
    from scipy.optimize import linprog
    from scipy.sparse import lil_matrix
    from .flow import flow_arcs, exit_amounts
    V0 = m.propagate(inflow)["V"]
    arcs = flow_arcs(m)
    n = len(arcs)
    f0 = np.zeros(n)
    wgt = np.ones(n)
    for k, (kind, src, t, dst) in enumerate(arcs):
        if kind in ("turn", "exit"):
            f0[k] = V0[src] * m.beta(m.target(src), src[3], t)
        else:
            f0[k] = inflow.get(src, 0.0) * m.beta(src[:3], src[3], t)
        if objective == "tau":
            if t == "S" or kind in ("exit", "dir"):
                wgt[k] = 1e-3                          # 直進と、格子の外へ出る曲がりは回転を作らない
            else:
                ev = m.values[dst]
                Lin = m.values[src].L if kind == "turn" else ev.L
                wgt[k] = (Lin / (m.denormalize_factor(dst, norm) * ev.L) if tau_mode == "count"
                          else Lin / (m.denormalize_factor(src, norm) * ev.m * ev.L))
    eidx = {e: i for i, e in enumerate(m.edges)}
    ents = list(m.entrances)
    xidx = {x: i for i, x in enumerate(ents)}
    ys = sorted({dst for (kind, _, _, dst) in arcs if kind in ("exit", "dir")})
    yidx = {y: i for i, y in enumerate(ys)}
    nE, nX, nY = len(m.edges), len(ents), (len(ys) if keep_exits else 0)
    rows = nE + nX + nY
    A = lil_matrix((rows + n, 3 * n))
    beq = np.zeros(rows + n)
    Aub = lil_matrix((nE, 3 * n))
    groups = {}
    for k, (kind, src, t, dst) in enumerate(arcs):
        if kind in ("turn", "inj"):
            A[eidx[dst], k] += 1.0
        if kind in ("turn", "exit"):
            A[eidx[src], k] -= 1.0
            Aub[eidx[src], k] += 1.0
        if kind in ("inj", "dir"):
            A[nE + xidx[src], k] += 1.0
        if keep_exits and kind in ("exit", "dir"):
            A[nE + nX + yidx[dst], k] += 1.0
        groups.setdefault((kind in ("inj", "dir"), src), []).append(k)
    for x, i in xidx.items():
        beq[nE + i] = inflow.get(x, 0.0)
    if keep_exits:
        o = exit_amounts(m, inflow)
        for y, i in yidx.items():
            beq[nE + nX + i] = o.get(y, 0.0)
    # 変更の大きさ：d ＝ u − v（u, v ≥ 0）
    for (is_ent, src), ks in groups.items():
        for k in ks:
            A[rows + k, k] = 1.0
            A[rows + k, n + k] = -1.0
            A[rows + k, 2 * n + k] = 1.0
            if objective == "branch":
                t = arcs[k][2]
                b0 = m.beta(src[:3], src[3], t) if is_ent else m.beta(m.target(src), src[3], t)
                if is_ent:
                    beq[rows + k] = b0 * inflow.get(src, 0.0)
                else:
                    for k2 in ks:
                        A[rows + k, k2] = A[rows + k, k2] - b0
            else:
                beq[rows + k] = f0[k]
    # グローバルの二分法・線形計画の誤差の分だけ、容量をごくわずかに緩める
    bub = np.array([cap[e] * (1 + 1e-7) for e in m.edges])
    c = np.concatenate([np.zeros(n), wgt, wgt])
    res = linprog(c, A_ub=Aub.tocsr(), b_ub=bub, A_eq=A.tocsr(), b_eq=beq,
                  bounds=[(0, None)] * (3 * n), method="highs")
    if res.status != 0:
        reason = ("指定した流入量・容量・出口条件を同時に満たす流し方が無い。"
                  "向きごとのグローバル制限だけでは、各素辺の容量以内に収まるとは限らない。"
                  if res.status == 2 else
                  "線形計画の計算が完了しなかった。流し方が無いとは判定していない。")
        return {"model": copy.deepcopy(m), "V": V0, "moves": [], "iterations": 1,
                "remaining_excess": {e: V0[e] - cap[e] for e in m.edges if V0[e] > cap[e] * (1 + 1e-6)},
                "resolved": False, "stop_reason": reason, "objective": objective,
                "flow_change": None, "nodes_changed": 0,
                "solver_status": int(res.status), "solver_message": str(res.message)}
    f = res.x[:n]
    w = copy.deepcopy(m)
    moves = []
    for (is_ent, src), ks in groups.items():
        tot = sum(f[k] for k in ks)
        if tot <= 1e-9:
            continue
        key = tuple(src) if is_ent else (*m.target(src), src[3])
        new = {arcs[k][2]: float(f[k] / tot) for k in ks}
        for t in TURNS:
            new.setdefault(t, 0.0)
        old = {t: m.beta(key[:3], key[3], t) for t in TURNS}
        w.branching[key] = new
        if max(abs(new[t] - old[t]) for t in TURNS) > 1e-6:
            moves.append({"node": key[:3], "in_road": key[3], "before": old, "after": new, "amount": float(tot)})
    p = w.propagate(inflow)
    V = p["V"]
    remaining = {e: V[e] - cap[e] for e in m.edges if V[e] > cap[e] * (1 + 1e-6) + EPS}
    moves.sort(key=lambda mv: -sum(abs(mv["after"][t] - mv["before"][t]) for t in TURNS) * mv["amount"])
    return {"model": w, "V": V, "moves": moves, "iterations": 1, "remaining_excess": remaining,
            "resolved": not remaining, "stop_reason": "" if not remaining else "数値の誤差で収まりきらない",
            "objective": objective, "flow_change": float(np.abs(f - f0).sum()),
            "solver_status": int(res.status), "solver_message": str(res.message),
            "nodes_changed": len({mv["node"] for mv in moves
                                  if max(abs(mv["after"][t] - mv["before"][t]) for t in TURNS) > 0.01})}
