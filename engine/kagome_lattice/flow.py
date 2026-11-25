# -*- coding: utf-8 -*-
"""最大流（グローバルの受け入れと、向きごとの上限）。

格子を「素辺を通る量に上限 c_e がある網」とみる。交差点ではどの曲がり方（直進・右・左）を使ってもよい
（U ターンなし）。この網で入口から出口へ流せる最大の量が最大流で、最大流・最小カット定理により、
入口と出口を切り離す素辺の組のうち容量の合計が最小のもの（最小カット）の容量に等しい。

  向きごとの上限 C_d … 向き d の入口から入り、向き d に進んで格子の外へ出る出口までの最大流
                         （通り抜けの最大流。曲がりを禁止すると「紐の上は最小・平行な紐は和」と一致する）
  受け入れ         … 入口 x に来ている量 b_x のうち入れる量 a_x。全部の入口を同じ割合 a_x / b_x で上げていき、
                       細い所に詰まった入口から順に止める。合計はちょうど最大流になり、割り当ては一通りに決まる
  出口の扱い       … 既定（exits="keep"）は、格子の外へ出る量の配分を今の分岐の割合で決まる配分のまま保ち、
                       変えるのは格子の中の流し方だけにする（出口ごとの量 o(a) は入れた量 a に比例して決まる）。
                       exits="free" はどの出口から出てもよい（一番緩い境目）

どの入口・どの素辺を何に当てはめるかは使う側が決める。ここでは数学的な網として扱うだけ。
"""
from collections import deque
from typing import Dict, List, Optional

import numpy as np

from .model import KagomeModel, TURNS, TURN_TABLE, EdgeKey

INF = float("inf")

try:
    import scipy.optimize  # noqa: F401
    _HAVE_SCIPY = True
except ImportError:                                   # scipy が無ければ二分法で求める（遅いが同じ答え）
    _HAVE_SCIPY = False
TOL = 1e-9


class Dinic:
    """実数の容量の最大流（Dinic 法）。"""

    def __init__(self, n: int):
        self.n = n
        self.adj: List[List[int]] = [[] for _ in range(n)]
        self.to: List[int] = []
        self.cap: List[float] = []

    def add(self, u: int, v: int, c: float) -> int:
        """u → v の辺（容量 c）。戻り値は辺の番号（流した量は flow(k) で読む）。"""
        k = len(self.to)
        self.to += [v, u]
        self.cap += [c, 0.0]
        self.adj[u].append(k)
        self.adj[v].append(k + 1)
        return k

    def flow(self, k: int) -> float:
        return self.cap[k ^ 1]

    def _bfs(self, s, t, eps):
        self.level = [-1] * self.n
        self.level[s] = 0
        q = deque([s])
        while q:
            u = q.popleft()
            for k in self.adj[u]:
                v = self.to[k]
                if self.cap[k] > eps and self.level[v] < 0:
                    self.level[v] = self.level[u] + 1
                    q.append(v)
        return self.level[t] >= 0

    def _dfs(self, s, t, eps):
        """レベルグラフの中で、s から t への道を 1 本ずつ見つけて流す（反復版）。"""
        total = 0.0
        it = self.it
        while True:
            path, u = [], s
            while u != t:
                adv = False
                while it[u] < len(self.adj[u]):
                    k = self.adj[u][it[u]]
                    v = self.to[k]
                    if self.cap[k] > eps and self.level[v] == self.level[u] + 1:
                        path.append(k)
                        u = v
                        adv = True
                        break
                    it[u] += 1
                if not adv:
                    if u == s:
                        return total
                    self.level[u] = -1           # 行き止まり。来た道を 1 つ戻る
                    k = path.pop()
                    u = self.to[k ^ 1]
                    it[u] += 1
            f = min(self.cap[k] for k in path)
            for k in path:
                self.cap[k] -= f
                self.cap[k ^ 1] += f
            total += f
            if f == INF:
                return INF

    def maxflow(self, s: int, t: int, eps: float = TOL) -> float:
        total = 0.0
        while self._bfs(s, t, eps):
            self.it = [0] * self.n
            f = self._dfs(s, t, eps)
            total += f
            if f == INF:
                return INF
        return total

    def source_side(self, s: int, eps: float = TOL) -> set:
        """最大流の後、残りの容量で s から届く点（最小カットの s 側）。"""
        seen = {s}
        q = deque([s])
        while q:
            u = q.popleft()
            for k in self.adj[u]:
                v = self.to[k]
                if self.cap[k] > eps and v not in seen:
                    seen.add(v)
                    q.append(v)
        return seen

    def reach_from(self, u0: int, eps: float = TOL) -> set:
        """残りの容量で u0 から届く点。"""
        seen = {u0}
        q = deque([u0])
        while q:
            u = q.popleft()
            for k in self.adj[u]:
                v = self.to[k]
                if self.cap[k] > eps and v not in seen:
                    seen.add(v)
                    q.append(v)
        return seen

    def can_reach(self, t: int, eps: float = TOL) -> set:
        """残りの容量で t へ届く点（まだ増やせる点）。"""
        seen = {t}
        q = deque([t])
        while q:
            v = q.popleft()
            for k in self.adj[v]:                 # k は v から出る辺。その逆向き k^1 が u → v
                u = self.to[k]
                if self.cap[k ^ 1] > eps and u not in seen:
                    seen.add(u)
                    q.append(u)
        return seen


class FlowNet:
    """格子の網。素辺 e は「入る点 → 出る点」の辺（容量 c_e）、曲がり方は容量なしの辺。"""

    def __init__(self, m: KagomeModel, cap: Dict[EdgeKey, float], sources: Dict[EdgeKey, float],
                 exit_road: Optional[int] = None, direct_exit: bool = True, allow_turns: bool = True,
                 exit_caps: Optional[Dict[tuple, float]] = None):
        """sources: 入口 → 流入の上限（INF なら上限なし）。
        exit_road: 指定すると、その向きに進んで格子の外へ出る出口だけを出口とする（通り抜け）。
        direct_exit: 入口からどの素辺も通らずにすぐ出口へ抜ける曲がり方を数えるか。
        allow_turns: False なら直進だけ（紐ごとに別々に流す）。
        exit_caps: 出口（交差点, 出ていく向き）→ そこから出てよい量。指定すると出口ごとに上限を付ける。
        """
        self.m = m
        ids = {}

        def nid(key):
            if key not in ids:
                ids[key] = len(ids)
            return ids[key]
        s, t = nid("s"), nid("t")
        arcs = []                                       # (u, v, 容量, 種類, 名前)

        def sink(node, road):                           # 出口へ向かう先（出口ごとの上限があれば出口の点）
            if exit_caps is None:
                return t
            return nid(("y", (node, road)))
        turns = TURNS if allow_turns else ("S",)
        for e in m.edges:
            arcs.append((nid(("i", e)), nid(("o", e)), cap[e], "edge", e))
            node = m.target(e)
            for tn in turns:
                e2 = m.out_edge(node, e[3], tn)
                if e2 is not None:
                    arcs.append((nid(("o", e)), nid(("i", e2)), INF, "turn", (e, e2)))
                elif exit_road is None or TURN_TABLE[(node[0], e[3])][tn] == exit_road:
                    arcs.append((nid(("o", e)), sink(node, TURN_TABLE[(node[0], e[3])][tn]), INF,
                                 "exit", (e, tn)))
        for x, b in sources.items():
            arcs.append((s, nid(("x", x)), b, "source", x))
            for tn in turns:
                e2 = m.out_edge(x[:3], x[3], tn)
                if e2 is not None:
                    arcs.append((nid(("x", x)), nid(("i", e2)), INF, "inject", (x, e2)))
                elif direct_exit and (exit_road is None or TURN_TABLE[(x[0], x[3])][tn] == exit_road):
                    arcs.append((nid(("x", x)), sink(x[:3], TURN_TABLE[(x[0], x[3])][tn]), INF,
                                 "direct", (x, tn)))
        if exit_caps is not None:
            for y, c in exit_caps.items():
                arcs.append((nid(("y", y)), t, c, "sink", y))
        self.ids, self.s, self.t = ids, s, t
        self.g = Dinic(len(ids))
        self.arcs = [(self.g.add(u, v, c), kind, name) for (u, v, c, kind, name) in arcs]
        self.ends = {k: (u, v) for k, (u, v, *_r) in zip([a[0] for a in self.arcs], arcs)}
        self.value = self.g.maxflow(s, t)

    def cut_edges(self) -> List[EdgeKey]:
        """最小カットに入る素辺（s 側から t 側へまたぐ素辺）。"""
        S = self.g.source_side(self.s)
        return [e for e in self.m.edges if self.ids[("i", e)] in S and self.ids[("o", e)] not in S]

    def cut_exits(self) -> List[tuple]:
        """最小カットに入る出口（出口ごとの上限が決め手になっている出口）。"""
        S = self.g.source_side(self.s)
        return [name for k, kind, name in self.arcs if kind == "sink" and self.ends[k][0] in S]

    def edge_flow(self) -> Dict[EdgeKey, float]:
        return {name: self.g.flow(k) for k, kind, name in self.arcs if kind == "edge"}


# ═══════════════════════════════════════════════════════════
#  向きごとの上限（通り抜けの最大流）
# ═══════════════════════════════════════════════════════════

def through_limit(m: KagomeModel, cap: Dict[EdgeKey, float], allow_turns: bool = True) -> Dict[int, dict]:
    """向き d の入口から入り、向き d に進んで出る出口までの最大流 C_d と、その最小カット。

    入口から素辺を通らずに抜ける分（格子の角）は数えない（地域を通り抜けていないため）。
    """
    out = {}
    for d in range(1, 7):
        ents = {x: INF for x in m.entrances if x[3] == d}
        net = FlowNet(m, cap, ents, exit_road=d, direct_exit=False, allow_turns=allow_turns)
        out[d] = {"C": float(net.value), "cut": net.cut_edges(), "entrances": len(ents)}
    return out


# ═══════════════════════════════════════════════════════════
#  グローバル：全体の最大流での受け入れ
# ═══════════════════════════════════════════════════════════

def flow_arcs(m: KagomeModel):
    """流れの変数：曲がり方ごとの量。(種類, 始まり, 曲がり方, 行き先)
    種類 turn（素辺→素辺）、exit（素辺→出口）、inj（入口→素辺）、dir（入口→そのまま出口）。出口は (交差点, 出ていく向き)。
    """
    arcs = []
    for e in m.edges:
        node = m.target(e)
        for t in TURNS:
            e2 = m.out_edge(node, e[3], t)
            if e2 is not None:
                arcs.append(("turn", e, t, e2))
            else:
                arcs.append(("exit", e, t, (node, TURN_TABLE[(node[0], e[3])][t])))
    for x in m.entrances:
        for t in TURNS:
            e2 = m.out_edge(x[:3], x[3], t)
            if e2 is not None:
                arcs.append(("inj", x, t, e2))
            else:
                arcs.append(("dir", x, t, (x[:3], TURN_TABLE[(x[0], x[3])][t])))
    return arcs


def _lp_max_lambda(m, cap, b, a, S, lo, hi, P):
    """出口の配分を保つときの、入れられる最大の λ（lo ≤ λ ≤ hi）を線形計画 1 回で求める。

    S の入口は λ b_x、それ以外は a_x を入れる。出口ごとの量は Σ（入れた量 × P[x]）。解けなければ None。
    """
    from scipy.optimize import linprog
    from scipy.sparse import lil_matrix
    arcs = flow_arcs(m)
    n = len(arcs)
    eidx = {e: i for i, e in enumerate(m.edges)}
    ents = list(m.entrances)
    xidx = {x: i for i, x in enumerate(ents)}
    ys = sorted({dst for (kind, _, _, dst) in arcs if kind in ("exit", "dir")})
    yidx = {y: i for i, y in enumerate(ys)}
    nE, nX, nY = len(m.edges), len(ents), len(ys)
    Aeq = lil_matrix((nE + nX + nY, n + 1))
    beq = np.zeros(nE + nX + nY)
    Aub = lil_matrix((nE, n + 1))
    for k, (kind, src, t, dst) in enumerate(arcs):
        if kind in ("turn", "inj"):
            Aeq[eidx[dst], k] += 1.0
        if kind in ("turn", "exit"):
            Aeq[eidx[src], k] -= 1.0
            Aub[eidx[src], k] += 1.0
        if kind in ("inj", "dir"):
            Aeq[nE + xidx[src], k] += 1.0
        if kind in ("exit", "dir"):
            Aeq[nE + nX + yidx[dst], k] += 1.0
    for x in ents:
        if x in S:
            Aeq[nE + xidx[x], n] = -b[x]
        else:
            beq[nE + xidx[x]] = a.get(x, 0.0)
    for x in b:
        for y, p in P[x].items():
            if x in S:
                Aeq[nE + nX + yidx[y], n] -= b[x] * p
            else:
                beq[nE + nX + yidx[y]] += a.get(x, 0.0) * p
    bub = np.array([cap[e] for e in m.edges])
    c = np.zeros(n + 1)
    c[n] = -1.0
    res = linprog(c, A_ub=Aub.tocsr(), b_ub=bub, A_eq=Aeq.tocsr(), b_eq=beq,
                  bounds=[(0, None)] * n + [(lo, hi)], method="highs")
    return float(res.x[n]) if res.status == 0 else None


def exit_amounts(m: KagomeModel, inflow: Dict[EdgeKey, float]) -> Dict[tuple, float]:
    """今の分岐の割合で流したとき、出口（交差点, 出ていく向き）ごとに格子の外へ出る量。"""
    V = m.propagate(inflow)["V"] if inflow else {e: 0.0 for e in m.edges}
    out = {}
    for e in m.edges:
        node = m.target(e)
        for tn in TURNS:
            if m.out_edge(node, e[3], tn) is None:
                y = (node, TURN_TABLE[(node[0], e[3])][tn])
                out[y] = out.get(y, 0.0) + V[e] * m.beta(node, e[3], tn)
    for x, b in inflow.items():
        for tn in TURNS:
            if m.out_edge(x[:3], x[3], tn) is None:
                y = (x[:3], TURN_TABLE[(x[0], x[3])][tn])
                out[y] = out.get(y, 0.0) + b * m.beta(x[:3], x[3], tn)
    return out


def exit_matrix(m: KagomeModel, ents) -> Dict[EdgeKey, Dict[tuple, float]]:
    """入口ごとに、1 だけ入れて今の分岐の割合で流したときの出口ごとの量（伝播を 1 回の行列計算でまとめて解く）。"""
    if not ents:
        return {}
    n = len(m.edges)
    A = np.eye(n) - m.transfer_matrix()
    Q = np.zeros((n, len(ents)))
    for c, x in enumerate(ents):
        Q[:, c] = m.entrance_injection({x: 1.0})
    Vs = np.linalg.solve(A, Q) if n else Q
    out = {x: {} for x in ents}
    for e in m.edges:
        node = m.target(e)
        for t in TURNS:
            if m.out_edge(node, e[3], t) is None:
                bt = m.beta(node, e[3], t)
                if bt <= 0:
                    continue
                y = (node, TURN_TABLE[(node[0], e[3])][t])
                row = Vs[m.index[e], :] * bt
                for c, x in enumerate(ents):
                    if row[c] != 0.0:
                        out[x][y] = out[x].get(y, 0.0) + float(row[c])
    for x in ents:
        for t in TURNS:
            if m.out_edge(x[:3], x[3], t) is None:
                bt = m.beta(x[:3], x[3], t)
                if bt > 0:
                    y = (x[:3], TURN_TABLE[(x[0], x[3])][t])
                    out[x][y] = out[x].get(y, 0.0) + bt
    return out


class _Admission:
    """入口ごとの量 a を入れられるか（容量以内に流し切れるか）を最大流で確かめる。"""

    def __init__(self, m, cap, b, exits):
        self.m, self.cap, self.exits = m, cap, exits
        self.P = exit_matrix(m, list(b)) if exits == "keep" else None

    def net(self, a):
        caps = None
        if self.P is not None:
            caps = {}
            for x, ax in a.items():
                for y, p in self.P[x].items():
                    caps[y] = caps.get(y, 0.0) + ax * p
        return FlowNet(self.m, self.cap, a, exit_caps=caps)

    def stuck(self, a, active):
        """もう増やせない入口：最大流の後の残りの容量で、その入口から行き先へ届かない入口。

        free : 出口（t）へ届かなければ詰まっている
        keep : 入口を増やすと、出口ごとの量もその入口の配分 P[x] どおりに増える。配分のある出口のうち
               1 つでも届かなければ詰まっている（今の出口の量はちょうど使い切っているので、増えた分は
               増えた出口からしか出られない）
        """
        net = self.net(a)
        g = net.g
        eps = 1e-7 * max([1.0] + list(a.values()))    # 二分法の誤差より大きく、意味のある空きより小さい幅
        out = set()
        for x in active:
            seen = g.reach_from(net.ids[("x", x)], eps)
            if self.P is None:
                if net.t not in seen:
                    out.add(x)
            elif any(p > 1e-9 and net.ids[("y", y)] not in seen for y, p in self.P[x].items()):
                out.add(x)
        return out

    def ok(self, a, net=None):
        net = net or self.net(a)
        tot = sum(a.values())
        return net.value >= tot - 1e-9 * max(1.0, tot)


def global_maxflow(m: KagomeModel, inflow: Dict[EdgeKey, float], cap: Dict[EdgeKey, float],
                   exits: str = "keep", max_rounds: int = 1000) -> Dict[str, object]:
    """全部の入口を同じ割合 λ で上げていき、詰まった入口から順に止める（最大最小の公平な割り当て）。

    各回：止まっていない入口の量を λ b_x として、入れられる最大の λ（≤ 1）を求め
    （出口の配分を保つときは線形計画、出口が自由なときは最大流の二分法）、
    そのとき残りの容量で行き先へ届かない（もう増やせない）入口を止める。
    exits="keep": 出口ごとの量は、入れた量を今の分岐の割合で流したときの配分のまま。"free": どの出口でもよい。
    返り値: admitted（入口ごとの量）, ratio（a_x / b_x）, total（合計）, rejected_total,
            cut（受け入れを決めた最小カットの素辺）, uniform_ratio（全部同じ割合で絞ったときの λ）,
            no_local_ratio（今の分岐の割合のまま、どの素辺も容量を超えない最大の λ）, routing（回し方の例）
    """
    if exits not in ("keep", "free"):
        raise ValueError(f"出口の扱いが違う: {exits}")
    b = {x: float(v) for x, v in inflow.items() if v > 0}
    adm = _Admission(m, cap, b, exits)
    a = {x: 0.0 for x in b}
    uniform, rounds, stall = None, 0, 0
    # 水位を上げるやり方：まだ増やせる入口のうち、割合が水位 λ より低いものを λ まで上げる。
    # 入れられる最大の λ を二分法で求め、もう増やせなくなった入口を外して繰り返す。
    # （出口の配分を保つときは、他の入口が増えると出口の空きが増え、止めた入口がまた増やせることがある。
    #   そのため毎回、全部の入口について増やせるかを確かめ直す）
    while rounds < max_rounds:
        rounds += 1
        cand = {x for x in b if a[x] < b[x] * (1 - 1e-12)}
        if not cand:
            break
        active = cand - adm.stuck(a, cand) if rounds > 1 else cand
        if not active:
            break
        level = min(a[x] / b[x] for x in active)
        trial = lambda L: {x: (max(a[x], L * b[x]) if x in active else a[x]) for x in b}
        if adm.ok(trial(1.0)):
            lam = 1.0
        elif adm.P is not None and _HAVE_SCIPY:
            # 出口の配分を保つとき：λ の区間ごと（入口が λ まで上がり始める点で区切る）に線形計画で最大の λ を求める
            brk = sorted({a[x] / b[x] for x in active if a[x] / b[x] > level} | {1.0})
            lo, lam = level, level
            for hi in brk:
                S = {x for x in active if a[x] / b[x] <= lo + 1e-15}
                got = _lp_max_lambda(m, cap, b, a, S, lo, hi, adm.P)
                if got is None:
                    break
                lam = got
                if got < hi - 1e-12:
                    break
                lo = hi
            lam = lam * (1 - 1e-9)                    # 線形計画の誤差の分だけ内側に取る
        else:
            lo, hi = level, 1.0
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if adm.ok(trial(mid)) else (lo, mid)
            lam = lo
        if uniform is None:
            uniform = lam
        new = trial(lam)
        gain = sum(new.values()) - sum(a.values())
        a = new
        stall = stall + 1 if gain <= 1e-9 * max(1.0, sum(b.values())) else 0
        if lam >= 1.0 or stall >= 3:                  # 3 回続けて増えなければ打ち切る（数値の誤差）
            break
    net = adm.net(a)
    cut = net.cut_edges()
    cut_exits = net.cut_exits()
    V = m.propagate(b)["V"]
    no_local = min([1.0] + [cap[e] / V[e] for e in m.edges if V[e] > TOL])
    by_d = {}
    for d in range(1, 7):
        xs = [x for x in b if x[3] == d]
        dem, ad = sum(b[x] for x in xs), sum(a[x] for x in xs)
        by_d[d] = {"demand": dem, "admitted": ad, "rejected": dem - ad}
    total = sum(a.values())
    return {"admitted": a, "ratio": {x: a[x] / b[x] for x in b}, "total": total, "exits": exits,
            "requested": sum(b.values()), "rejected_total": sum(b.values()) - total,
            "by_direction": by_d, "cut": cut, "cut_exits": cut_exits, "uniform_ratio": uniform if uniform is not None else 1.0,
            "no_local_ratio": no_local, "routing": routing(m, net)}


def routing(m: KagomeModel, net: FlowNet) -> Dict[tuple, Dict[str, float]]:
    """最大流の流し方を分岐の割合に直す（β = 曲がった量 / 素辺の量）。流れの無い所は今の割合のまま。

    閉じた回り道を回り続ける流れは、入口から出口への道に分けるときに取り除く。
    """
    g = net.g
    out_arcs = {}
    for k, kind, name in net.arcs:
        f = g.flow(k)
        if f > TOL:
            u, v = net.ends[k]
            out_arcs.setdefault(u, []).append([v, f, kind, name])
    kept = {}
    for _ in range(1000000):
        path, u, seen = [], net.s, {net.s}
        while u != net.t:
            nxt = next((arc for arc in out_arcs.get(u, []) if arc[1] > TOL and arc[0] not in seen), None)
            if nxt is None:
                break
            path.append(nxt)
            u = nxt[0]
            seen.add(u)
        if u != net.t:
            if not path:
                break
            path[-1][1] = 0.0                         # 行き止まり（閉じた回り道）。この辺はもう使わない
            continue
        f = min(arc[1] for arc in path)
        for arc in path:
            arc[1] -= f
            kept[(arc[2], arc[3])] = kept.get((arc[2], arc[3]), 0.0) + f
    beta = {k: dict(v) for k, v in m.branching.items()}
    for (kind, e), fe in list(kept.items()):
        if kind != "edge" or fe <= TOL:
            continue
        node = m.target(e)
        bt = {}
        for tn in TURNS:
            e2 = m.out_edge(node, e[3], tn)
            bt[tn] = kept.get(("turn", (e, e2)) if e2 is not None else ("exit", (e, tn)), 0.0)
        s_ = sum(bt.values())
        if s_ > TOL:
            beta[(*node, e[3])] = {tn: v / s_ for tn, v in bt.items()}
    for x in m.entrances:
        if kept.get(("source", x), 0.0) <= TOL:
            continue
        bt = {}
        for tn in TURNS:
            e2 = m.out_edge(x[:3], x[3], tn)
            bt[tn] = kept.get(("inject", (x, e2)) if e2 is not None else ("direct", (x, tn)), 0.0)
        s_ = sum(bt.values())
        if s_ > TOL:
            beta[x] = {tn: v / s_ for tn, v in bt.items()}
    return beta


# ═══════════════════════════════════════════════════════════
#  グローバル：向きごとの総交通量を道路インフラ限界以内に（資料 p.16 に忠実な形）
# ═══════════════════════════════════════════════════════════

def direction_load_matrix(m: KagomeModel, ents) -> Dict[int, Dict[EdgeKey, float]]:
    """G[d][x]：入口 x から 1 だけ入れて今の分岐の割合で流したときの、向き d の総交通量。"""
    G = {d: {x: 0.0 for x in ents} for d in range(1, 7)}
    if not ents or not m.edges:
        return G
    A = np.eye(len(m.edges)) - m.transfer_matrix()
    Q = np.zeros((len(m.edges), len(ents)))
    for c, x in enumerate(ents):
        Q[:, c] = m.entrance_injection({x: 1.0})
    Vs = np.linalg.solve(A, Q)
    for e in m.edges:
        row = Vs[m.index[e], :]
        for c, x in enumerate(ents):
            G[e[3]][x] += float(row[c])
    return G


def global_direction(m: KagomeModel, inflow: Dict[EdgeKey, float], C: Dict[int, float]) -> Dict[str, object]:
    """入口で入れる量を、向きごとの総交通量 T_d が道路インフラ限界 C_d を超えない範囲で決める。

    流れは今の分岐の割合で流す（伝播）ので、T_d は入れる量に比例する：T_d ＝ Σ_x a_x G[d][x]。
    全部の入口を同じ割合 λ で上げていき、限界に達した向きに流れ込む入口から順に止める
    （限界に達した向き d について G[d][x] > 0 の入口を止め、残りは上げ続ける）。式は線形なので厳密に決まる。
    返り値: admitted, ratio, total, requested, rejected_total, uniform_ratio, by_direction（入口の向きごと）,
            load（向きごとの限界・今の総交通量・入れた後の総交通量）, tight（限界に達した向き）
    """
    b = {x: float(v) for x, v in inflow.items() if v > 0}
    G = direction_load_matrix(m, list(b))
    a = {x: 0.0 for x in b}
    active = set(b)
    lam_prev, uniform, tight_all = 0.0, None, []
    while active:
        lam, tight = 1.0, []
        for d in range(1, 7):
            fixed = sum(a[x] * G[d][x] for x in b if x not in active)
            rate = sum(b[x] * G[d][x] for x in active)
            if rate <= 1e-15:
                continue
            ld = (C[d] - fixed) / rate
            if ld < lam - 1e-12:
                lam, tight = ld, [d]
            elif abs(ld - lam) <= 1e-12:
                tight.append(d)
        lam = max(lam, lam_prev)
        if uniform is None:
            uniform = lam
        for x in active:
            a[x] = lam * b[x]
        if lam >= 1.0 or not tight:
            break
        tight_all += [d for d in tight if d not in tight_all]
        stop = {x for x in active if any(G[d][x] > 1e-15 for d in tight)}
        if not stop:
            break
        active -= stop
        lam_prev = lam
    load_before = {d: sum(b[x] * G[d][x] for x in b) for d in range(1, 7)}
    load_after = {d: sum(a[x] * G[d][x] for x in b) for d in range(1, 7)}
    by_d = {}
    for d in range(1, 7):
        xs = [x for x in b if x[3] == d]
        dem, ad = sum(b[x] for x in xs), sum(a[x] for x in xs)
        by_d[d] = {"demand": dem, "admitted": ad, "rejected": dem - ad}
    total = sum(a.values())
    return {"admitted": a, "ratio": {x: a[x] / b[x] for x in b}, "total": total, "requested": sum(b.values()),
            "rejected_total": sum(b.values()) - total, "uniform_ratio": uniform if uniform is not None else 1.0,
            "by_direction": by_d, "tight": tight_all,
            "load": {d: {"limit": C[d], "before": load_before[d], "after": load_after[d]} for d in range(1, 7)}}
