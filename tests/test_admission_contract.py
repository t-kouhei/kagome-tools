"""Check admission against straight paths with independently countable loads."""
import contextlib
import csv
import io
import json
from pathlib import Path
import zipfile

import pytest

from kagome_lattice.cli import main
from kagome_lattice.flow import global_direction
from kagome_lattice.gui import Workspace
from kagome_lattice.io import read_entrances, read_model

EXAMPLES = Path(__file__).resolve().parent.parent / 'examples/admission'


def model_for(name, tmp_path):
    state = json.loads((EXAMPLES / (name + '.json')).read_text(encoding='utf-8'))
    folder = tmp_path / 'input'
    Workspace(tmp_path).write_input(folder, state)
    model = read_model(state['n'], folder / 'edges.csv', folder / 'branching.csv', halo=state['halo'])
    return state, model, read_entrances(folder / 'entrances.csv')


@pytest.mark.parametrize('name,requested,admitted,rejected', [
    ('low', 38000, 38000, 0), ('high', 228000, 76000, 152000),
    ('direction-6-off', 174000, 58000, 116000),
])
def test_straight_admission_matches_hand_counted_contract(tmp_path, name, requested, admitted, rejected):
    state, model, inflow = model_for(name, tmp_path)
    # All edges have c = m*mu = 2000. Each straight path keeps its entrance flow.
    counts = {d: sum(edge[3] == d for edge in model.edges) for d in range(1, 7)}
    assert counts == {1: 45, 2: 45, 3: 41, 4: 45, 5: 45, 6: 41}
    limits = {d: row['C'] for d, row in model.infrastructure_limit(mode='m').items()}
    assert limits == {d: count * 2000 for d, count in counts.items()}
    result = global_direction(model, inflow, limits)
    assert result['requested'] == requested
    assert result['total'] == pytest.approx(admitted)
    assert result['rejected_total'] == pytest.approx(rejected)
    actual = model.propagate(result['admitted'])
    assert actual['inflow_total'] == pytest.approx(admitted)
    assert actual['outflow_total'] == pytest.approx(admitted)
    expected_edge = 1000 if name == 'low' else 2000
    for edge, value in actual['V'].items():
        assert value == pytest.approx(0 if name == 'direction-6-off' and edge[3] == 6 else expected_edge)
    for direction in range(1, 7):
        before = 0 if name == 'direction-6-off' and direction == 6 else (1000 if name == 'low' else 6000)
        after = 0 if before == 0 else expected_edge
        assert result['load'][direction]['before'] == pytest.approx(counts[direction] * before)
        assert result['load'][direction]['after'] == pytest.approx(counts[direction] * after)
    if name == 'direction-6-off':
        assert limits[6] == 82000  # Zero demand retains the infrastructure reference.
        assert result['by_direction'][6] == {'demand': 0, 'admitted': 0, 'rejected': 0}
        assert len(model.edges) == 262


class DirectWorkspace(Workspace):
    def command(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(list(map(str, args)))
        assert result == 0, output.getvalue()
        return output.getvalue()


@pytest.mark.parametrize('name,requested,admitted', [('high', 228000, 76000),
                                                  ('direction-6-off', 174000, 58000)])
def test_admission_exports_preserve_demand_and_accepted_amounts(tmp_path, name, requested, admitted):
    state = json.loads((EXAMPLES / (name + '.json')).read_text(encoding='utf-8'))
    workspace = DirectWorkspace(tmp_path)
    run = workspace.run(state)
    result = workspace.directory(run['id']) / 'result'
    report = json.loads((result / 'report.json').read_text(encoding='utf-8'))
    control = report['operations']['global']
    assert control['requested'] == requested
    assert control['admitted_total'] == pytest.approx(admitted)
    assert control['rejected_total'] == pytest.approx(requested - admitted)
    assert report['global_rule'] == 'direction' and report['local_rule'] == 'none'
    with (result / 'global.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert sum(float(row['entrance_demand']) for row in rows) == requested
    assert sum(float(row['entrance_admitted']) for row in rows) == pytest.approx(admitted)
    assert all(float(row['load_after']) <= float(row['limit']) + 1e-7 for row in rows)
    with zipfile.ZipFile(result.parent / 'analysis.zip') as archive:
        saved = json.loads(archive.read('result/report.json'))
        assert saved['operations']['global'] == control
