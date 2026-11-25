"""現行式への入力値・中間値・出力の対応。先生の式の確定を意味しない。"""
import math

from . import _engine as E
from .io import edge_id
from .spin import faces
from .semantics import ROUTING_CONVENTION, source_equivalent_occupancy


def _turn_term(m, V, J, node, mapping, turn, norm, tau_mode):
    definition = mapping[node[0]][turn]
    source = m.upstream(node, definition["in_road"])
    target = (*node, definition["out_road"])
    if source is None or target not in m.index:
        return {"node": list(node), "turn": turn, "complete": False, "value": None}
    incoming, outgoing = m.values[source], m.values[target]
    beta = m.beta(node, definition["in_road"], turn)
    numerator_flow = V[source] if tau_mode == "count" else J[source]
    divisor = m.denormalize_factor(target, norm) if tau_mode == "count" else outgoing.m
    value = numerator_flow * beta * incoming.L / (divisor * outgoing.L)
    return {"node": list(node), "turn": turn, "complete": True,
            "incoming_edge": edge_id(source), "outgoing_edge": edge_id(target),
            "V_in": V[source], "J_in": J[source], "beta": beta,
            "L_in": incoming.L, "L_out": outgoing.L, "divisor": divisor,
            "numerator_flow": numerator_flow,
            "formula": "V_in × β × L_in / (D_out × L_out)" if tau_mode == "count"
                       else "J_in × β × L_in / (m_out × L_out)",
            "value": value}


def _state_trace(m, V, J, dec, norm, tau_mode, crit=None, cap=None):
    edges = {}
    for edge in m.edges:
        node = m.target(edge)
        tri, hexa = E.STRAIGHT_POTENTIAL_IN_TERMS[(node[0], edge[3])]
        _, orient, sign, di, dj = tri
        s_key = (orient, sign, node[1] + di, node[2] + dj)
        _, sign, di, dj = hexa
        h_key = (sign, node[1] + di, node[2] + dj)
        s_val, h_val = dec["s"].get(s_key), dec["sigma"].get(h_key)
        complete = dec["straight"][edge]["complete"]
        ev = m.values[edge]
        row = {"inputs": {k: getattr(ev, k) for k in ("m", "L", "v", "T", "mu")},
               "V": V[edge], "n_equivalent": source_equivalent_occupancy(V[edge], ev.L, ev.v),
               "j_source": V[edge] / ev.m,
               "denormalize_factor": m.denormalize_factor(edge, norm), "J": J[edge],
               "straight": {"formula": "J − s/3 − σ/6", "s_reference": list(s_key),
                            "sigma_reference": list(h_key), "s": s_val, "sigma": h_val,
                            "s_over_3": s_val / 3 if s_val is not None else None,
                            "sigma_over_6": h_val / 6 if h_val is not None else None,
                            "recomputed": J[edge] - s_val / 3 - h_val / 6 if complete else None,
                            "value": dec["straight"][edge]["J_straight"],
                            "complete": dec["straight"][edge]["complete"]}}
        if crit is not None:
            row["critical"] = dict(crit[edge])
        if cap is not None:
            row.update(standard_flow=cap[edge], minus_standard=V[edge] - cap[edge],
                       usage=V[edge] / cap[edge] if cap[edge] else None)
        edges[edge_id(edge)] = row
    rings = []
    for face in faces(m, dec):
        if not all(node in m.inner_nodes for node in face["vs"]):
            continue
        kind, i, j = face["key"]
        for component, sign, turn in (("cw", "+", "R"), ("ccw", "-", "L")):
            terms = []
            for index, node in enumerate(face["vs"]):
                mapping = (E.TURN_MAP_HEX_UPPER if index < 3 else E.TURN_MAP_HEX_LOWER) if kind == "h" else (
                    E.TURN_MAP_UP if kind == "u" else E.TURN_MAP_DOWN)
                terms.append(_turn_term(m, V, J, node, mapping, turn, norm, tau_mode))
            value = dec["sigma"][sign, i, j] if kind == "h" else dec["s"][kind, sign, i, j]
            recomputed = math.fsum(t["value"] for t in terms) if all(t["complete"] for t in terms) else None
            rings.append({"kind": kind, "i": i, "j": j, "component": component,
                          "terms": terms, "value": value, "recomputed": recomputed})
    return {"edges": edges, "rings": rings}


def calculation_trace(m, V, J, dec, norm, tau_mode, crit=None, cap=None, standard=None, standard_model=None):
    result = {"norm": norm, "tau_mode": tau_mode,
              "routing_convention": ROUTING_CONVENTION,
              "note": "Vは単位時間あたりの総流量。原資料のnとはV=n·v/Lで対応し、j=V/m。"
                      "原資料の基本設定はnorm=m・tau=engine。"
                      "DはJをVに戻す係数（k: v×m、m: m、mvl: L×m/v）。"
                      "回転の内訳は解析範囲内の完全な図形。端で必要な入力が欠ける項は未完として示す。",
              "now": _state_trace(m, V, J, dec, norm, tau_mode, crit, cap)}
    if standard is not None:
        result["standard"] = _state_trace(standard_model or m, standard["V"], standard["J"], standard["dec"],
                                          norm, tau_mode)
    return result
