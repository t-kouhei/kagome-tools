"""定常輸送の出口到達性と、計算失敗の診断。"""
from collections import deque
import math
from . import _engine as E


class SteadyFlowError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.details = details or {}


def _reachable(starts, adjacency):
    seen = set(starts)
    queue = deque(seen)
    while queue:
        for target in adjacency[queue.popleft()]:
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def diagnose_steady(m, inflow=None):
    """流量の大きさと独立に、正の分岐で出口へ到達できるかを調べる。

    正の分岐は小さくても切り捨てない。閉じた部分への流入がなくても、
    その内部の循環量は入口条件だけでは一意に決まらない。
    """
    forward = {e: [] for e in m.edges}
    reverse = {e: [] for e in m.edges}
    exits = set()
    for edge in m.edges:
        node, road = m.target(edge), edge[3]
        for turn in ("S", "R", "L"):
            if m.beta(node, road, turn) <= 0:
                continue
            target = m.out_edge(node, road, turn)
            if target is None:
                exits.add(edge)
            else:
                forward[edge].append(target)
                reverse[target].append(edge)
    can_exit = _reachable(exits, reverse)
    trapped = set(m.edges) - can_exit
    starts = set()
    for entrance, value in (inflow or {}).items():
        if value <= 0:
            continue
        for turn in ("S", "R", "L"):
            if m.beta(entrance[:3], entrance[3], turn) > 0:
                target = m.out_edge(entrance[:3], entrance[3], turn)
                if target is not None:
                    starts.add(target)
    fed = trapped & _reachable(starts, forward)
    conservative = all(abs(sum(b.values()) - 1) <= 1e-9 and min(b.values()) >= 0
                       for b in m.branching.values())
    if trapped:
        code = "trapped_inflow" if fed and conservative else "nonunique_circulation"
        if not conservative:
            code = "invalid_routing"
    else:
        code = "ok"
    return {"code": code, "all_edges_reach_exit": not trapped,
            "unreachable_edges": sorted(trapped), "fed_unreachable_edges": sorted(fed),
            "conservative_routing": conservative}


def require_unique_steady(m, inflow):
    for entrance, value in inflow.items():
        if entrance not in m.entrances or not math.isfinite(value) or value < 0:
            raise SteadyFlowError("invalid_inflow", "入口の場所と流入量を確認してください。流入量は有限の非負数が必要です。")
    for node in m.nodes:
        for road in E.CONNECTED_ROADS[node[0]]:
            b = m.branching.get((*node, road))
            if b is None or any(not math.isfinite(v) or v < -1e-12 for v in b.values()) or abs(sum(b.values()) - 1) > 1e-9:
                raise SteadyFlowError("invalid_routing", f"{node}の流入方向{road}：分岐割合は有限の非負数で、合計1が必要です。丸めた値を補正せず計算するため、合計を確認してください。")
    diagnostic = diagnose_steady(m, inflow)
    if diagnostic["code"] == "ok":
        return diagnostic
    edges = diagnostic["unreachable_edges"]
    examples = ", ".join(f"{e[0]}({e[1]},{e[2]})-{e[3]}" for e in edges[:8])
    reasons = {
        "trapped_inflow": "入口からの流れが出口へ抜けられない部分に入ります。蓄積するため有限の定常流を求められません。",
        "nonunique_circulation": "出口へ抜けられない部分があります。流入がなくても内部の循環量が一意に決まりません。",
        "invalid_routing": "出口へ抜けられない部分があり、分岐割合も保存的な条件を満たしていません。",
    }
    raise SteadyFlowError(diagnostic["code"], reasons[diagnostic["code"]] +
                         f" 対象 {len(edges)} 本：{examples}。分岐割合と出口への接続を確認してください。", diagnostic)
