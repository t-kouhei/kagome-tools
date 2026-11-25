"""保存ケースの一覧と、タブごとの復元用退避。入力のスナップショットとは別に扱う。"""
from datetime import datetime, timedelta, timezone
import json
import os
import threading
import time
import uuid

JST = timezone(timedelta(hours=9))


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def retry_file_access(operation):
    """Windowsの短い共有・置換ロックだけを有限回待つ。永続的な失敗は呼出元へ返す。"""
    for attempt in range(6):
        try:
            return operation()
        except PermissionError:
            if attempt==5:
                raise
            time.sleep(.01*2**attempt)


def read_json(path):
    return retry_file_access(lambda: json.loads(path.read_text(encoding='utf-8')))


def replace_file(source, target):
    return retry_file_access(lambda: os.replace(source, target))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        replace_file(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class WorkspaceHistory:
    def __init__(self, workspace):
        self.workspace = workspace
        self.sessions = workspace.root / 'sessions'
        self.lock = threading.RLock()

    def metadata(self, identifier, state=None, **extra):
        directory = self.workspace.directory(identifier)
        path = directory / 'case.json'
        if path.exists():
            item = read_json(path)
        else:
            state = state or self.workspace.load(identifier)
            stamp = datetime.fromtimestamp((directory/'state.json').stat().st_mtime, timezone.utc).isoformat()
            item = {'id': identifier, 'name': state.get('name', identifier), 'profile': state['profile'],
                    'n': state['n'], 'mode': state['mode'], 'created_at': stamp}
        item.update(extra)
        if extra or not path.exists():
            atomic_json(path, item)
        return item

    def cases(self, filters):
        profile, query = filters.get('profile', 'all'), filters.get('query', '').casefold().strip()
        if profile not in ('all', 'patent', 'traffic'):
            raise ValueError('一覧の版が不正です')
        dates = {}
        for key in ('from', 'to'):
            if filters.get(key):
                dates[key] = datetime.strptime(filters[key], '%Y-%m-%d').date()
        if dates.get('from') and dates.get('to') and dates['from'] > dates['to']:
            raise ValueError('保存日の開始日は終了日以前にしてください')
        rows = []
        for path in self.workspace.root.glob('*/state.json'):
            try:
                item = self.metadata(path.parent.name)
                date = datetime.fromisoformat(item['created_at']).astimezone(JST).date()
            except (ValueError, KeyError, OSError, TypeError):
                continue  # 壊れた個別ケースで他のケースまで読み込めなくしない
            if profile != 'all' and item['profile'] != profile:
                continue
            if query and query not in item['name'].casefold():
                continue
            if ('from' in dates and date < dates['from']) or ('to' in dates and date > dates['to']):
                continue
            rows.append(item)
        return sorted(rows, key=lambda item: (item['created_at'], item['id']), reverse=True)

    def result(self, identifier):
        directory = self.workspace.directory(identifier)
        for relative in ('result/scenario/viewer.html', 'result/viewer.html'):
            if (directory/relative).is_file():
                report = json.loads((directory/relative.replace('viewer.html', 'report.json')).read_text(encoding='utf-8'))
                local = report.get('operations', {}).get('local', {})
                return {'id': identifier, 'url': f'/files/{identifier}/{relative}',
                        'archive_url': f'/files/{identifier}/analysis.zip', 'log': '',
                        'adjustment_resolved': local.get('resolved'), 'adjustment_reason': local.get('stop_reason')}
        return None

    def duplicate(self, identifier, name=None):
        state = self.workspace.load(identifier)
        state['name'] = str(name or (state.get('name', '解析') + ' のコピー')).strip()[:200]
        if not state['name']:
            raise ValueError('複製するケースの名前を入力してください')
        copied = self.workspace.save(state)
        self.metadata(copied, state, source_id=identifier, kind='duplicate')
        return {'id': copied, 'state': state}

    def session_path(self, identifier):
        if str(uuid.UUID(identifier)) != identifier:
            raise ValueError('作業の復元番号が不正です')
        return self.sessions / (identifier + '.json')

    def store_draft(self, data):
        with self.lock:
            path = self.session_path(data['session_id'])
            self.workspace.validate(data['state'])  # 数値が未完成でも構造が正しければ退避する
            revision = data['revision']
            if type(revision) is not int or revision < 0:
                raise ValueError('作業の更新番号が不正です')
            if path.exists():
                before = read_json(path)
                if revision <= before['revision']:
                    return {'revision': before['revision'], 'updated_at': before['updated_at'], 'stale': True}
            document = {key: data.get(key) for key in ('session_id', 'state', 'revision', 'dirty', 'baseline', 'view', 'result_id')}
            document['updated_at'] = timestamp()
            atomic_json(path, document)
            for pointer in ('latest.json', f"latest-{data['state']['profile']}.json"):
                atomic_json(self.sessions/pointer, {'session_id': data['session_id']})
            return {'revision': revision, 'updated_at': document['updated_at'], 'stale': False}

    def startup(self, profile='auto', identifier=None):
        if profile not in ('auto', 'patent', 'traffic'):
            raise ValueError('版が不正です')
        if identifier:
            self.session_path(identifier)
        with self.lock:
            source = identifier
            if not source:
                pointer = self.sessions/('latest.json' if profile == 'auto' else f'latest-{profile}.json')
                if pointer.exists():
                    try:
                        source = read_json(pointer)['session_id']
                    except (ValueError, KeyError, OSError):
                        source = None
            document = None
            warning = None
            if source:
                try:
                    document = read_json(self.session_path(source))
                    self.workspace.validate(document['state'])
                except (ValueError, KeyError, OSError, TypeError):
                    warning = '退避した作業を読めなかったため、新しい作業を開きました。保存済みケースはそのまま残っています。'
                    document = None
            if document:
                # 新しいタブ・起動では別番号へ分岐し、別タブの編集を上書きしない。
                active = identifier or str(uuid.uuid4())
                if warning:
                    active = str(uuid.uuid4())
                document['session_id'] = active
                atomic_json(self.session_path(active), document)
                return {'session_id': active, 'source_session_id': source, 'draft': document}
            return {'session_id': str(uuid.uuid4()), 'draft': None, 'warning': warning}
