# -*- coding: utf-8 -*-
"""カゴメ格子モデル：格子・値・計算（設計書 §4・§5 の P1〜P5 のうち、式が決まっている部分）。

用語は分野に依存しない言葉にそろえる。
  素辺（edge）   … 交差点から交差点への有向の辺。キー (node_type, i, j, road)
  交差点（node） … C・D・E。キー (node_type, i, j)
  向き（road）   … 1〜6。水平右向きが 1、反時計回りに番号。(1,4)(2,5)(3,6) が逆向き
  分岐の割合     … 交差点に向き r から入った流れが S（直進）・R（時計回り側）・L（反時計回り側）へ分かれる割合

各変数にどの物理量を当てはめるか（流れ＝交通量・物の量・血流量…）は使う側が分野ごとに決める。
このモジュールは数学的な変数として扱うだけで、その意味付けの正しさは保証しない。

格子と分解の計算は、既存ツール（kagomesoft）で検証済みのエンジン _engine.py を無改変で使う。
"""
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import _engine as E

EdgeKey = Tuple[str, int, int, int]
NodeKey = Tuple[str, int, int]

TURNS = ("S", "R", "L")
DIRECTIONS = (1, 2, 3, 4, 5, 6)


def _turn_table():
    """(交差点の種類, 入ってきた向き) → {S/R/L: 出ていく向き}。エンジンの回転表から作る。"""
    table = {}
    for m in (E.TURN_MAP_UP, E.TURN_MAP_DOWN, E.TURN_MAP_HEX_UPPER, E.TURN_MAP_HEX_LOWER):
        for t, turns in m.items():
            for turn, d in turns.items():
                table.setdefault((t, d["in_road"]), {})[turn] = d["out_road"]
    for t, roads in E.CONNECTED_ROADS.items():
        for r in roads:
            table.setdefault((t, r), {})["S"] = r          # 直進は同じ向きのまま
    return table


TURN_TABLE = _turn_table()


@dataclass
class EdgeValues:
    """素辺ごとの値（設計書 §4）。None は未入力。"""
    m: Optional[float] = None      # 並列経路数（等価本数も可）。交通版では車線数
    L: Optional[float] = None      # 距離
    v: Optional[float] = None      # 輸送速度（長さ/時間）
    V: Optional[float] = None      # 輸送流量（単位時間あたり。観測モード）
    T: Optional[float] = None      # 分布の幅（フェルミ・ディラック型。規格化量と同じ単位）
    mu: Optional[float] = None     # フェルミ準位（臨界点）


class KagomeModel:
    """N×N 個の単位格子からなるカゴメ格子と、その上の値。

    halo=True なら、周りに 1 リングの余白を付けた (N+2)×(N+2) の格子を作る。
    解析の対象は内側の N×N（添字 1〜N）で、余白は「格子の端で直進成分が計算しきれない」のを
    内側に持ち込まないためのもの（余白の素辺にも値は入れる）。内側の素辺はすべて計算しきれる。
    """

    def __init__(self, n: int, halo: bool = False):
        if n < 1:
            raise ValueError("格子の大きさ N は 1 以上")
        self.n = n
        self.halo = bool(halo)
        self.size = n + 2 if self.halo else n
        self._lat = E.KagomeLattice(rows=self.size, cols=self.size)
        self.nodes: List[NodeKey] = sorted(
            (nd.node_type, nd.i, nd.j) for nd in self._lat.main_intersections)
        self._node_set = set(self.nodes)
        self.edges: List[EdgeKey] = []
        self.exits: List[EdgeKey] = []          # 格子の外へ出ていく向き（交差点, 向き）
        for (t, i, j) in self.nodes:
            for r in E.CONNECTED_ROADS[t]:
                tg = self.target((t, i, j, r))
                (self.edges if tg is not None else self.exits).append((t, i, j, r))
        self.index = {e: k for k, e in enumerate(self.edges)}
        # 入口：格子の外から、交差点へ向き r で入ってくる流れ（交差点, 入ってくる向き）
        self.entrances: List[EdgeKey] = []
        for (t, i, j) in self.nodes:
            for r in E.CONNECTED_ROADS[t]:
                if self.upstream((t, i, j), r) is None:
                    self.entrances.append((t, i, j, r))
        self.values: Dict[EdgeKey, EdgeValues] = {e: EdgeValues() for e in self.edges}
        lo, hi = (1, n) if self.halo else (0, n - 1)
        self.inner_nodes = {nd for nd in self.nodes if lo <= nd[1] <= hi and lo <= nd[2] <= hi}
        self.inner_edges: List[EdgeKey] = [e for e in self.edges if self.is_inner(e)]
        self.branching: Dict[Tuple[str, int, int, int], Dict[str, float]] = {}

    # ─── 幾何 ─────────────────────────────────────────
    def is_inner(self, e: EdgeKey) -> bool:
        """素辺 e が解析の対象（内側）か。余白が無ければすべて内側。"""
        if not self.halo:
            return True
        tg = self.target(e)
        return e[:3] in self.inner_nodes and tg is not None and tg in self.inner_nodes

    def target(self, e: EdgeKey) -> Optional[NodeKey]:
        """素辺 e の到着交差点（格子の外なら None）。"""
        t, i, j, r = e
        tg = self._lat.get_outgoing_target(t, i, j, r)
        return tuple(tg) if tg is not None and tuple(tg) in self._node_set else None

    def upstream(self, node: NodeKey, r: int) -> Optional[EdgeKey]:
        """交差点 node へ向き r で入ってくる素辺（格子の外から来るなら None）。"""
        t, i, j = node
        for (st, rr), (tt, di, dj) in E.OUTGOING_TARGET_OFFSETS.items():
            if rr == r and tt == t:
                src = (st, i - di, j - dj)
                if src in self._node_set:
                    return (*src, r)
        return None

    def out_edge(self, node: NodeKey, in_road: int, turn: str) -> Optional[EdgeKey]:
        """交差点 node に in_road から入って turn へ進むときの、出ていく素辺（出口なら None）。"""
        out = TURN_TABLE[(node[0], in_road)][turn]
        e = (*node, out)
        return e if e in self.index else None

    @staticmethod
    def position(node: NodeKey, scale: float = 1.0) -> Tuple[float, float]:
        return E.KagomeLattice.calc_position(node[0], node[1], node[2], scale=scale)

    def lines(self) -> Dict[int, List[List[EdgeKey]]]:
        """向きごとの「紐」：同じ向きのまま直進でつながる素辺の列。"""
        out = {d: [] for d in DIRECTIONS}
        for e in self.edges:
            t, i, j, r = e
            if self.upstream((t, i, j), r) is not None:
                continue                                  # 途中の素辺。始まりから辿る
            line, cur = [], e
            while cur is not None:
                line.append(cur)
                tg = self.target(cur)
                cur = (*tg, r) if tg is not None and (*tg, r) in self.index else None
            out[r].append(line)
        return out

    # ─── 値の入力 ─────────────────────────────────────
    def set_edge(self, e: EdgeKey, **kw):
        if e not in self.values:
            raise KeyError(f"格子に無い素辺: {e}")
        for k, v in kw.items():
            if not hasattr(self.values[e], k):
                raise KeyError(f"素辺の値の名前が違う: {k}")
            setattr(self.values[e], k, None if v is None else float(v))

    def set_branching(self, node: NodeKey, in_road: int, S: float, R: float, L: float):
        if node not in self._node_set or in_road not in E.CONNECTED_ROADS[node[0]]:
            raise KeyError(f"格子に無い交差点・向き: {node} {in_road}")
        self.branching[(*node, in_road)] = {"S": float(S), "R": float(R), "L": float(L)}

    def beta(self, node: NodeKey, in_road: int, turn: str) -> float:
        return self.branching.get((*node, in_road), {}).get(turn, 0.0)

    # ─── P1 規格化 ────────────────────────────────────
    def normalize(self, V: Optional[Dict[EdgeKey, float]] = None, mode: str = "m") -> Dict[EdgeKey, float]:
        """規格化した流れ J_e。

        mode="k"  : V/(v·m)。1 車線あたりの交通密度（台/km/車線）。交通工学の標準の見方
                    （交通量 ＝ 密度 × 速度）で、渋滞の臨界点を臨界密度として比べる（比較用）
        mode="m"  : V/m。原資料のjに対応する1並列経路あたりの流量（新規の基本設定）
        mode="mvl": V·v/(L·m)（設計書 P1 の候補）
        """
        out = {}
        for e in self.edges:
            ev = self.values[e]
            Ve = (V or {}).get(e, ev.V)
            if Ve is None:
                raise ValueError(f"流量が未入力: {e}")
            if mode == "m":
                out[e] = Ve / ev.m
            elif mode == "k":
                out[e] = Ve / (ev.v * ev.m)
            elif mode == "mvl":
                out[e] = Ve * ev.v / (ev.L * ev.m)
            else:
                raise ValueError(f"規格化の方式が違う: {mode}")
        return out

    def denormalize_factor(self, e: EdgeKey, mode: str = "m") -> float:
        """J を流量 V に戻す係数（V = J × これ）。"""
        ev = self.values[e]
        if mode == "m":
            return ev.m
        if mode == "k":
            return ev.v * ev.m
        if mode == "mvl":
            return ev.L * ev.m / ev.v
        raise ValueError(f"規格化の方式が違う: {mode}")

    # ─── エンジンへの受け渡し ──────────────────────────
    def _engine_lattice(self, J: Dict[EdgeKey, float], tau_mode: str = "engine", norm: str = "m"):
        """値を入れたエンジンの格子を作る。分岐の割合は到着交差点の (入ってきた向き, S/R/L) に置く。

        tau_mode（局所回転 τ の分子に何を使うか）:
          "count"  … 現行実装では輸送流量 V_in を使う（原資料のjを使う式とは別の比較用方式）
                     τ = V_in β L_in / (m_out L_out)。一様な流れで直進成分が厳密に J × β^S になる
                     規格化が V/m 以外のときは、m_out の代わりに曲がり先の「J を V に戻す係数」で割り、
                     τ を J と同じ単位にする（norm="k" なら v_out·m_out）
          "engine" … 規格化した流れ J_in を使う τ = J_in β L_in / (m_out L_out)。
                     norm="m" かつ V=n·v/L と対応させた場合、原資料5・24〜28ページのjとτの通用形に対応する。
                     原資料の表記差7項は図形に沿う進行方向で正規化し、原文と実装判断を記録する。
        """
        if tau_mode not in ("count", "engine"):
            raise ValueError(f"τ の式の指定が違う: {tau_mode}")
        lat = E.KagomeLattice(rows=self.size, cols=self.size)
        for e in self.edges:
            t, i, j, r = e
            src = lat.get_intersection(t, i, j)
            tg = self.target(e)
            dst = lat.get_intersection(*tg)
            ev = self.values[e]
            src.flows[(r, "out")] = J[e]
            dst.flows[(r, "in")] = J[e]
            src.road_length[(r, "out")] = ev.L
            dst.road_length[(r, "in")] = ev.L
            src.norm_lanes[(r, "out")] = ev.m
            # τ の分母は「曲がり先の素辺の容量の重み」。エンジンは交差点の (出ていく向き, 曲がり方) に持つ。
            # "count" では分子を輸送流量にするため、入ってくる素辺の重みで割り戻した値を置く
            # （交差点の種類・出ていく向き・曲がり方が決まれば、入ってくる向きは 1 つに決まる）。
            for turn in TURNS:
                w = ev.m
                if tau_mode == "count" and turn in ("R", "L"):
                    in_road = next((ri for ri in E.CONNECTED_ROADS[t]
                                    if TURN_TABLE[(t, ri)][turn] == r), None)
                    up = self.upstream((t, i, j), in_road) if in_road is not None else None
                    k_out = self.denormalize_factor(e, norm)
                    w = k_out / self.denormalize_factor(up, norm) if up is not None else k_out
                src.lane_count[(r, turn)] = w
        for (t, i, j, r), b in self.branching.items():
            nd = lat.get_intersection(t, i, j)
            for turn in TURNS:
                nd.beta[(r, turn)] = b[turn]
        return lat

    # ─── P2 回転量と分解 ───────────────────────────────
    def decompose(self, J: Dict[EdgeKey, float], tau_mode: str = "engine", norm: str = "m") -> Dict[str, dict]:
        """局所回転 τ、三角形の回転量 s、六角形の回転量 σ、直進成分 J⁺・J⁻。

        直進成分が計算に使う三角形・六角形の頂点が格子に欠けている素辺は complete=False。
        tau_mode は _engine_lattice を参照。
        """
        lat = self._engine_lattice(J, tau_mode, norm)
        main = self._node_set
        missing = []
        orig = lat.get_intersection

        def watched(t, i, j):                    # 格子の外の頂点を参照したかを記録する
            if (t, i, j) not in main:
                missing.append((t, i, j))
            return orig(t, i, j)
        lat.get_intersection = watched

        # τ が「格子に無い素辺」（入ってくる素辺か曲がり先の素辺が格子の外）を使ったかも記録する
        base_tau = E.Intersection.calc_tau_with_map
        for (t, i, j) in self.nodes:
            nd = orig(t, i, j)

            def tau_watched(turn_map, turn, nd=nd, node=(t, i, j)):
                m = turn_map[node[0]][turn]
                if (self.upstream(node, m["in_road"]) is None
                        or (*node, m["out_road"]) not in self.index):
                    missing.append((*node, turn))
                return base_tau(nd, turn_map, turn)
            nd.calc_tau_with_map = tau_watched

        tau = {}
        for (t, i, j) in self.nodes:
            nd = orig(t, i, j)
            for tri in ("up", "down"):
                for turn in ("R", "L"):
                    tau[(t, i, j, tri, turn)] = nd.calc_tau(turn, tri)
        s, sigma = {}, {}
        for (i, j) in sorted({(n[1], n[2]) for n in self.nodes}):
            s[("u", "+", i, j)] = lat.calc_s_up_plus(i, j)
            s[("u", "-", i, j)] = lat.calc_s_up_minus(i, j)
            s[("d", "+", i, j)] = lat.calc_s_down_plus(i, j)
            s[("d", "-", i, j)] = lat.calc_s_down_minus(i, j)
            sigma[("+", i, j)] = lat.calc_sigma_plus(i, j)
            sigma[("-", i, j)] = lat.calc_sigma_minus(i, j)
        straight = {}
        for e in self.edges:
            t, i, j, r = e
            tg = self.target(e)
            missing.clear()
            jplus = lat._calc_in_potential(tg[0], tg[1], tg[2], r)   # 到着側で見た直進成分
            complete = not missing
            straight[e] = {"J": J[e], "J_straight": jplus, "complete": complete}
        lat.get_intersection = orig
        return {"tau": tau, "s": s, "sigma": sigma, "straight": straight}

    # ─── P3 臨界点（フェルミ・ディラック） ──────────────
    @staticmethod
    def fermi_dirac(eps: float, mu: float, T: float) -> float:
        x = -(eps - mu) / T
        if x > 700:
            return 0.0
        return 1.0 / (1.0 + math.exp(x))

    def critical(self, eps: Dict[EdgeKey, float], theta: float = 0.5) -> Dict[EdgeKey, dict]:
        """各素辺の分布の値 f、臨界量 ε*（f = θ となる ε）、臨界量までの余裕 ε* − ε と比 ε/ε*。

        θ = 1/2 なら ε* はフェルミ準位 μ そのもの。判定（混んでいる等）は付けない。
        """
        if not 0.0 < theta < 1.0:
            raise ValueError("θ は 0 と 1 の間")
        out = {}
        for e in self.edges:
            ev = self.values[e]
            if ev.T is None or ev.mu is None:
                raise ValueError(f"温度とフェルミ準位が未入力: {e}")
            if ev.T <= 0:
                raise ValueError(f"温度は正の値: {e}")
            es = ev.mu + ev.T * math.log(theta / (1.0 - theta))
            x = eps[e]
            out[e] = {"eps": x, "f": self.fermi_dirac(x, ev.mu, ev.T), "eps_star": es,
                      "margin": es - x, "ratio": (x / es) if es != 0 else float("nan")}
        return out

    # ─── P4 道路インフラ限界 ────────────────────────────
    def capacity(self, theta: float = 0.5, mode: str = "m") -> Dict[EdgeKey, float]:
        """素辺の臨界交通量 c_e ＝ 臨界量 ε*（f ＝ θ）を流量の単位に戻したもの（資料 p.16「渋滞臨界状態とする交通量」）。"""
        out = {}
        for e in self.edges:
            ev = self.values[e]
            es = ev.mu + ev.T * math.log(theta / (1.0 - theta))
            out[e] = es * self.denormalize_factor(e, mode)
        return out

    # ─── 標準状態（資料 p.13・p.16） ──────────────────────
    def standard_state(self, theta: float = 0.5, mode: str = "m", tau_mode: str = "engine") -> Dict[str, object]:
        """標準状態：全ての素辺を渋滞臨界状態とした状態（資料 p.16「調和状態の構成と標準交通量の算出」）。

        各素辺の交通量を臨界交通量 c_e とし、入力の分岐の割合（右左折の時空間的分岐割合）のまま分解して、
        標準状態の直進成分と回転量（スピン）を求める。これは比較用の基準で、節点の保存則や
        分岐割合との整合を満たすとは限らない。資料 p.13 の可解格子状態との対応は未確認。
        Yang–Baxter 関係に基づく基底状態の厳密解を計算する処理ではない。
        返り値: V（標準交通量）, J（規格化）, dec（分解。τ・s・σ・直進成分）
        """
        V = self.capacity(theta, mode)
        J = self.normalize(V=V, mode=mode)
        return {"V": V, "J": J, "dec": self.decompose(J, tau_mode=tau_mode, norm=mode)}

    def direction_totals(self, V: Dict[EdgeKey, float]) -> Dict[int, float]:
        """向きごとの総交通量 T_d ＝ 向き d の素辺の交通量の和。"""
        out = {d: 0.0 for d in DIRECTIONS}
        for e in self.edges:
            out[e[3]] += V[e]
        return out

    # ─── P4 道路インフラ限界 ────────────────────────────
    def infrastructure_limit(self, theta: float = 0.5, mode: str = "m",
                             rule: str = "critical_total") -> Dict[int, dict]:
        """向きごとの道路インフラ限界 C_d。

        rule="critical_total"  : 資料 p.16 のとおり。全ての素辺を渋滞臨界状態とする交通量（臨界交通量 c_e）を求め、
                                 完全格子の各辺（向き d の紐の束）の総交通量 C_d ＝ Σ_{向き d の素辺} c_e とする（既定）
        rule="through_maxflow" : 参考。向き d の入口から向き d の出口までの最大流（途中で曲がってよい）
        rule="line_min_sum"    : 参考。同じ紐の上は最小、平行な紐どうしは和（曲がりを禁止したときの最大流）
        どの規則でも、参考として line_min_sum と critical_total の値を付ける。
        """
        cap = self.capacity(theta, mode)
        lines = self.lines()
        lms = {d: [min(lns, key=lambda e: cap[e]) for lns in ls] for d, ls in lines.items()}
        tot = self.direction_totals(cap)
        out = {}
        if rule == "critical_total":
            for d, ls in lines.items():
                out[d] = {"C": float(tot[d]), "lines": len(ls), "bottlenecks": []}
        elif rule == "through_maxflow":
            from .flow import through_limit
            for d, v in through_limit(self, cap).items():
                out[d] = {"C": v["C"], "lines": len(lines[d]), "bottlenecks": v["cut"]}
        elif rule == "line_min_sum":
            for d, ls in lines.items():
                out[d] = {"C": float(sum(cap[e] for e in lms[d])), "lines": len(ls), "bottlenecks": lms[d]}
        else:
            raise ValueError(f"上限の出し方が違う: {rule}")
        for d in out:
            out[d]["line_min_sum"] = float(sum(cap[e] for e in lms[d]))
            out[d]["critical_total"] = float(tot[d])
        return out

    # ─── P5 伝播（入口からの流れを分岐の割合で流す） ──────
    def transfer_matrix(self) -> np.ndarray:
        """M[e', e] = 素辺 e から素辺 e' へ進む割合（e の到着交差点の分岐の割合）。"""
        n = len(self.edges)
        M = np.zeros((n, n))
        for e in self.edges:
            node = self.target(e)
            r = e[3]
            for turn in TURNS:
                e2 = self.out_edge(node, r, turn)
                if e2 is not None:
                    M[self.index[e2], self.index[e]] += self.beta(node, r, turn)
        return M

    def entrance_injection(self, inflow: Dict[EdgeKey, float]) -> np.ndarray:
        """入口（交差点, 入ってくる向き）からの流入量を、分岐の割合で最初の素辺へ配る。"""
        q = np.zeros(len(self.edges))
        for (t, i, j, r), b in inflow.items():
            if (t, i, j, r) not in self.entrances:
                raise KeyError(f"入口ではない: {(t, i, j, r)}")
            for turn in TURNS:
                e2 = self.out_edge((t, i, j), r, turn)
                if e2 is not None:
                    q[self.index[e2]] += b * self.beta((t, i, j), r, turn)
        return q

    def propagate(self, inflow: Dict[EdgeKey, float]) -> Dict[str, object]:
        """V = (I − M)⁻¹ q。各素辺の流量と、出口から出た量・入口から入った量を返す。"""
        from .steady import SteadyFlowError, require_unique_steady
        require_unique_steady(self, inflow)
        M = self.transfer_matrix()
        q = self.entrance_injection(inflow)
        A = np.eye(len(self.edges)) - M
        try:
            V = np.linalg.solve(A, q)
        except np.linalg.LinAlgError as ex:
            raise SteadyFlowError("numerical_failure", "定常流の連立方程式を解けませんでした。分岐割合や出口への流れが極端に小さい条件を確認してください。") from ex
        if not np.all(np.isfinite(V)):
            raise SteadyFlowError("nonfinite_solution", "定常流の計算結果が有限値になりませんでした。入力の桁と分岐条件を確認してください。")
        residual = float(np.max(np.abs(A @ V - q))) if len(V) else 0.0
        if residual > 1e-8 * max(1.0, float(np.max(np.abs(q), initial=0.0))):
            raise SteadyFlowError("large_residual", "連立方程式の計算誤差が大きいため、結果を採用できません。入力の桁と分岐条件を確認してください。")
        if float(np.min(V, initial=0.0)) < -1e-8 * max(1.0, float(np.max(np.abs(V), initial=0.0))):
            raise SteadyFlowError("negative_solution", "定常流が負になりました。分岐割合が非負で合計1か確認してください。")
        out_total = 0.0
        for e in self.edges:                         # 素辺の先で出口へ向かう分
            node, r = self.target(e), e[3]
            for turn in TURNS:
                if self.out_edge(node, r, turn) is None:
                    out_total += V[self.index[e]] * self.beta(node, r, turn)
        for (t, i, j, r), b in inflow.items():       # 入口からそのまま出口へ抜ける分
            for turn in TURNS:
                if self.out_edge((t, i, j), r, turn) is None:
                    out_total += b * self.beta((t, i, j), r, turn)
        balance_error = float(out_total - sum(inflow.values()))
        if abs(balance_error) > 1e-7 * max(1.0, abs(sum(inflow.values()))):
            raise SteadyFlowError("flow_imbalance", "入口と出口の総流量がつり合いません。分岐割合の合計や数値計算の精度を確認してください。")
        return {"V": {e: float(V[self.index[e]]) for e in self.edges},
                "inflow_total": float(sum(inflow.values())), "outflow_total": float(out_total),
                "residual": residual, "balance_error": balance_error}

    # ─── P5 の逆：観測した流量から入口の流入量を求める ──────
    def estimate_inflow(self, V: Optional[Dict[EdgeKey, float]] = None) -> Dict[str, object]:
        """観測モード用。伝播の式 (I − M) V = q を逆に使い、q を入口からの流入で説明する。

        q_needed = (I − M) V    … 各素辺の流量のうち、上流の素辺からの流れでは説明できない分
        q_needed ≈ B b          … B の列は「入口 x から 1 だけ入れたとき最初の素辺へ配られる量」
        b ≥ 0 を最小二乗で求め、残り（unexplained = q_needed − B b）を素辺ごとに返す。
        残りは「入れた流量と分岐の割合の組み合わせでは、入口からの流れとして説明できない分」で、
        それが何を意味するか（測り方の誤差・格子の中での出入りなど）は使う側が判断する。
        """
        Vv = np.array([(V or {}).get(e, self.values[e].V) for e in self.edges], dtype=float)
        A = np.eye(len(self.edges)) - self.transfer_matrix()
        need = A @ Vv
        B = np.zeros((len(self.edges), len(self.entrances)))
        for c, x in enumerate(self.entrances):
            B[:, c] = self.entrance_injection({x: 1.0})
        used = [c for c in range(B.shape[1]) if np.any(B[:, c] > 0)]
        Bu = B[:, used]
        try:
            from scipy.optimize import nnls
            b, _ = nnls(Bu, need)
        except ImportError:                       # scipy が無ければ、最小二乗の解を 0 で切る
            b = np.clip(np.linalg.lstsq(Bu, need, rcond=None)[0], 0.0, None)
        est = {x: None for x in self.entrances}   # 格子に何も入れない入口（すぐ出口へ抜ける）は決まらない
        for c, val in zip(used, b):
            est[self.entrances[c]] = float(val)
        res = need - Bu @ b
        scale = max(float(np.abs(Vv).sum()), 1e-12)
        return {"inflow": est,
                "needed": {e: float(need[k]) for k, e in enumerate(self.edges)},
                "unexplained": {e: float(res[k]) for k, e in enumerate(self.edges)},
                "unexplained_share": float(np.abs(res).sum()) / scale,
                "identifiable": bool(np.linalg.matrix_rank(Bu) == len(used)) if used else True}
