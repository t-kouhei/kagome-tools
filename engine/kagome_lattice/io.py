# -*- coding: utf-8 -*-
"""入力テンプレートの書き出し、入力 CSV の読み込み、結果の書き出し。

入力は 3 つの CSV（1 行 = 1 つの場所）。
  edges.csv      素辺ごと : node_type, i, j, road, m, L, v, V, T, mu
  branching.csv  交差点×入ってきた向きごと : node_type, i, j, in_road, S, R, L
  entrances.csv  入口ごと（伝播モードのみ） : node_type, i, j, in_road, inflow
空欄は「未入力」。どの値にどの物理量を当てはめるかは使う側が決める。
"""
import csv
import json
import os

from .model import KagomeModel
from .profiles import PROFILE_NAMES, profile_info
from .semantics import SOURCE_SETTINGS, LEGACY_SETTINGS

EDGE_COLS = ["node_type", "i", "j", "road", "m", "L", "v", "V", "T", "mu"]
BRANCH_COLS = ["node_type", "i", "j", "in_road", "S", "R", "L"]
ENTRANCE_COLS = ["node_type", "i", "j", "in_road", "inflow"]


LATTICE_FILE = "lattice.json"


def write_templates(n: int, outdir: str, halo: bool = False, profile: str = "traffic", calculation=None):
    """格子の大きさ N の空のテンプレート 3 つと、格子の形（lattice.json）を書き出す。

    halo=True なら余白の 1 リングを含めた (N+2)×(N+2) の素辺を並べる（添字 0 と N+1 が余白）。
    """
    calculation = dict(calculation or SOURCE_SETTINGS)
    info = profile_info(profile, calculation["norm"])
    m = KagomeModel(n, halo=halo)
    os.makedirs(outdir, exist_ok=True)
    write_json(os.path.join(outdir, LATTICE_FILE),
               {"n": n, "halo": bool(halo), "profile": profile, "calculation": calculation,
                "note": "inner は添字 1〜N（halo のとき）。余白の素辺にも値を入れる"})
    write_json(os.path.join(outdir, "parameters.json"), info)
    with open(os.path.join(outdir, "edges.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(EDGE_COLS)
        for (t, i, j, r) in m.edges:
            w.writerow([t, i, j, r] + [""] * 6)
    with open(os.path.join(outdir, "branching.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(BRANCH_COLS)
        for (t, i, j) in m.nodes:
            for r in sorted(_in_roads(m, (t, i, j))):
                w.writerow([t, i, j, r, "", "", ""])
    with open(os.path.join(outdir, "entrances.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(ENTRANCE_COLS)
        for (t, i, j, r) in m.entrances:
            w.writerow([t, i, j, r, ""])
    return m


def _in_roads(m: KagomeModel, node):
    from . import _engine as E
    return E.CONNECTED_ROADS[node[0]]


def _num(x):
    x = (x or "").strip()
    return None if x == "" else float(x)


def _reader(stream, columns, name):
    reader = csv.DictReader(stream)
    fields = reader.fieldnames or []
    missing = set(columns) - set(fields)
    if missing or len(fields) != len(set(fields)):
        raise ValueError(f"{name}の列名に不足または重複があります。必要な列: {','.join(columns)}")
    return reader


def read_lattice_info(indir: str):
    """テンプレートと一緒に書いた格子の形 {n, halo}。無ければ None。"""
    path = os.path.join(indir, LATTICE_FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    profile = d.get("profile", "traffic")
    if profile not in PROFILE_NAMES:
        raise ValueError(f"lattice.jsonのprofileが不明: {profile}")
    calculation = d.get("calculation", dict(LEGACY_SETTINGS))
    if not isinstance(calculation, dict) or calculation.get("norm") not in ("k", "m", "mvl") or calculation.get("tau") not in ("count", "engine"):
        raise ValueError("lattice.jsonの計算設定が不正です")
    return {"n": int(d["n"]), "halo": bool(d.get("halo", False)), "profile": profile,
            "calculation": calculation, "legacy_settings": "calculation" not in d}


def read_model(n: int, edges_csv: str, branching_csv: str, halo: bool = False):
    """CSV から格子と値を組み立てる。形の誤り（格子に無い場所・数字でない値）はまとめて報告する。"""
    m = KagomeModel(n, halo=halo)
    errors = []
    seen_edges, seen_branches = set(), set()
    with open(edges_csv, newline="", encoding="utf-8-sig") as f:
        for k, row in enumerate(_reader(f, EDGE_COLS, "edges.csv"), start=2):
            try:
                e = (row["node_type"].strip(), int(row["i"]), int(row["j"]), int(row["road"]))
                if e in seen_edges:
                    raise ValueError(f"素辺の重複: {e}")
                seen_edges.add(e)
                m.set_edge(e, **{c: _num(row.get(c)) for c in EDGE_COLS[4:]})
            except (KeyError, ValueError, TypeError, AttributeError) as ex:
                errors.append(f"edges.csv {k} 行目: {ex}")
    with open(branching_csv, newline="", encoding="utf-8-sig") as f:
        for k, row in enumerate(_reader(f, BRANCH_COLS, "branching.csv"), start=2):
            try:
                node = (row["node_type"].strip(), int(row["i"]), int(row["j"]))
                road = int(row["in_road"])
                if (*node, road) in seen_branches:
                    raise ValueError(f"分岐の重複: {(*node, road)}")
                seen_branches.add((*node, road))
                vals = [_num(row.get(c)) for c in ("S", "R", "L")]
                if all(v is None for v in vals):
                    continue
                m.set_branching(node, road, *[v or 0.0 for v in vals])
            except (KeyError, ValueError, TypeError, AttributeError) as ex:
                errors.append(f"branching.csv {k} 行目: {ex}")
    if errors:
        raise ValueError("入力の形に誤りがある:\n" + "\n".join(errors))
    return m


def read_entrances(path: str):
    out = {}
    seen = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        for line, row in enumerate(_reader(f, ENTRANCE_COLS, "entrances.csv"), start=2):
            try:
                key = (row["node_type"].strip(), int(row["i"]), int(row["j"]), int(row["in_road"]))
                if key in seen:
                    raise ValueError(f"入口の重複: {key}")
                seen.add(key)
                b = _num(row.get("inflow"))
                if b is not None:
                    out[key] = b
            except (KeyError, ValueError, TypeError, AttributeError) as ex:
                raise ValueError(f"entrances.csv {line} 行目: {ex}") from ex
    return out


def apply_changes(m, inflow, change_dir: str):
    """シナリオ：change_dir の CSV に書いた行だけ、もとの値を置き換える（m と inflow を直接変える）。

      edges.csv      node_type, i, j, road と、変えたい列だけ（空欄の列は変えない）
      branching.csv  node_type, i, j, in_road, S, R, L（その行の分岐の割合を置き換える）
      entrances.csv  node_type, i, j, in_road, inflow（その入口の流入量を置き換える）
    どれも無くてよい。返り値は変えた内容の記録 [(ファイル, 場所, 列, もとの値, 新しい値)]。
    """
    log, errors = [], []
    path = os.path.join(change_dir, "edges.csv")
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for k, row in enumerate(csv.DictReader(f), start=2):
                try:
                    e = (row["node_type"].strip(), int(row["i"]), int(row["j"]), int(row["road"]))
                    if e not in m.values:
                        raise KeyError(f"格子に無い素辺: {e}")
                    for c in EDGE_COLS[4:]:
                        x = _num(row.get(c))
                        if x is not None:
                            log.append(("edges", edge_id(e), c, getattr(m.values[e], c), x))
                            m.set_edge(e, **{c: x})
                except (KeyError, ValueError) as ex:
                    errors.append(f"変更の edges.csv {k} 行目: {ex}")
    path = os.path.join(change_dir, "branching.csv")
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for k, row in enumerate(csv.DictReader(f), start=2):
                try:
                    node = (row["node_type"].strip(), int(row["i"]), int(row["j"]))
                    r = int(row["in_road"])
                    vals = [_num(row.get(c)) or 0.0 for c in ("S", "R", "L")]
                    old = m.branching.get((*node, r))
                    m.set_branching(node, r, *vals)
                    fmt = lambda xs: "/".join(f"{x:g}" for x in xs)
                    log.append(("branching", "%s(%d,%d)" % node + f"←{r}", "S/R/L",
                                None if old is None else fmt([old[t] for t in ("S", "R", "L")]), fmt(vals)))
                except (KeyError, ValueError) as ex:
                    errors.append(f"変更の branching.csv {k} 行目: {ex}")
    path = os.path.join(change_dir, "entrances.csv")
    if os.path.exists(path):
        for x, b in read_entrances(path).items():
            if x not in m.entrances:
                errors.append(f"変更の entrances.csv: 入口ではない {x}")
                continue
            log.append(("entrances", "%s(%d,%d)" % x[:3] + f"←{x[3]}", "inflow", inflow.get(x), b))
            inflow[x] = b
    if errors:
        raise ValueError("変更の入力に誤りがある:\n" + "\n".join(errors))
    return log


def edge_id(e):
    t, i, j, r = e
    return f"{t}({i},{j})-{r}"


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
