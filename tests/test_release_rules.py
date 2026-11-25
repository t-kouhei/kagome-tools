import csv
import json
import math

import pytest

from kagome_lattice import KagomeModel
from kagome_lattice.cli import main
from kagome_lattice.gui import Workspace
from kagome_lattice.io import read_model
from kagome_lattice.ops import edge_capacity
from kagome_lattice.spin import hex_rotation_comparison, spin_interactions
from kagome_lattice.tutorial import tutorial_state


def model_from_state(state, tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_input(tmp_path / 'input', state)
    return read_model(state['n'], tmp_path / 'input' / 'edges.csv',
                      tmp_path / 'input' / 'branching.csv', halo=state['halo'])


@pytest.mark.parametrize('theta', [0.1, 0.0, 1.0, float('nan')])
def test_capacity_rejects_invalid_or_nonpositive_critical_value(tmp_path, theta):
    state = tutorial_state()
    for row in state['tables']['edges']:
        row.update(mu='100', T='200')
    model = model_from_state(state, tmp_path)
    with pytest.raises(ValueError):
        model.capacity(theta)
    with pytest.raises(ValueError):
        edge_capacity(model, theta)


def test_distribution_only_reports_threshold_outside_nonnegative_range(tmp_path):
    state = tutorial_state()
    for row in state['tables']['edges']:
        row.update(mu='100', T='200')
    model = model_from_state(state, tmp_path)
    values = model.critical(model.normalize(), theta=0.1)
    assert all(row['eps_star'] < 0 and row['ratio'] is None for row in values.values())
    assert all(row['threshold_status'] == 'outside_nonnegative_range' for row in values.values())
    json.dumps(values[next(iter(values))], allow_nan=False)


def test_cli_stops_before_writing_negative_capacity_results(tmp_path):
    state = tutorial_state()
    for row in state['tables']['edges']:
        row.update(mu='100', T='200')
    model_from_state(state, tmp_path)
    assert main(['analyze', '3', str(tmp_path / 'input'), str(tmp_path / 'result'), '--halo', '--theta', '0.1']) == 2
    assert not (tmp_path / 'result' / 'report.json').exists()


@pytest.mark.parametrize('factor', [1.0, 10.0])
def test_zero_standard_spin_is_withheld_without_losing_rotations(tmp_path, factor):
    state = tutorial_state()
    for i, row in enumerate(state['tables']['edges']):
        row.update(V=str((100 + i % 211) * factor), mu=str(100 * factor), T=str(10 * factor))
    for row in state['tables']['branching']:
        row.update(S='0.6', R='0.2', L='0.2')
    model = model_from_state(state, tmp_path)
    standard = model.standard_state()
    dec = model.decompose(model.normalize(), tau_mode='engine', norm='m')
    interaction = spin_interactions(model, dec, standard['dec'])
    assert interaction['scale'] == 0 and not interaction['available']
    assert interaction['status'] == 'withheld'
    assert all(row['now'] is None and row['diff_abs'] is None for row in interaction['types'].values())
    assert interaction['rows'] and all(now is None and reference is None for _, _, now, reference in interaction['rows'])
    assert hex_rotation_comparison(model, dec, standard['dec'])[1]
    json.dumps(interaction, allow_nan=False)


def test_withheld_cli_export_has_blank_scores_and_explicit_reason(tmp_path):
    state = tutorial_state()
    for row in state['tables']['branching']:
        row.update(S='0.6', R='0.2', L='0.2')
    model_from_state(state, tmp_path)
    output = tmp_path / 'result'
    assert main(['analyze', '3', str(tmp_path / 'input'), str(output), '--halo']) == 0
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    assert report['standard']['spin_interactions']['status'] == 'withheld'
    assert '算定保留' in report['standard']['spin_interactions']['reason']
    with (output / 'interactions.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert rows and all(r['q_now'] == r['q_minus_standard'] == '' and r['status'] == 'withheld' for r in rows)
    assert (output / 'hex_rotation.csv').exists()


def test_standard_itself_has_zero_local_difference_but_nonzero_mean_difference(tmp_path):
    state = tutorial_state()
    for i, row in enumerate(state['tables']['edges']):
        row['mu'] = str(100 + i % 11)
    model = model_from_state(state, tmp_path)
    standard = model.standard_state()
    mean, rows = hex_rotation_comparison(model, standard['dec'], standard['dec'])
    assert rows and mean
    assert all(all(v == 0 for v in row['minus_own_standard'].values()) for row in rows.values())
    assert any(abs(row['difference']['cw']) > 0 for row in rows.values())


@pytest.mark.parametrize('factor', [1e-80, 1e80])
def test_provisional_products_do_not_depend_on_quantity_unit_when_scale_positive(tmp_path, factor):
    results = []
    for i, scale in enumerate((1.0, factor)):
        state = tutorial_state()
        for row in state['tables']['edges']:
            for key in ('V', 'mu', 'T'):
                row[key] = str(float(row[key]) * scale)
        model = model_from_state(state, tmp_path / str(i))
        dec = model.decompose(model.normalize(), tau_mode='engine', norm='m')
        results.append(spin_interactions(model, dec, model.standard_state()['dec']))
    assert all(r['available'] for r in results)
    for kind in results[0]['types']:
        assert results[1]['types'][kind]['diff'] == pytest.approx(results[0]['types'][kind]['diff'], rel=1e-11, abs=1e-11)


def test_straight_distribution_keeps_j_reference_explicit(tmp_path):
    model_from_state(tutorial_state(), tmp_path)
    output = tmp_path / 'straight'
    assert main(['analyze', '3', str(tmp_path / 'input'), str(output), '--halo', '--eps', 'straight']) == 0
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    assert report['standard']['standard_quantity'] == 'J'
    assert report['standard']['distribution_quantity'] == 'straight'
    assert report['standard']['distribution_matches_standard'] is False
    assert any(row[1] == 'eps' for row in report['issues'])


def test_default_tutorial_and_both_profiles_keep_expected_rotations(tmp_path):
    for profile in ('patent', 'traffic'):
        model = model_from_state(tutorial_state(profile), tmp_path / profile)
        dec = model.decompose(model.normalize(), tau_mode='engine', norm='m')
        assert dec['sigma']['+', 2, 2] == pytest.approx(600)
        assert dec['sigma']['-', 2, 2] == pytest.approx(360)
        assert model.capacity()[next(iter(model.edges))] == 2000
        assert model.fermi_dirac(1000, 1000, 100) == 0.5
