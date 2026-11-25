"""輸送量・流量・規格化量の意味と、明示的な旧設定からの移行。"""
import copy
import math

SOURCE_SETTINGS = {"norm": "m", "tau": "engine"}
LEGACY_SETTINGS = {"norm": "k", "tau": "count"}
ROUTING_CONVENTION = (
    "in/outは輸送の進行方向を表す。τは図形に沿って前の素辺から入り次の素辺へ出る寄与。"
    "+は時計回り、−は反時計回り。原資料の表記差7項は、この接続規約に正規化する実装判断を記録した。"
)
SOURCE_INDEX_INTERPRETATIONS = [
    {"page": 24, "term": "上向きE・R", "literal": "分母5in", "normalized": "分母2out"},
    {"page": 25, "term": "下向きC・R", "literal": "分子3out", "normalized": "分子3in"},
    {"page": 25, "term": "下向きC・L", "literal": "分母6in", "normalized": "分母6out"},
    {"page": 25, "term": "下向きE・R", "literal": "分子1out・分母5in", "normalized": "分子1in・分母5out"},
    {"page": 25, "term": "下向きE・L", "literal": "分子2out・分母4in", "normalized": "分子2in・分母4out"},
    {"page": 25, "term": "下向きD・R", "literal": "右辺の節点E", "normalized": "右辺の節点D"},
    {"page": 27, "term": "六角形下半分C・R", "literal": "分子3out・分母4in", "normalized": "分子4in・分母3out"},
]


def flow_from_occupancy(n, length, speed):
    if not all(math.isfinite(x) for x in (n, length, speed)) or n < 0 or length <= 0 or speed <= 0:
        raise ValueError("素片内の量nは有限の非負数、長さLと速度vは有限の正数が必要です")
    result = n * speed / length
    if not math.isfinite(result):
        raise ValueError("n・L・vの桁が大きすぎて流量へ換算できません")
    return result


def source_equivalent_occupancy(V, length, speed):
    return V * length / speed if speed is not None and speed > 0 and length is not None else None


def convert_state_units(state, norm, tau=None):
    """Vと臨界総流量を保持して、μ・Tを選択した規格化量の単位にそろえる。"""
    converted = copy.deepcopy(state)
    old_norm = state["norm"]
    changes = []
    def factor(row, mode):
        if mode == "m":
            return 1.0
        speed = float(row["v"])
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("単位換算には有限の正の速度vが必要です")
        if mode == "k":
            return speed
        if mode == "mvl":
            length = float(row["L"])
            if not math.isfinite(length) or length <= 0:
                raise ValueError("単位換算には有限の正の長さLが必要です")
            return length / speed
        raise ValueError("規格化が不明です")
    for row in converted["tables"]["edges"]:
        ratio = factor(row, old_norm) / factor(row, norm)
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError("μ・Tの単位換算には有限の正のL・vが必要です")
        for key in ("mu", "T"):
            if row[key] not in (None, ""):
                value = float(row[key]) * ratio
                if not math.isfinite(value):
                    raise ValueError("μ・Tの換算結果が有限値になりません")
                row[key] = str(value)
        changes.append({"edge": [row[k] for k in ("node_type", "i", "j", "road")], "factor": ratio})
    converted.update(norm=norm, tau=tau or state["tau"])
    converted["migration"] = {"from": {k: state[k] for k in ("norm", "tau")},
                              "to": {k: converted[k] for k in ("norm", "tau")}, "mu_T_factors": changes,
                              "note": "Vと臨界総流量を保持する単位換算。τ・s・σ・直進成分は新しい定義で再計算する。"}
    return converted


def migrate_state_to_source(state):
    return convert_state_units(state, **SOURCE_SETTINGS)
