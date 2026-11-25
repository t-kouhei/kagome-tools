import contextlib
import copy
import io
import json
import zipfile

import pytest

from kagome_lattice.cli import main
from kagome_lattice.effects import CATALOG, compare_metrics, comparison_case
from kagome_lattice.gui import Workspace


class DirectWorkspace(Workspace):
    def command(self, args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(list(map(str, args)))
        assert code == 0, stream.getvalue()
        return stream.getvalue()


@pytest.mark.parametrize('identifier', [row['id'] for row in CATALOG])
def test_controlled_comparisons_report_measured_effects_and_reproducible_inputs(tmp_path, identifier):
    workspace = DirectWorkspace(tmp_path)
    pair = comparison_case(identifier, 'patent')
    before, after = copy.deepcopy(pair['before']), copy.deepcopy(pair['after'])
    baseline = workspace.save(before)
    result = workspace.run(after, baseline)
    folder = workspace.directory(result['id'])
    base = json.loads((folder / 'result/base/report.json').read_text(encoding='utf-8'))
    report = json.loads((folder / 'result/scenario/report.json').read_text(encoding='utf-8'))
    values = report['comparison_summary']['values']
    assert report['comparison_summary']['changed_parameters']
    assert pair['before'] == before and pair['after'] == after
    with zipfile.ZipFile(folder / 'analysis.zip') as archive:
        assert json.loads(archive.read('result/scenario/report.json'))['comparison_summary'] == report['comparison_summary']
        assert json.loads(archive.read('base/lattice.json'))['profile'] == 'patent'
    if identifier == 'flow':
        assert values['hex_net_mean']['before'] == pytest.approx(240)
        assert values['hex_net_mean']['after'] == pytest.approx(360)
        assert values['max_usage']['after'] == pytest.approx(1.2)
    elif identifier == 'components':
        assert values['hex_net_mean']['change'] == pytest.approx(0)
        assert values['hex_cw_mean']['before'] == pytest.approx(600)
        assert values['hex_cw_mean']['after'] == pytest.approx(840)
        assert values['hex_ccw_mean']['after'] == pytest.approx(600)
        assert any('成分' in note for note in report['comparison_summary']['observations'])
    elif identifier == 'reference':
        assert values['hex_net_mean']['change'] == pytest.approx(0)
        assert values['standard_net_mean']['before'] == pytest.approx(300)
        assert values['standard_net_mean']['after'] == pytest.approx(360)
        assert any('比較基準' in note for note in report['comparison_summary']['observations'])
    elif identifier == 'speed':
        assert values['mean_j']['change'] == pytest.approx(0)
        assert values['hex_net_mean']['change'] == pytest.approx(0)
        assert values['equivalent_occupancy_mean']['before'] == pytest.approx(20)
        assert values['equivalent_occupancy_mean']['after'] == pytest.approx(10)
    elif identifier == 'bottleneck':
        assert base['local_rule'] == 'none' and report['local_rule'] == 'lp'
        assert base['operations'] == {} and report['operations']['local']['resolved'] is True
        assert values['over_capacity_edges']['before'] == 1
        assert values['over_capacity_edges']['after'] == 0
        assert values['max_usage']['before'] == pytest.approx(1.2)
        assert values['max_usage']['after'] <= 1 + 1e-6
        assert values['inflow_total']['before'] == values['inflow_total']['after'] == 228000
        assert values['outflow_total']['change'] == pytest.approx(0, abs=1e-6)
        assert any(row[0] == 'settings' and row[2] == 'local_rule' for row in report['changes'])


def test_missing_reference_is_not_interpreted_as_a_change():
    metrics = {'scope': 'inner_edges_and_complete_inner_hexagons', 'mean_j': 10.0, 'hex_net_mean': 0.0,
               'hex_cw_mean': 1.0, 'hex_ccw_mean': 1.0, 'standard_net_mean': None,
               'equivalent_occupancy_mean': None, 'over_capacity_edges': None}
    assert compare_metrics(metrics, metrics)['observations'] == []


def test_global_control_comparison_does_not_apply_current_rule_to_baseline(tmp_path):
    workspace = DirectWorkspace(tmp_path)
    pair = comparison_case('bottleneck', 'patent')
    before = pair['before']
    for row in before['tables']['entrances']:
        row['inflow'] = str(float(row['inflow']) * 100)
    after = copy.deepcopy(before)
    after['global_rule'] = 'direction'
    result = workspace.run(after, workspace.save(before))
    folder = workspace.directory(result['id'])
    base = json.loads((folder / 'result/base/report.json').read_text(encoding='utf-8'))
    scenario = json.loads((folder / 'result/scenario/report.json').read_text(encoding='utf-8'))
    assert base['global_rule'] == 'none' and scenario['global_rule'] == 'direction'
    assert base['propagation']['inflow_total'] > scenario['propagation']['inflow_total']
    assert base['propagation']['inflow_requested'] == scenario['propagation']['inflow_requested']


@pytest.mark.parametrize('identifier', [row['id'] for row in CATALOG])
def test_profile_changes_only_meaning_not_controlled_numerical_inputs(identifier):
    a, b = comparison_case(identifier, 'patent'), comparison_case(identifier, 'traffic')
    for state in ('before', 'after'):
        assert a[state]['tables'] == b[state]['tables']
        assert a[state]['local_rule'] == b[state]['local_rule']


def test_unknown_comparison_is_rejected():
    with pytest.raises(ValueError):
        comparison_case('unknown', 'patent')
