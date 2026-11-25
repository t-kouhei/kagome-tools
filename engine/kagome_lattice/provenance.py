"""入力・式の識別と、当時の実装を残す再現用記録。署名による真正性の証明ではない。"""
import csv
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import sys
import zipfile

FORMULA_VERSION = 'kagome-source-routing-20261109.1'
NUMERIC_MODULES = ('_engine.py', 'model.py', 'steady.py', 'flow.py', 'ops.py', 'spin.py',
                   'semantics.py', 'diagnostics.py', 'trace.py', 'check.py', 'io.py', 'cli.py', 'basis.py')
OUTPUTS = ('edges_result.csv', 'tau.csv', 'rotation.csv', 'hex_rotation.csv', 'direction_comparison.csv')


def digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def code_identity(snapshot=None):
    folder = Path(__file__).parent
    source = snapshot or {path.name:path.read_bytes() for path in sorted(folder.glob('*.py'))}
    files = {name:hashlib.sha256(data).hexdigest() for name,data in source.items() if name.endswith('.py')}
    return {'files': files, 'software_sha256': digest(files),
            'engine_sha256': digest({name: files[name] for name in NUMERIC_MODULES})}


def capture(model, inflow, args):
    from . import __version__
    values = [[*edge, *[getattr(model.values[edge], k) for k in ('m', 'L', 'v', 'V', 'T', 'mu')]]
              for edge in sorted(model.edges)]
    branches = [[*key, *[beta[t] for t in ('S', 'R', 'L')]] for key, beta in sorted(model.branching.items())]
    entrances = None if inflow is None else [[*key, inflow.get(key, 0.)] for key in sorted(model.entrances)]
    settings = {key: getattr(args, key) for key in ('norm', 'tau', 'eps', 'theta', 'limit', 'global_rule', 'local_rule', 'local_objective', 'exits')}
    inputs = {'n': model.n, 'halo': model.halo, 'values': values, 'branching': branches, 'entrances': entrances, 'settings': settings}
    environment = {'python': platform.python_version(), 'platform': platform.platform(), 'libraries': {}}
    for name in ('numpy', 'scipy', 'matplotlib'):
        try:
            environment['libraries'][name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            environment['libraries'][name] = None
    snapshot={path.name:path.read_bytes() for path in sorted(Path(__file__).parent.iterdir()) if path.suffix in ('.py','.html','.css','.js')}
    return {'schema_version': 1, 'software_version': __version__, 'formula_version': FORMULA_VERSION,
            **code_identity(snapshot), '_snapshot_bytes':snapshot, 'input_sha256': digest(inputs), 'inputs': inputs, 'profile': args.profile,
            'environment': environment,
            'note': '式の版は採用した定義の識別子。先生による承認や理論の可解性の証明を意味しない。'
                    '入力の識別は数値と計算設定による。名前・版の表示用語は入力ハッシュに含めない。'
                    '異なるOS・ライブラリ・数値計算環境での完全なビット一致は保証しない。'}


def write_bundle(outdir, record):
    from .io import EDGE_COLS, BRANCH_COLS, ENTRANCE_COLS, write_csv, write_json
    outdir = Path(outdir)
    data = record['inputs']
    replay = outdir/'replay-input'
    replay.mkdir(exist_ok=True)
    write_csv(replay/'edges.csv', EDGE_COLS, data['values'])
    write_csv(replay/'branching.csv', BRANCH_COLS, data['branching'])
    write_csv(replay/'entrances.csv', ENTRANCE_COLS, data['entrances'] or [])
    write_json(replay/'lattice.json', {'n':data['n'], 'halo':data['halo'], 'profile':record['profile'],
                                     'calculation':{k:data['settings'][k] for k in ('norm', 'tau')}})
    args = ['analyze', str(data['n']), 'replay-input', 'replay-output', '--profile', record['profile']]
    if data['halo']: args.append('--halo')
    if data['entrances'] is not None: args.append('--entrances')
    flags = {'global_rule':'global', 'local_rule':'local', 'local_objective':'local-objective'}
    for key, value in data['settings'].items(): args += ['--'+flags.get(key, key), str(value)]
    record['replay_arguments'] = args
    record['output_sha256'] = {name:hashlib.sha256((outdir/name).read_bytes()).hexdigest()
                               for name in OUTPUTS if (outdir/name).exists()}
    snapshot=record.pop('_snapshot_bytes')
    write_json(outdir/'provenance.json', record)
    folder = Path(__file__).parent
    with zipfile.ZipFile(outdir/'engine_snapshot.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name,data_bytes in snapshot.items():
            archive.writestr('kagome_lattice/'+name,data_bytes)
        archive.writestr('requirements.lock', '\n'.join(name+'=='+version for name, version in record['environment']['libraries'].items() if version)+'\n')
    (outdir/'REPRODUCE.txt').write_text(
        '1. engine_snapshot.zipをこの結果フォルダに展開する。\n'
        '2. 記録されたPythonと依存パッケージを用意する（requirements.lockを参照）。\n'
        '3. このフォルダで次のコマンドを実行する。\n\npython -X utf8 -m kagome_lattice '+ ' '.join(args)+
        '\n\nprovenance.jsonのoutput_sha256で主要CSVを照合できる。\n'
        '元の結果は上書きせず、replay-outputへ出力する。環境の差による丸め差は別途確認する。\n', encoding='utf-8')
    return {key:record[key] for key in ('schema_version','software_version','formula_version','software_sha256','engine_sha256','input_sha256','environment','output_sha256','note')}
