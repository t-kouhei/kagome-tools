"""Browser transport adapter. Uses the same release calculation code as Python."""
import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import threading
import sys

from kagome_lattice.gui import Workspace, COLUMNS
from kagome_lattice.model import KagomeModel
from kagome_lattice.profiles import profile_info
from kagome_lattice.semantics import migrate_state_to_source, convert_state_units, flow_from_occupancy
from kagome_lattice.tutorial import tutorial_state
from kagome_lattice.examples import CATALOG, example_state
from kagome_lattice import cli
from kagome_lattice import sweep as sweep_module


class BrowserWorkspace(Workspace):
    def command(self, args):
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                result = cli.main(list(map(str, args)))
            if result not in (None, 0):
                raise ValueError(output.getvalue() or '計算を完了できませんでした。')
        except SystemExit as error:
            if error.code not in (None, 0):
                raise ValueError(output.getvalue() or str(error)) from error
        return output.getvalue()


class DeferredPool:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append(args)

    def shutdown(self, **kwargs):
        pass


class BrowserSweeps(sweep_module.SweepManager):
    """Advance one case per message, leaving the UI and cancel action responsive."""
    def __init__(self, workspace):
        self.workspace = workspace
        self.pool = DeferredPool()
        self.ids = set()
        self.lock = threading.Lock()
        self.jobs = {}
        self.starting = False

    def start(self, state, request):
        self.starting = True
        try:
            document = super().start(state, request)
        finally:
            self.starting = False
        pending, frozen, changed = self.pool.jobs.pop()
        self.jobs[document['id']] = [pending, frozen, changed, -1]
        return document

    def status(self, identifier):
        document = super().status(identifier)
        if document and document['status'] in ('queued', 'running') and identifier not in self.jobs and not self.starting:
            # A browser reload terminates its worker. Keep finished cases visible.
            document.update(status='interrupted', error='ページが再読み込みされたため一括比較を中断しました。完了済みの個別結果は残っています。同じ条件で新しく実行できます。')
            for key in ('url', 'csv_url', 'archive_url', 'cancel_requested', 'archiving'):
                document.pop(key, None)
            self._write(document)
            return super().status(identifier)
        return document

    def tick(self, identifier):
        job = self.jobs.get(identifier)
        if not job:
            return self.status(identifier)
        document, state, changed, step = job
        folder = self.workspace.directory(identifier)
        terminal = False
        try:
            if (folder / 'cancel.request').exists():
                document['status'] = 'cancelled'
                terminal = True
            elif step == -1:
                document['status'] = 'running'
                result = self.workspace.run(state)
                document['reference'] = sweep_module.summary(self.workspace, result)
                job[3] = 0
            else:
                value = document['request']['values'][step]
                try:
                    result = self.workspace.run(changed[step])
                    reference = document['reference'].get('own_standard_net_mean')
                    row = {'value': value, **sweep_module.summary(self.workspace, result, reference)}
                except Exception as error:
                    row = {'value': value, 'status': 'error', 'error': str(error)}
                document['cases'].append(row)
                document['completed'] = len(document['cases'])
                job[3] += 1
                if job[3] == len(changed):
                    document['status'] = 'completed_with_errors' if any(r['status'] == 'error' for r in document['cases']) else 'completed'
                    terminal = True
        except Exception as error:
            document.update(status='failed', error=str(error))
            terminal = True
        self._write(document)
        if terminal:
            try:
                self._archive(document)
            except Exception as error:
                document['archive_error'] = str(error)
                self._write(document)
            self.ids.discard(identifier)
            self.jobs.pop(identifier, None)
        return self.status(identifier)


workspace = BrowserWorkspace('/persist/workspace')
sweep_module.alive = lambda pid: True
sweeps = BrowserSweeps(workspace)


def dispatch(path, data):
    if path == 'init':
        return workspace.initialize(data)
    if path == 'examples':
        return CATALOG
    if path == 'example':
        return example_state(data['id'], data['profile'])
    if path == 'sweep':
        return sweeps.start(data['state'], data['request'])
    if path == 'sweep-status':
        return sweeps.tick(data['id'])
    if path == 'sweep-cancel':
        return sweeps.cancel(data['id'])
    if path == 'startup':
        return workspace.history.startup(data.get('profile', 'auto'), data.get('session_id'))
    if path == 'draft':
        return workspace.history.store_draft(data)
    if path == 'duplicate':
        return workspace.history.duplicate(data['id'], data.get('name'))
    if path == 'result':
        result = workspace.history.result(data['id'])
        if result and 'state' in data:
            before, current = workspace.load(data['id']), dict(data['state'])
            for item in (before, current):
                item.setdefault('global_rule', 'none')
                item.setdefault('local_rule', 'none')
            if before != current:
                return None
        return result
    if path == 'tutorial':
        return tutorial_state(data['profile'])
    if path == 'info':
        model = KagomeModel(data['n'], halo=data['halo'])
        return {'profile': profile_info(data['profile'], data['norm']),
                'edges': [{'key': list(e), 'a': model.position(e[:3]), 'b': model.position(model.target(e)), 'inner': model.is_inner(e)} for e in model.edges]}
    if path == 'save':
        return {'id': workspace.save(data)}
    if path == 'source-settings':
        workspace.validate(data)
        return migrate_state_to_source(data)
    if path == 'from-occupancy':
        return {'V': flow_from_occupancy(float(data['n']), float(data['L']), float(data['v']))}
    if path == 'normalization':
        workspace.validate(data['state'])
        return convert_state_units(data['state'], data['norm'])
    if path == 'list':
        return workspace.history.cases(data)
    if path == 'load':
        return workspace.load(data['id'])
    if path == 'run':
        return workspace.run(data['state'], data.get('baseline'))
    if path == 'import':
        reader = csv.DictReader(io.StringIO(data['csv'].lstrip('\ufeff')))
        if reader.fieldnames != COLUMNS[data['table']]:
            raise ValueError('CSVの列と順序がテンプレートと一致しません')
        return list(reader)
    raise ValueError('操作が見つかりません')


def request(path, payload):
    return json.dumps(dispatch(path, json.loads(payload)), ensure_ascii=False, allow_nan=False)
