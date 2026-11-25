import contextlib
import csv
import io
import json
import math
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'engine'))
from kagome_lattice import cli

qa = ROOT / 'qa-output'
source = qa / 'native-input'
source.mkdir(exist_ok=True)
with zipfile.ZipFile(qa / 'analysis.zip') as archive:
    for info in archive.infolist():
        if info.filename.startswith('input/'):
            archive.extract(info, source)
out = qa / 'native-result'
capture = io.StringIO()
with contextlib.redirect_stdout(capture):
    cli.main(['analyze', '3', str(source / 'input'), str(out), '--profile', 'patent', '--norm', 'm', '--tau', 'engine', '--theta', '0.5', '--halo', '--entrances', '--global', 'none', '--local', 'none'])
browser = json.loads((qa / 'browser-report.json').read_text(encoding='utf-8'))['provenance']
native = json.loads((out / 'report.json').read_text(encoding='utf-8'))['provenance']
assert browser['input_sha256'] == native['input_sha256'], 'Input identity differs'
comparisons = {}
with zipfile.ZipFile(qa / 'analysis.zip') as archive:
    for name in native['output_sha256']:
        left = list(csv.DictReader(io.StringIO(archive.read('result/' + name).decode('utf-8'))))
        with (out / name).open(encoding='utf-8', newline='') as stream:
            right = list(csv.DictReader(stream))
        assert len(left) == len(right), name
        maximum = 0.0
        for a, b in zip(left, right):
            assert a.keys() == b.keys()
            for key in a:
                if a[key] == b[key]:
                    continue
                x, y = float(a[key]), float(b[key])
                assert math.isclose(x, y, rel_tol=1e-12, abs_tol=1e-10), (name, key, x, y)
                maximum = max(maximum, abs(x - y))
        comparisons[name] = {'rows': len(left), 'maximum_absolute_difference': maximum,
                             'byte_identical': browser['output_sha256'][name] == native['output_sha256'][name]}
result = {'input_sha256': browser['input_sha256'], 'files': comparisons, 'within_tolerance': True,
          'absolute_tolerance': 1e-10, 'relative_tolerance': 1e-12}
(qa / 'native-parity.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print('NATIVE/BROWSER PARITY PASS', comparisons)
