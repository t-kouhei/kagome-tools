"""標準との比較を、解析範囲と数え方を明示して出す。"""
import math


DIRECTION_NOTE = (
    "innerは両端が解析範囲内にある素辺、allは余白を含む全素辺。"
    "現況と標準を同じ素辺で足す。直列に通る素辺もそれぞれ数える。"
    "方向の合計が標準以下でも、個々の素辺では臨界量を超える場合がある。"
    "超過本数はV > c×(1+1e-6)+1e-9で数える。"
)


def direction_comparison(m, V, standard):
    """素辺の流量和・臨界量和と、相殺せずに数えた局所の超過。"""
    result = {}
    for scope, edges in (("inner", m.inner_edges), ("all", m.edges)):
        result[scope] = {}
        for d in range(1, 7):
            es = [e for e in edges if e[3] == d]
            now = math.fsum(V[e] for e in es)
            ref = math.fsum(standard[e] for e in es)
            over = [e for e in es if V[e] > standard[e] * (1 + 1e-6) + 1e-9]
            result[scope][d] = {
                "edges": len(es), "now": now, "standard": ref,
                "difference": now - ref, "ratio": now / ref if ref else None,
                "over_capacity_edges": len(over),
                "excess_total": math.fsum(V[e] - standard[e] for e in over),
            }
    return result


def hex_scenario_comparison(base_rows, scenario_rows, base_mean, scenario_mean):
    """同じ六角形の変更前後を、変更前の標準平均に固定して比較する。"""
    if base_mean is None or scenario_mean is None:
        return []
    rows = []
    for i, j in sorted(base_rows.keys() & scenario_rows.keys()):
        for component in ("cw", "ccw", "net"):
            before = base_rows[i, j]["now"][component]
            after = scenario_rows[i, j]["now"][component]
            ref = base_mean[component]
            rows.append({
                "i": i, "j": j, "component": component,
                "before": before, "after": after, "change": after - before,
                "reference_mean": ref, "before_minus_reference": before - ref,
                "after_minus_reference": after - ref,
                "scenario_standard_mean": scenario_mean[component],
            })
    return rows
