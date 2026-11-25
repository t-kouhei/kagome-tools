"""Controlled synthetic comparisons and shared, scope-explicit result metrics."""
from copy import deepcopy
import math

from .examples import example_state
from .tutorial import tutorial_state

CATALOG = [
    {'id': 'flow', 'name': '流量を増やすと回転量はどう変わる？',
     'changed': '全素辺のVだけを1600→2400。', 'fixed': 'm・L・v・μ・T・分岐を固定。',
     'check': '正味の平均240→360、容量比80%→120%。増減を良否と同一視しません。'},
    {'id': 'components', 'name': '正味が同じでも右・左は変わる',
     'changed': '右25%・左15%・直進60%→右35%・左25%・直進40%。', 'fixed': '全素辺のV・m・L・v・μ・Tを固定。',
     'check': '正味平均240は同じでも、右600→840、左360→600。成分を残す効果を確認します。'},
    {'id': 'reference', 'name': '流れを変えずに比較基準を変える',
     'changed': '全素辺のμだけを1000→1200。', 'fixed': 'V・m・L・v・T・分岐を固定。',
     'check': '現在の回転量は同じ。標準の正味平均300→360、容量比80%→約67%。基準の変更と流れの変更を区別します。'},
    {'id': 'speed', 'name': '観測流量を固定して速度を変える',
     'changed': '全素辺のvだけを40→80。', 'fixed': 'V=1600、m・L・μ・T・分岐を固定。',
     'check': '基本設定ではjと回転量は同じ。換算した素片内の量nは平均20→10。nを固定した実験とは異なります。'},
    {'id': 'bottleneck', 'name': '容量超過を配分調整で解消する',
     'changed': '同じボトルネック入力で局所LP配分を「なし」→「あり」。', 'fixed': '入口の要求量・経路の容量・元の分岐入力を固定。',
     'check': '容量超過1本→0本、最大容量比120%→100%。入口・出口の量も併記し、流入を減らした効果と区別します。'},
]


def comparison_case(identifier, profile):
    info = next((item for item in CATALOG if item['id'] == identifier), None)
    if info is None:
        raise ValueError('比較例が不明です')
    before = example_state('bottleneck', profile) if identifier == 'bottleneck' else tutorial_state(profile)
    after = deepcopy(before)
    if identifier in ('flow', 'reference', 'speed'):
        key, value = {'flow': ('V', '2400'), 'reference': ('mu', '1200'), 'speed': ('v', '80')}[identifier]
        for row in after['tables']['edges']:
            row[key] = value
    elif identifier == 'components':
        for row in after['tables']['branching']:
            row.update(S='0.4', R='0.35', L='0.25')
    else:
        after['local_rule'] = 'lp'
    before['name'] = info['name'] + '（変更前）'
    after['name'] = info['name'] + '（変更後）'
    return {'info': deepcopy(info), 'before': before, 'after': after, 'synthetic': True}


def result_metrics(m, V, J, cap, hex_rows, report):
    def mean(values):
        return math.fsum(values) / len(values) if values else None
    edges = m.inner_edges
    ratios = [V[e] / cap[e] for e in edges] if cap else []
    equivalent = [V[e] * m.values[e].L / m.values[e].v for e in edges
                  if m.values[e].v is not None and m.values[e].v > 0]
    reference = report.get('standard', {}).get('hex_rotation', {}).get('standard_mean') or {}
    propagation = report.get('propagation', {})
    return {
        'scope': 'inner_edges_and_complete_inner_hexagons',
        'edge_count': len(edges), 'hex_count': len(hex_rows),
        'mean_j': mean([J[e] for e in edges]),
        **{'hex_' + key + '_mean': mean([row['now'][key] for row in hex_rows.values()]) for key in ('cw', 'ccw', 'net')},
        'standard_net_mean': reference.get('net'),
        'max_usage': max(ratios) if ratios else None,
        'over_capacity_edges': sum(V[e] > cap[e] * (1 + 1e-6) + 1e-9 for e in edges) if cap else None,
        'equivalent_occupancy_mean': mean(equivalent) if len(equivalent) == len(edges) else None,
        'inflow_requested': propagation.get('inflow_requested'),
        'inflow_total': propagation.get('inflow_total'), 'outflow_total': propagation.get('outflow_total'),
    }


def compare_metrics(before, after, changes=()):
    values = {key: {'before': before.get(key), 'after': value,
                    'change': value - before[key] if isinstance(value, (float, int)) and isinstance(before.get(key), (float, int)) else None}
              for key, value in after.items() if key not in ('scope', 'edge_count', 'hex_count')}
    notes = []
    def same(key):
        a, b = before.get(key), after.get(key)
        return a is not None and b is not None and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
    def different(key):
        return before.get(key) is not None and after.get(key) is not None and not same(key)
    if same('hex_net_mean') and not (same('hex_cw_mean') and same('hex_ccw_mean')):
        notes.append('正味の平均が同じでも、右回り・左回りの平均は変わっています。成分を分けて確認してください。')
    if same('hex_net_mean') and different('standard_net_mean'):
        notes.append('現在の正味平均を保ったまま、比較基準の標準平均が変わっています。基準の変化を回転量の改善と読み替えません。')
    if same('mean_j') and same('hex_net_mean') and different('equivalent_occupancy_mean'):
        notes.append('規格化量と正味回転の平均は同じで、V・L・vから換算した素片内の量が変わっています。')
    if before.get('over_capacity_edges') is not None and after.get('over_capacity_edges') is not None:
        if before['over_capacity_edges'] > 0 and after['over_capacity_edges'] == 0:
            notes.append('解析範囲内の容量超過が0本になりました。各時点の容量に対する結果です。入口・出口の量と変更した条件も確認してください。')
    grouped = {}
    for source, location, key, previous, current in changes:
        group = (str(source), str(key), str(previous), str(current))
        grouped[group] = grouped.get(group, 0) + 1
    changed_parameters = [{'source': source, 'parameter': key, 'before': previous, 'after': current, 'rows': count}
                          for (source, key, previous, current), count in grouped.items()]
    return {'scope': after['scope'], 'values': values, 'observations': notes, 'changed_parameters': changed_parameters,
            'note': '内側の素辺と完全な内側六角形の集計。平均値の一致は各面・各素辺の一致を意味しません。数値の大小だけで総合的な良否は判定しません。'}
