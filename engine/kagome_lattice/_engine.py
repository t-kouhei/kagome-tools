# -*- coding: utf-8 -*-
"""
カゴメ格子 交通流シミュレータ — コアデータモデル
Kagome Lattice Traffic Flow Simulator — Core Data Model

Phase 1: データ構造 + ダミーデータ生成
Phase 3: 回転要素 τ, s, σ の算出
Phase 4: 直進ポテンシャル J⁺, J⁻ の抽出
"""

import csv
import json
import math
import os
import random
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional, List


# ═══════════════════════════════════════════════════════════
#  定数・型定義
# ═══════════════════════════════════════════════════════════

# 道路番号の対向ペア
ROAD_PAIRS = {1: 4, 4: 1, 2: 5, 5: 2, 3: 6, 6: 3}

# 交差点タイプごとの接続道路番号
# 各交差点は 4 本の道路に接続（2辺 × 対向2方向）
# C: 道路1,4 (C↔E) と 道路3,6 (C↔D)
# D: 道路2,5 (D↔E) と 道路3,6 (D↔C)
# E: 道路1,4 (E↔C) と 道路2,5 (E↔D)
CONNECTED_ROADS = {
    'C': [1, 3, 4, 6],
    'D': [2, 3, 5, 6],
    'E': [1, 2, 4, 5],
}

# 接続規則: (from_type, road, direction) -> (to_type, road, direction)
# J^{C}_{1out} = J^{E}_{1in} のような関係
CONNECTION_RULES = [
    ('C', 1, 'out', 'E', 1, 'in'),
    ('C', 4, 'in',  'E', 4, 'out'),
    ('C', 3, 'in',  'D', 3, 'out'),
    ('C', 6, 'out', 'D', 6, 'in'),
    ('D', 2, 'out', 'E', 2, 'in'),
    ('D', 5, 'in',  'E', 5, 'out'),
]

# ─── 三角形タイプ別の回転マッピング ───
# 各エントリ: in_road, in_dir(流量方向), out_road, out_dir(流量方向)
#
# ★ 上向き三角形 (E_{i,j-1}, C_{i,j}, D_{i+1,j-1}) ← 画像1
# ★ 下向き三角形 (C_{i,j}, E_{i,j}, D_{i,j})         ← 画像2
# ★ 六角形 σ (6頂点)                                   ← 画像3

# ──────────────────────────────────────────────
#  画像1: 上向き三角形 τ
# ──────────────────────────────────────────────
TURN_MAP_UP = {
    'C': {
        # τ^R_C: j^{6in} β^{6R} L^{6in} / m^{4R} L^{4out}
        'R': {'in_road': 6, 'in_dir': 'in',  'out_road': 4, 'out_dir': 'out'},
        # τ^L_C: j^{1in} β^{1L} L^{1in} / m^{3L} L^{3out}
        'L': {'in_road': 1, 'in_dir': 'in',  'out_road': 3, 'out_dir': 'out'},
    },
    'E': {
        # τ^R_E: from C(inter) to D(inter)
        # j^{4in} β^{4R} L^{4in} / m^{2R} L^{2out}
        'R': {'in_road': 4, 'in_dir': 'in',  'out_road': 2, 'out_dir': 'out'},
        # τ^L_E: from D(inter) to C(inter)
        # j^{5in} β^{5L} L^{5in} / m^{1L} L^{1out}
        'L': {'in_road': 5, 'in_dir': 'in',  'out_road': 1, 'out_dir': 'out'},
    },
    'D': {
        # τ^R_D: j^{2in} β^{2R} L^{2in} / m^{6R} L^{6out}
        'R': {'in_road': 2, 'in_dir': 'in',  'out_road': 6, 'out_dir': 'out'},
        # τ^L_D: j^{3in} β^{3L} L^{3in} / m^{5L} L^{5out}
        'L': {'in_road': 3, 'in_dir': 'in',  'out_road': 5, 'out_dir': 'out'},
    },
}

# ──────────────────────────────────────────────
#  画像2: 下向き三角形 τ
# ──────────────────────────────────────────────
TURN_MAP_DOWN = {
    'C': {
        # τ^R_C: from D(intra) to E(intra)
        # j^{3in} β^{3R} L^{3in} / m^{1R} L^{1out}
        'R': {'in_road': 3, 'in_dir': 'in',  'out_road': 1, 'out_dir': 'out'},
        # τ^L_C: from E(intra) to D(intra)
        # j^{4in} β^{4L} L^{4in} / m^{6L} L^{6out}
        'L': {'in_road': 4, 'in_dir': 'in',  'out_road': 6, 'out_dir': 'out'},
    },
    'E': {
        # τ^R_E: from C(intra) to D(intra)
        # j^{1in} β^{1R} L^{1in} / m^{5R} L^{5out}
        'R': {'in_road': 1, 'in_dir': 'in',  'out_road': 5, 'out_dir': 'out'},
        # τ^L_E: from D(intra) to C(intra)
        # j^{2in} β^{2L} L^{2in} / m^{4L} L^{4out}
        'L': {'in_road': 2, 'in_dir': 'in',  'out_road': 4, 'out_dir': 'out'},
    },
    'D': {
        # τ^R_D: from E(intra) to C(intra)
        # j^{5in} β^{5R} L^{5in} / m^{3R} L^{3out}
        'R': {'in_road': 5, 'in_dir': 'in',  'out_road': 3, 'out_dir': 'out'},
        # τ^L_D: from C(intra) to E(intra)
        # j^{6in} β^{6L} L^{6in} / m^{2L} L^{2out}
        'L': {'in_road': 6, 'in_dir': 'in',  'out_road': 2, 'out_dir': 'out'},
    },
}

# ──────────────────────────────────────────────
#  画像3: 六角形 σ 用 τ
#  σ^+_{i,j} = τ^R(上半分3頂点) + τ^R(下半分3頂点)
#  σ^-_{i,j} = τ^L(上半分3頂点) + τ^L(下半分3頂点)
#  上半分: C_{i,j}, E_{i,j-1}, D_{i,j}
#  下半分: C_{i-1,j}, E_{i-1,j}, D_{i,j-1}
# ──────────────────────────────────────────────
TURN_MAP_HEX_UPPER = {
    'C': {
        # τ^R_C: j^{1in} β^{1R} L^{1in} / m^{6R} L^{6out}
        'R': {'in_road': 1, 'in_dir': 'in',  'out_road': 6, 'out_dir': 'out'},
        # τ^L_C: j^{3in} β^{3L} L^{3in} / m^{4L} L^{4out}
        'L': {'in_road': 3, 'in_dir': 'in',  'out_road': 4, 'out_dir': 'out'},
    },
    'E': {
        # τ^R_E: j^{2in} β^{2R} L^{2in} / m^{1R} L^{1out}
        'R': {'in_road': 2, 'in_dir': 'in',  'out_road': 1, 'out_dir': 'out'},
        # τ^L_E: j^{4in} β^{4L} L^{4in} / m^{5L} L^{5out}
        'L': {'in_road': 4, 'in_dir': 'in',  'out_road': 5, 'out_dir': 'out'},
    },
    'D': {
        # τ^R_D: j^{6in} β^{6R} L^{6in} / m^{5R} L^{5out}
        'R': {'in_road': 6, 'in_dir': 'in',  'out_road': 5, 'out_dir': 'out'},
        # τ^L_D: j^{2in} β^{2L} L^{2in} / m^{3L} L^{3out}
        'L': {'in_road': 2, 'in_dir': 'in',  'out_road': 3, 'out_dir': 'out'},
    },
}

TURN_MAP_HEX_LOWER = {
    'C': {
        # τ^R_C: from E(intra) to D(inter)
        # j^{4in} β^{4R} L^{4in} / m^{3R} L^{3out}
        'R': {'in_road': 4, 'in_dir': 'in',  'out_road': 3, 'out_dir': 'out'},
        # τ^L_C: from D(inter) to E(intra)
        # j^{6in} β^{6L} L^{6in} / m^{1L} L^{1out}
        'L': {'in_road': 6, 'in_dir': 'in',  'out_road': 1, 'out_dir': 'out'},
    },
    'E': {
        # τ^R_E: j^{5in} β^{5R} L^{5in} / m^{4R} L^{4out}
        'R': {'in_road': 5, 'in_dir': 'in',  'out_road': 4, 'out_dir': 'out'},
        # τ^L_E: j^{1in} β^{1L} L^{1in} / m^{2L} L^{2out}
        'L': {'in_road': 1, 'in_dir': 'in',  'out_road': 2, 'out_dir': 'out'},
    },
    'D': {
        # τ^R_D: j^{3in} β^{3R} L^{3in} / m^{2R} L^{2out}
        'R': {'in_road': 3, 'in_dir': 'in',  'out_road': 2, 'out_dir': 'out'},
        # τ^L_D: j^{5in} β^{5L} L^{5in} / m^{6L} L^{6out}
        'L': {'in_road': 5, 'in_dir': 'in',  'out_road': 6, 'out_dir': 'out'},
    },
}

# 後方互換
TURN_MAP = TURN_MAP_UP


# 直進ポテンシャルで差し引く回転項。
# J^{road+} は「その交差点へ road 方向から入ってくる有向辺」の定義。
# 同じ有向辺の J^{road-} は、到着点側の J^{road+} を参照して同じ値にする。
STRAIGHT_POTENTIAL_IN_TERMS = {
    # 流入辺共有の幾何＋参照バランス(s=3/3/3/3, σ=6/6, 各頂点1回)で確定。
    # D2/D3/E2/E4 の4行は原典スライドの転記ミスを修正済み。
    ('C', 1): (('s', 'u', '-', 0, 0), ('sigma', '+', 0, 0)),
    ('C', 4): (('s', 'd', '-', 0, 0), ('sigma', '+', 1, 0)),
    ('C', 3): (('s', 'd', '+', 0, 0), ('sigma', '-', 0, 0)),
    ('C', 6): (('s', 'u', '+', 0, 0), ('sigma', '-', 1, 0)),
    ('D', 2): (('s', 'u', '+', -1, 1), ('sigma', '-', 0, 0)),
    ('D', 5): (('s', 'd', '+', 0, 0), ('sigma', '-', 0, 1)),
    ('D', 3): (('s', 'u', '-', -1, 1), ('sigma', '+', 0, 1)),
    ('D', 6): (('s', 'd', '-', 0, 0), ('sigma', '+', 0, 0)),
    ('E', 1): (('s', 'd', '+', 0, 0), ('sigma', '-', 1, 0)),
    ('E', 4): (('s', 'u', '+', 0, 1), ('sigma', '-', 0, 1)),
    ('E', 2): (('s', 'd', '-', 0, 0), ('sigma', '+', 0, 1)),
    ('E', 5): (('s', 'u', '-', 0, 1), ('sigma', '+', 1, 0)),
}

OUTGOING_TARGET_OFFSETS = {
    ('C', 1): ('E', 0, 0),
    ('C', 3): ('D', 1, -1),
    ('C', 4): ('E', 0, -1),
    ('C', 6): ('D', 0, 0),
    ('D', 2): ('E', 0, 0),
    ('D', 3): ('C', 0, 0),
    ('D', 5): ('E', -1, 0),
    ('D', 6): ('C', -1, 1),
    ('E', 1): ('C', 0, 1),
    ('E', 2): ('D', 1, 0),
    ('E', 4): ('C', 0, 0),
    ('E', 5): ('D', 0, 0),
}


# ═══════════════════════════════════════════════════════════
#  Intersection クラス
# ═══════════════════════════════════════════════════════════

@dataclass
class Intersection:
    """交差点1つ分の全データを保持する。

    Attributes:
        node_type: 'C', 'D', 'E'
        i, j: 格子座標
        flows: {(road_num, 'in'/'out'): float}  交通量 J
        beta: {(road_num, 'R'/'L'/'S'): float}  分岐比 (右折/左折/直進)
        road_length: {(road_num, 'in'/'out'): float}  道路長 L
        lane_count: {(road_num, 'R'/'L'/'S'): int}    車線数 m
        source_flow: {road_num: float}  沿道から道路へ入る正規化交通量
        sink_flow: {road_num: float}    道路から沿道へ出る正規化交通量
        net_source: {road_num: float}   正味のソース q (= source - sink)
        norm_lanes: {(road_num, 'in'/'out'): float}
            J = (count/duration)/lanes の分母に使った車線数。
            節点収支を「台数」で書き戻すのに要る（J×lanes で台数に戻る）。
            lane_count は右折/左折/直進レーンの内訳なので用途が別。
            未設定の道路は lane_R+lane_L+lane_S で代用する。

        source_flow/sink_flow にキーが無い道路は「未調査」を表す。
        0.0 が格納されている道路は「調査済み・出入りなし」を表す。
    """
    node_type: str
    i: int
    j: int
    flows: Dict[Tuple[int, str], float] = field(default_factory=dict)
    beta: Dict[Tuple[int, str], float] = field(default_factory=dict)
    road_length: Dict[Tuple[int, str], float] = field(default_factory=dict)
    lane_count: Dict[Tuple[int, str], int] = field(default_factory=dict)
    source_flow: Dict[int, float] = field(default_factory=dict)
    sink_flow: Dict[int, float] = field(default_factory=dict)
    net_source: Dict[int, float] = field(default_factory=dict)
    norm_lanes: Dict[Tuple[int, str], float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.node_type}_{{{self.i},{self.j}}}"

    @property
    def connected_roads(self) -> List[int]:
        return CONNECTED_ROADS[self.node_type]

    def get_flow(self, road: int, direction: str) -> float:
        """交通量 J を取得"""
        return self.flows.get((road, direction), 0.0)

    def get_beta(self, road: int, turn: str) -> float:
        """分岐比 β を取得"""
        return self.beta.get((road, turn), 0.0)

    def get_road_length(self, road: int, direction: str) -> float:
        """道路長 L を取得"""
        return self.road_length.get((road, direction), 1.0)

    def get_lane_count(self, road: int, turn: str) -> int:
        """車線数 m を取得"""
        return self.lane_count.get((road, turn), 1)

    def get_norm_lanes(self, road: int, direction: str) -> float:
        """正規化に使った車線数。J×これ で台数[台/時]に戻る。

        未設定なら右折+左折+直進レーンの和で代用する（reader の既定と同じ）。
        """
        v = self.norm_lanes.get((road, direction))
        if v is not None and v > 0:
            return float(v)
        total = (self.lane_count.get((road, 'R'), 0)
                 + self.lane_count.get((road, 'L'), 0)
                 + self.lane_count.get((road, 'S'), 0))
        return float(total) if total > 0 else 1.0

    def get_source_flow(self, road: int):
        """実測ソースを取得。未調査なら None、実測ゼロなら 0.0。"""
        return self.source_flow.get(road)

    def get_sink_flow(self, road: int):
        """実測シンクを取得。未調査なら None、実測ゼロなら 0.0。"""
        return self.sink_flow.get(road)

    def get_net_source(self, road: int):
        """正味のソース q を取得。未調査なら None。"""
        return self.net_source.get(road)

    # ─── Phase 3: 局所回転成分 τ ─────────────────────
    def calc_tau(self, turn: str, tri_type: str = 'up') -> float:
        """局所回転成分 τ を計算する。

        τ = (J × β × L) / (m × L)
        ※ 道路番号と流れ方向(in/out)は三角形タイプにより異なる

        Args:
            turn: 'R' (右折/時計回り) or 'L' (左折/反時計回り)
            tri_type: 'up' (上向き三角形) or 'down' (下向き三角形)
        """
        turn_map = TURN_MAP_UP if tri_type == 'up' else TURN_MAP_DOWN
        return self.calc_tau_with_map(turn_map, turn)

    def calc_tau_with_map(self, turn_map: dict, turn: str) -> float:
        """任意のturn_mapでτを計算する（σ計算用）。

        Args:
            turn_map: TURN_MAP_UP, TURN_MAP_DOWN, TURN_MAP_HEX_* 等
            turn: 'R' or 'L'
        """
        mapping = turn_map[self.node_type][turn]
        in_road = mapping['in_road']
        in_dir = mapping['in_dir']
        out_road = mapping['out_road']
        out_dir = mapping['out_dir']

        j_val = self.get_flow(in_road, in_dir)
        beta_val = self.get_beta(in_road, turn)
        L_in = self.get_road_length(in_road, in_dir)
        m_out = self.get_lane_count(out_road, turn)
        L_out = self.get_road_length(out_road, out_dir)

        if m_out * L_out == 0:
            return 0.0
        return (j_val * beta_val * L_in) / (m_out * L_out)

    def total_inflow(self) -> float:
        """総流入量"""
        return sum(v for (r, d), v in self.flows.items() if d == 'in')

    def total_outflow(self) -> float:
        """総流出量"""
        return sum(v for (r, d), v in self.flows.items() if d == 'out')


# ═══════════════════════════════════════════════════════════
#  UnitCell クラス
# ═══════════════════════════════════════════════════════════

@dataclass
class UnitCell:
    """カゴメ格子の単位格子 (C, D, E の3交差点)"""
    i: int
    j: int
    C: Intersection = field(default=None)
    D: Intersection = field(default=None)
    E: Intersection = field(default=None)
    lattice: Optional[object] = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self.C is None:
            self.C = Intersection('C', self.i, self.j)
        if self.D is None:
            self.D = Intersection('D', self.i, self.j)
        if self.E is None:
            self.E = Intersection('E', self.i, self.j)

    @property
    def intersections(self) -> List[Intersection]:
        return [self.C, self.D, self.E]

    # ─── Phase 3: 三角形の回転作用 s ─────────────────

    def calc_s_up_plus(self) -> float:
        """上向き三角形の右回り回転作用 s^{u+}

        s^{u+}_{i,j} = τ^R_{C_{i,j}} + τ^R_{E_{i,j-1}} + τ^R_{D_{i+1,j-1}}
        ※ TURN_MAP_UP を使用
        """
        if self.lattice is None:
            raise ValueError(
                "calc_s_up_plus requires KagomeLattice because s_u uses "
                "neighboring cells"
            )
        return self.lattice.calc_s_up_plus(self.i, self.j)

    def calc_s_up_minus(self) -> float:
        """上向き三角形の左回り回転作用 s^{u-}

        s^{u-}_{i,j} = τ^L_{C_{i,j}} + τ^L_{E_{i,j-1}} + τ^L_{D_{i+1,j-1}}
        ※ TURN_MAP_UP を使用
        """
        if self.lattice is None:
            raise ValueError(
                "calc_s_up_minus requires KagomeLattice because s_u uses "
                "neighboring cells"
            )
        return self.lattice.calc_s_up_minus(self.i, self.j)

    def calc_s_down_plus(self) -> float:
        """下向き三角形の右回り回転作用 s^{d+}

        s^{d+}_{i,j} = τ^R_{C_{i,j}} + τ^R_{E_{i,j}} + τ^R_{D_{i,j}}
        ※ TURN_MAP_DOWN を使用
        """
        return (self.C.calc_tau('R', 'down')
                + self.E.calc_tau('R', 'down')
                + self.D.calc_tau('R', 'down'))

    def calc_s_down_minus(self) -> float:
        """下向き三角形の左回り回転作用 s^{d-}

        s^{d-}_{i,j} = τ^L_{C_{i,j}} + τ^L_{E_{i,j}} + τ^L_{D_{i,j}}
        ※ TURN_MAP_DOWN を使用
        """
        return (self.C.calc_tau('L', 'down')
                + self.E.calc_tau('L', 'down')
                + self.D.calc_tau('L', 'down'))


# ═══════════════════════════════════════════════════════════
#  KagomeLattice クラス
# ═══════════════════════════════════════════════════════════

class KagomeLattice:
    """カゴメ格子全体を管理するクラス"""

    def __init__(self, rows: int = 1, cols: int = 1):
        self.rows = rows
        self.cols = cols
        self.cells: Dict[Tuple[int, int], UnitCell] = {}
        # 値を実測せず推定で埋めた有向道路 {(node_type, i, j, road), ...}。
        # 入力CSVの任意列 estimated=1 で立つ。判定の揺れを見積もるのに使う。
        self.estimated_edges = set()
        self._build_lattice()

    def _build_lattice(self):
        """格子を構築

        メイングリッド (i=0..cols-1, j=0..rows-1) に加え、
        上向き三角形・六角形の計算に必要な境界セルを作成する。

        C_{i,j} の上向き三角形は E_{i,j-1} と D_{i+1,j-1} を参照するため、
        j=-1 の行を境界セルとして追加する。
        """
        # メイングリッド
        for j in range(self.rows):
            for i in range(self.cols):
                self.cells[(i, j)] = UnitCell(i, j, lattice=self)

        # 境界セル: j=-1 行
        # C_{i,0} の上向き三角形に E_{i,-1}, D_{i+1,-1} が必要
        for i in range(self.cols + 1):
            self.cells[(i, -1)] = UnitCell(i, -1, lattice=self)

    def get_cell(self, i: int, j: int) -> Optional[UnitCell]:
        return self.cells.get((i, j))

    def get_intersection(self, node_type: str, i: int, j: int) -> Optional[Intersection]:
        """特定の交差点を取得"""
        cell = self.get_cell(i, j)
        if cell is None:
            return None
        return getattr(cell, node_type, None)

    @property
    def all_intersections(self) -> List[Intersection]:
        """全交差点のリスト（境界セル含む）"""
        result = []
        for cell in self.cells.values():
            result.extend(cell.intersections)
        return result

    @property
    def all_cells(self) -> List[UnitCell]:
        """全セルのリスト（境界セル含む）"""
        return list(self.cells.values())

    @property
    def main_cells(self) -> List[UnitCell]:
        """メイングリッドのセルのみ（境界セルを除く）"""
        return [cell for (i, j), cell in self.cells.items()
                if 0 <= i < self.cols and 0 <= j < self.rows]

    @property
    def main_intersections(self) -> List[Intersection]:
        """メイングリッドの交差点のみ（境界セルを除く）"""
        result = []
        for cell in self.main_cells:
            result.extend(cell.intersections)
        return result

    # ─── 座標計算 ─────────────────────────────────

    @staticmethod
    def calc_position(node_type: str, i: int, j: int, scale: float = 2.0):
        """交差点の2D描画座標を計算する。

        draw_lattice.pos と同じ座標系:
          i: 行方向、j: 列方向
          C_{i,j} = (2j + i,       i * √3) * scale
          E_{i,j} = (2j + i + 1,   i * √3) * scale
          D_{i,j} = (2j + i + 0.5, i * √3 - √3/2) * scale
        """
        sqrt3 = math.sqrt(3)
        base_x = (2 * j + i) * scale
        base_y = i * sqrt3 * scale

        if node_type == 'C':
            return (base_x, base_y)
        elif node_type == 'E':
            return (base_x + scale, base_y)
        elif node_type == 'D':
            return (base_x + scale / 2, base_y - sqrt3 * scale / 2)
        else:
            raise ValueError(f"Unknown node type: {node_type}")

    def _calc_s_up(self, i: int, j: int, turn: str) -> float:
        nodes = [
            self.get_intersection('C', i, j),
            self.get_intersection('E', i, j - 1),
            self.get_intersection('D', i + 1, j - 1),
        ]
        if any(node is None for node in nodes):
            return 0.0
        return sum(node.calc_tau_with_map(TURN_MAP_UP, turn) for node in nodes)

    def calc_s_up_plus(self, i: int, j: int) -> float:
        """上向き三角形の右回り回転作用 s^{u+}_{i,j}"""
        return self._calc_s_up(i, j, 'R')

    def calc_s_up_minus(self, i: int, j: int) -> float:
        """上向き三角形の左回り回転作用 s^{u-}_{i,j}"""
        return self._calc_s_up(i, j, 'L')

    def calc_s_down_plus(self, i: int, j: int) -> float:
        """下向き三角形の右回り回転作用 s^{d+}_{i,j}"""
        cell = self.get_cell(i, j)
        if cell is None:
            return 0.0
        return cell.calc_s_down_plus()

    def calc_s_down_minus(self, i: int, j: int) -> float:
        """下向き三角形の左回り回転作用 s^{d-}_{i,j}"""
        cell = self.get_cell(i, j)
        if cell is None:
            return 0.0
        return cell.calc_s_down_minus()

    # ─── Phase 3: 六角形回転作用 σ ────────────────
    #  画像3: σ^+_{i,j} = τ^R(上半分3頂点) + τ^R(下半分3頂点)
    #         σ^-_{i,j} = τ^L(上半分3頂点) + τ^L(下半分3頂点)
    #  上半分: C_{i,j}, E_{i,j-1}, D_{i,j}       ← TURN_MAP_HEX_UPPER
    #  下半分: C_{i-1,j}, E_{i-1,j}, D_{i,j-1}   ← TURN_MAP_HEX_LOWER

    def _calc_sigma_half(self, i: int, j: int, turn: str) -> float:
        """σ計算の共通ロジック（上半分 + 下半分）

        Args:
            i, j: 六角形の位置
            turn: 'R' (σ⁺) or 'L' (σ⁻)
        """
        total = 0.0
        # 上半分: C_{i,j}, E_{i,j-1}, D_{i,j}
        nodes_upper = [
            self.get_intersection('C', i, j),
            self.get_intersection('E', i, j - 1),
            self.get_intersection('D', i, j),
        ]
        for node in nodes_upper:
            if node is not None:
                total += node.calc_tau_with_map(TURN_MAP_HEX_UPPER, turn)

        # 下半分: C_{i-1,j}, E_{i-1,j}, D_{i,j-1}
        nodes_lower = [
            self.get_intersection('C', i - 1, j),
            self.get_intersection('E', i - 1, j),
            self.get_intersection('D', i, j - 1),
        ]
        for node in nodes_lower:
            if node is not None:
                total += node.calc_tau_with_map(TURN_MAP_HEX_LOWER, turn)

        return total

    def calc_sigma_plus(self, i: int, j: int) -> float:
        """六角形の右回り回転作用 σ^{+}_{i,j}

        σ^+ = τ^R_{C_{i,j}} + τ^R_{E_{i,j-1}} + τ^R_{D_{i,j}}
             + τ^R_{C_{i-1,j}} + τ^R_{E_{i-1,j}} + τ^R_{D_{i,j-1}}
        """
        return self._calc_sigma_half(i, j, 'R')

    def calc_sigma_minus(self, i: int, j: int) -> float:
        """六角形の左回り回転作用 σ^{-}_{i,j}

        σ^- = τ^L_{C_{i,j}} + τ^L_{E_{i,j-1}} + τ^L_{D_{i,j}}
             + τ^L_{C_{i-1,j}} + τ^L_{E_{i-1,j}} + τ^L_{D_{i,j-1}}
        """
        return self._calc_sigma_half(i, j, 'L')

    # ─── Phase 4: 直進ポテンシャル J⁺, J⁻ ───────

    def _calc_s_by_ref(self, orientation: str, sign: str,
                       i: int, j: int) -> float:
        if orientation == 'u' and sign == '+':
            return self.calc_s_up_plus(i, j)
        if orientation == 'u' and sign == '-':
            return self.calc_s_up_minus(i, j)
        if orientation == 'd' and sign == '+':
            return self.calc_s_down_plus(i, j)
        if orientation == 'd' and sign == '-':
            return self.calc_s_down_minus(i, j)
        return 0.0

    def _calc_sigma_by_ref(self, sign: str, i: int, j: int) -> float:
        if sign == '+':
            return self.calc_sigma_plus(i, j)
        if sign == '-':
            return self.calc_sigma_minus(i, j)
        return 0.0

    def _calc_rotation_term(self, ref, i: int, j: int) -> float:
        kind = ref[0]
        if kind == 's':
            _, orientation, sign, di, dj = ref
            return self._calc_s_by_ref(orientation, sign, i + di, j + dj)
        if kind == 'sigma':
            _, sign, di, dj = ref
            return self._calc_sigma_by_ref(sign, i + di, j + dj)
        return 0.0

    def get_outgoing_target(self, node_type: str, i: int, j: int,
                            road: int) -> Optional[Tuple[str, int, int]]:
        """node_type(i,j) から road 方向へ出る有向辺の到着交差点を返す（公開API）。"""
        return self._outgoing_target(node_type, i, j, road)

    def _outgoing_target(self, node_type: str, i: int, j: int,
                         road: int) -> Optional[Tuple[str, int, int]]:
        """node_type(i,j) から road 方向へ出る有向辺の到着交差点を返す。"""
        target = OUTGOING_TARGET_OFFSETS.get((node_type, road))
        if target is None:
            return None
        target_type, di, dj = target
        target_i = i + di
        target_j = j + dj
        if self.get_intersection(target_type, target_i, target_j) is None:
            return None
        return (target_type, target_i, target_j)

    def _calc_in_potential(self, node_type: str, i: int, j: int,
                           road: int) -> float:
        node = self.get_intersection(node_type, i, j)
        refs = STRAIGHT_POTENTIAL_IN_TERMS.get((node_type, road))
        if node is None or refs is None:
            return 0.0

        s_term = self._calc_rotation_term(refs[0], i, j)
        sigma_term = self._calc_rotation_term(refs[1], i, j)
        return node.get_flow(road, 'in') - s_term / 3 - sigma_term / 6

    def calc_straight_potential(self, node_type: str, i: int, j: int,
                                 road: int) -> Tuple[float, float]:
        """直進ポテンシャル J⁺ と J⁻ を計算する。

        J⁺ はその交差点へ入ってくる有向辺の値として計算する。
        J⁻ は出ていく有向辺の到着点を求め、その到着点側の J⁺ と同じ値を返す。
        これにより、同じ有向辺の A road out と B road in は必ず一致する。

        Returns:
            (J_plus, J_minus)
        """
        node = self.get_intersection(node_type, i, j)
        if node is None or (node_type, road) not in STRAIGHT_POTENTIAL_IN_TERMS:
            return (0.0, 0.0)

        J_plus = self._calc_in_potential(node_type, i, j, road)
        target = self._outgoing_target(node_type, i, j, road)
        if target is None:
            J_minus = 0.0
        else:
            target_type, target_i, target_j = target
            J_minus = self._calc_in_potential(target_type, target_i, target_j, road)

        return (J_plus, J_minus)


# ═══════════════════════════════════════════════════════════
#  ダミーデータ生成
# ═══════════════════════════════════════════════════════════

def _assign_bond_flow(rng, nodeA, nodeB, road_fwd, road_rev):
    """ボンド(辺)に対して正規化交通量 J を計算し、両端に同一値を設定する。

    J = n * v / (L * m)
      n: 交通量（台数）
      v: 速度
      L: 道路長
      m: 車線数

    road_fwd: A→B方向の道路番号
    road_rev: B→A方向の道路番号

    制約: nodeA.flows[(road_fwd, 'out')] == nodeB.flows[(road_fwd, 'in')]
          nodeB.flows[(road_rev, 'out')] == nodeA.flows[(road_rev, 'in')]
    """
    # A→B方向 (road_fwd): nodeAのout, nodeBのin
    n_fwd = rng.randint(30, 150)   # 台数（整数）
    v_fwd = rng.uniform(20, 60)    # 速度 (km/h)
    L_fwd = nodeA.get_road_length(road_fwd, 'out')
    m_fwd = nodeA.get_lane_count(road_fwd, 'S')  # 代表車線数として直進を使用
    flow_fwd = (n_fwd * v_fwd) / (L_fwd * m_fwd) if (L_fwd * m_fwd) > 0 else 0.0
    nodeA.flows[(road_fwd, 'out')] = flow_fwd
    nodeB.flows[(road_fwd, 'in')] = flow_fwd

    # B→A方向 (road_rev): nodeBのout, nodeAのin
    n_rev = rng.randint(30, 150)
    v_rev = rng.uniform(20, 60)
    L_rev = nodeB.get_road_length(road_rev, 'out')
    m_rev = nodeB.get_lane_count(road_rev, 'S')
    flow_rev = (n_rev * v_rev) / (L_rev * m_rev) if (L_rev * m_rev) > 0 else 0.0
    nodeB.flows[(road_rev, 'out')] = flow_rev
    nodeA.flows[(road_rev, 'in')] = flow_rev


def generate_dummy_data(lattice: KagomeLattice, seed: int = 42):
    """全交差点にダミーの交通データを設定する。

    交通量はボンド(辺)単位で生成し、同一道路の両端で
    j^{1out}_{C_{i,j}} = j^{1in}_{E_{i,j}} 等の整合性を保証する。

    - 交通量 J: 50〜200
    - 分岐比 β: R + L + S = 1.0 (直進率 ≥ 0.4)
    - 道路長 L: 0.5〜2.0
    - 車線数 m: 1〜3
    """
    rng = random.Random(seed)

    # ── β, L, m はノード単位で生成 ──
    for node in lattice.all_intersections:
        for road in node.connected_roads:
            # 分岐比 (直進率 ≥ 40%)
            straight = rng.uniform(0.4, 0.7)
            right = rng.uniform(0.05, (1 - straight) * 0.7)
            left = 1.0 - straight - right
            node.beta[(road, 'R')] = right
            node.beta[(road, 'L')] = left
            node.beta[(road, 'S')] = straight

            # 道路長
            L = rng.uniform(0.5, 2.0)
            node.road_length[(road, 'in')] = L
            node.road_length[(road, 'out')] = L

            # 車線数
            m = rng.randint(1, 3)
            node.lane_count[(road, 'R')] = m
            node.lane_count[(road, 'L')] = m
            node.lane_count[(road, 'S')] = m

    # ── 交通量はボンド(辺)単位で生成 ──
    # セル内ボンド: 全セル(境界含む)
    for cell in lattice.all_cells:
        # C↔E: road 1 (C→E), road 4 (E→C)
        _assign_bond_flow(rng, cell.C, cell.E, 1, 4)
        # C↔D: road 6 (C→D), road 3 (D→C)
        _assign_bond_flow(rng, cell.C, cell.D, 6, 3)
        # E↔D: road 5 (E→D), road 2 (D→E)
        _assign_bond_flow(rng, cell.E, cell.D, 5, 2)

    # セル間ボンド
    for (ci, cj), cell in lattice.cells.items():
        # E_{i,j} — C_{i,j+1} (隣列): road 1 (E→C), road 4 (C→E)
        next_cell = lattice.get_cell(ci, cj + 1)
        if next_cell:
            _assign_bond_flow(rng, cell.E, next_cell.C, 1, 4)
        # C_{i,j} — D_{i+1,j-1} (斜め): road 3 (C→D), road 6 (D→C)
        diag_cell = lattice.get_cell(ci + 1, cj - 1)
        if diag_cell:
            _assign_bond_flow(rng, cell.C, diag_cell.D, 3, 6)
        # E_{i,j} — D_{i+1,j} (上): road 2 (E→D), road 5 (D→E)
        up_cell = lattice.get_cell(ci + 1, cj)
        if up_cell:
            _assign_bond_flow(rng, cell.E, up_cell.D, 2, 5)


# ═══════════════════════════════════════════════════════════
#  CSV / JSON 入出力
# ═══════════════════════════════════════════════════════════

def export_to_json(lattice: KagomeLattice, filepath: str):
    """格子データをJSONファイルに出力する"""
    data = {'cells': []}

    for (ci, cj), cell in sorted(lattice.cells.items()):
        cell_data = {'i': ci, 'j': cj, 'intersections': []}

        for node in cell.intersections:
            node_data = {
                'type': node.node_type,
                'i': node.i, 'j': node.j,
                'flows': {f"{r}_{d}": round(v, 2)
                          for (r, d), v in sorted(node.flows.items())},
                'beta': {f"{r}_{t}": round(v, 4)
                         for (r, t), v in sorted(node.beta.items())},
                'road_length': {f"{r}_{d}": round(v, 3)
                                for (r, d), v in sorted(node.road_length.items())},
                'lane_count': {f"{r}_{t}": v
                               for (r, t), v in sorted(node.lane_count.items())},
            }
            cell_data['intersections'].append(node_data)

        data['cells'].append(cell_data)

    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported: {filepath}")


def import_from_json(filepath: str) -> KagomeLattice:
    """JSONファイルから格子データを読み込む"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # グリッドサイズを推定
    max_i = max(c['i'] for c in data['cells']) + 1
    max_j = max(c['j'] for c in data['cells']) + 1
    lattice = KagomeLattice(rows=max_j, cols=max_i)

    for cell_data in data['cells']:
        ci, cj = cell_data['i'], cell_data['j']
        cell = lattice.get_cell(ci, cj)
        if cell is None:
            continue

        for node_data in cell_data['intersections']:
            node = getattr(cell, node_data['type'])

            for key, val in node_data['flows'].items():
                r, d = key.split('_')
                node.flows[(int(r), d)] = val

            for key, val in node_data['beta'].items():
                r, t = key.split('_')
                node.beta[(int(r), t)] = val

            for key, val in node_data['road_length'].items():
                r, d = key.split('_')
                node.road_length[(int(r), d)] = val

            for key, val in node_data['lane_count'].items():
                r, t = key.split('_')
                node.lane_count[(int(r), t)] = val

    return lattice


def row_turn_node(lattice: KagomeLattice, node_type: str, i: int, j: int,
                  road: int) -> Optional[Intersection]:
    """入力の1行（node から road 方向へ出る有向道路）の右左折率を持つ交差点。

    ★ 行の右左折率は「その行で数えた車が、道路の先の交差点で曲がる割合」。
      現地では交差点の流入方向ごとに「通過・右折・左折」を数えるので、
      1つの観測（ある道路を来た車の台数と、その車の曲がり方）が1行に収まる。

      一方モデルの β は交差点側に置き、`node.beta[(road, turn)]` は
      「road 方向から node へ**到着した**車の右左折率」を表す（τ と M がこれを使う）。

      したがって行 (S, road) の β は、その道路の到着点 T の `T.beta[(road, ·)]` に入る。
      出発点 S に入れると、1つ上流の別の道路の車に当たってしまう
      （2026-10 に修正。それまで入力画面・調査仕様の意味と1交差点ずれていた）。

    格子の外へ出る行は到着点が無いので None（その β は解析に使われない）。
    """
    tgt = lattice.get_outgoing_target(node_type, i, j, road)
    if tgt is None:
        return None
    return lattice.get_intersection(*tgt)


def export_flows_csv(lattice: KagomeLattice, filepath: str):
    """交通量のみをCSV出力（可視化用）"""
    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['node_type', 'i', 'j', 'road', 'direction', 'flow',
                          'beta_R', 'beta_L', 'beta_S'])
        for node in lattice.all_intersections:
            for road in node.connected_roads:
                for direction in ['in', 'out']:
                    flow = node.get_flow(road, direction)
                    # 行の β は「その行の車が道路の先で曲がる割合」。
                    # in 行は node に着く車なので node の β、
                    # out 行は道路の到着点の β（row_turn_node 参照）。
                    bnode = node if direction == 'in' else row_turn_node(
                        lattice, node.node_type, node.i, node.j, road)
                    if bnode is None:
                        bnode = node   # 格子の外へ出る行。解析には使われない
                    bR = bnode.get_beta(road, 'R')
                    bL = bnode.get_beta(road, 'L')
                    bS = bnode.get_beta(road, 'S')
                    writer.writerow([
                        node.node_type, node.i, node.j,
                        road, direction, f"{flow:.2f}",
                        f"{bR:.4f}", f"{bL:.4f}", f"{bS:.4f}"
                    ])
    print(f"Exported: {filepath}")


# ═══════════════════════════════════════════════════════════
#  メイン（モジュール単体テスト）
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 60)
    print("  カゴメ格子 交通流モデル — 単体テスト")
    print("=" * 60)

    # Phase 1: 格子生成 + ダミーデータ
    lattice = KagomeLattice(rows=2, cols=2)
    generate_dummy_data(lattice)

    print(f"\n格子サイズ: {lattice.cols}×{lattice.rows}")
    print(f"UnitCell数: {len(lattice.cells)}")
    print(f"交差点総数: {len(lattice.all_intersections)}")

    # β の整合性チェック
    print("\n--- β 整合性チェック ---")
    all_ok = True
    for node in lattice.all_intersections:
        for road in node.connected_roads:
            total_beta = (node.get_beta(road, 'R')
                          + node.get_beta(road, 'L')
                          + node.get_beta(road, 'S'))
            if abs(total_beta - 1.0) > 1e-6:
                print(f"  ⚠ {node.label} road {road}: β合計={total_beta:.6f}")
                all_ok = False
    if all_ok:
        print("  ✓ 全交差点・全道路で β^R + β^L + β^S = 1.0 を確認")

    # Phase 3: 回転作用 τ, s
    print("\n--- 回転作用の計算 (Phase 3) ---")
    cell_00 = lattice.get_cell(0, 0)
    for node in cell_00.intersections:
        tau_R = node.calc_tau('R')
        tau_L = node.calc_tau('L')
        print(f"  {node.label}: τ^R = {tau_R:.4f},  τ^L = {tau_L:.4f}")

    s_up = lattice.calc_s_up_plus(0, 0)
    s_um = lattice.calc_s_up_minus(0, 0)
    print(f"  s^{{u+}} = {s_up:.4f}")
    print(f"  s^{{u-}} = {s_um:.4f}")

    sigma_p = lattice.calc_sigma_plus(0, 0)
    sigma_m = lattice.calc_sigma_minus(0, 0)
    print(f"  σ^{{+}} = {sigma_p:.4f}")
    print(f"  σ^{{-}} = {sigma_m:.4f}")

    # Phase 4: 直進ポテンシャル
    print("\n--- 直進ポテンシャル (Phase 4) ---")
    for node in cell_00.intersections:
        for road in node.connected_roads[:2]:  # 最初の2道路
            Jp, Jm = lattice.calc_straight_potential(
                node.node_type, node.i, node.j, road)
            J_in = node.get_flow(road, 'in')
            J_out = node.get_flow(road, 'out')
            print(f"  {node.label} road {road}: "
                  f"J_in={J_in:.1f} → J⁺={Jp:.2f}, "
                  f"J_out={J_out:.1f} → J⁻={Jm:.2f}")

    # ファイル出力
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    data_dir = os.path.join(project_dir, 'data')

    export_to_json(lattice, os.path.join(data_dir, 'lattice_data.json'))
    export_flows_csv(lattice, os.path.join(data_dir, 'flows.csv'))

    print("\n✓ Phase 1-4 コアモデル テスト完了")
