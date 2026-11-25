# -*- coding: utf-8 -*-
"""入力の検査。エラーにならずに間違った答えだけが出る入力を、計算の前に止める。

分野に依存しない検査だけを置く（既存ツールの受け入れ検査のうち、交通に依存しない部分）。
戻り値は (重さ, 場所, 内容) の並び。重さは "error"（計算できない）と "warning"（計算はできるが疑わしい）。
"""
import statistics
import math

from .model import KagomeModel, TURNS

TOL = 1e-6


def check(m: KagomeModel, need=("m", "L"), mode="observe", norm="m", inflow=None):
    """need: 必ず要る素辺の値。mode="observe" なら流量 V も要り、交差点の出入りの釣り合いを見る。"""
    out = []
    need = list(need) + (["V"] if mode == "observe" else []) + (["v"] if norm in ("mvl", "k") else [])
    # 素辺の値
    for e in m.edges:
        ev = m.values[e]
        for k in ("m", "L", "v", "V", "T", "mu"):
            x = getattr(ev, k)
            if x is not None and not math.isfinite(x):
                out.append(("error", e, f"{k} は有限の数値が必要（{x}）"))
        for k in need:
            x = getattr(ev, k)
            if x is None:
                out.append(("error", e, f"{k} が未入力"))
            elif k in ("m", "L", "v") and x <= 0:
                out.append(("error", e, f"{k} は正の値（{x}）"))
            elif k == "V" and x < 0:
                out.append(("error", e, f"流量が負（{x}）"))
        if ev.T is not None and ev.T <= 0:
            out.append(("error", e, f"温度 T は正の値（{ev.T}）"))
    # 分岐の割合
    for node in m.nodes:
        for r in _in_roads(node):
            b = m.branching.get((*node, r))
            if b is None:
                if m.upstream(node, r) is not None or (*node, r) in m.entrances:
                    out.append(("error", (*node, r), "分岐の割合が未入力"))
                continue
            if any(not math.isfinite(b[t]) for t in TURNS):
                out.append(("error", (*node, r), "分岐の割合は有限の数値が必要"))
                continue
            if any(b[t] < -TOL for t in TURNS):
                out.append(("error", (*node, r), f"分岐の割合が負 {b}"))
            s = sum(b.values())
            if abs(s - 1.0) > 1e-3:
                out.append(("error", (*node, r), f"分岐の割合の合計が 1 でない（{s:.4f}）"))
    for entrance, value in (inflow or {}).items():
        if entrance not in m.entrances:
            out.append(("error", entrance, "格子の入口ではない"))
        if not math.isfinite(value) or value < 0:
            out.append(("error", entrance, "入口の流入量は有限の非負数が必要"))
    # 長さの桁（m と km の混在など）：中央値から 100 倍以上離れた値
    for k in ("L", "m", "v"):
        xs = [getattr(m.values[e], k) for e in m.edges
              if getattr(m.values[e], k) and math.isfinite(getattr(m.values[e], k))]
        if len(xs) >= 5:
            med = statistics.median(xs)
            for e in m.edges:
                x = getattr(m.values[e], k)
                if x and math.isfinite(x) and med > 0 and (x / med >= 100 or med / x >= 100):
                    out.append(("warning", e, f"{k} の桁が他と大きく違う（{x}、中央値 {med}）。単位の混在を確認"))
    # 交差点の出入りの釣り合い（観測モード。格子の内側の交差点だけ）
    if mode == "observe" and not any(s == "error" for s, _, _ in out):
        for node in m.nodes:
            ins = [m.upstream(node, r) for r in _in_roads(node)]
            outs = [(*node, r) for r in _in_roads(node)]
            if any(e is None for e in ins) or any(e not in m.index for e in outs):
                continue
            a = sum(m.values[e].V for e in ins)
            b = sum(m.values[e].V for e in outs)
            if max(a, b) > 0 and abs(a - b) / max(a, b) > 0.10:
                out.append(("warning", node, f"入る量 {a:.1f} と出る量 {b:.1f} が 10% 以上ずれている"))
    return out


def _in_roads(node):
    from . import _engine as E
    return E.CONNECTED_ROADS[node[0]]
