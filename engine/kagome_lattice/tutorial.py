"""解説書とGUIで共有する、単位と手計算が明確な一様入力。"""
from . import _engine as E
from .model import KagomeModel
from .profiles import PROFILE_NAMES
from .semantics import SOURCE_SETTINGS


def tutorial_state(profile="patent"):
    if profile not in PROFILE_NAMES:
        raise ValueError("版が不正です")
    model = KagomeModel(3, halo=True)
    return {
        "n": 3, "halo": True, "profile": profile, "mode": "observe",
        **SOURCE_SETTINGS, "theta": .5, "global_rule": "none", "local_rule": "none",
        "name": "解説書の練習例", "tables": {
            "edges": [dict(zip(("node_type", "i", "j", "road", "m", "L", "v", "V", "T", "mu"),
                               (*e, "2", "0.5", "40", "1600", "100", "1000"))) for e in model.edges],
            "branching": [dict(zip(("node_type", "i", "j", "in_road", "S", "R", "L"),
                                   (*node, road, "0.6", "0.25", "0.15")))
                          for node in sorted(model.nodes) for road in E.CONNECTED_ROADS[node[0]]],
            "entrances": [dict(zip(("node_type", "i", "j", "in_road", "inflow"), (*e, "0")))
                          for e in model.entrances],
        },
    }
