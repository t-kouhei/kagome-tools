"""開始時の入力を固定した一要因の感度分析。保存した個別解析の上に構成する。"""
from concurrent.futures import ThreadPoolExecutor
import copy
import csv
import ctypes
import json
import math
import os
from pathlib import Path
import threading
import zipfile

from .model import KagomeModel
from .workspace_history import atomic_json, timestamp, read_json, replace_file
from .provenance import code_identity, FORMULA_VERSION

PARAMETERS = {'m':'並列経路数 m', 'L':'素辺長 L', 'v':'輸送速度 v', 'V':'観測流量 V',
              'T':'分布の幅 T', 'mu':'臨界基準 μ', 'R':'右回りの割合', 'left':'左回りの割合', 'inflow_scale':'入口流入量の倍率'}


def variants(state, request):
    parameter, scope = request.get('parameter'), request.get('scope', 'all')
    values = request.get('values', [])
    if parameter not in PARAMETERS or scope not in ('all','inner','selected'):
        raise ValueError('変更する項目・範囲が不正です')
    if not isinstance(values,list) or not 2 <= len(values) <= 12:
        raise ValueError('比較する値は2～12個で指定してください')
    if any(type(value) not in (int,float) or not math.isfinite(value) for value in values) or len(set(values)) != len(values):
        raise ValueError('値は重複のない有限数で指定してください')
    if parameter=='V' and state['mode']!='observe':
        raise ValueError('Vの一括比較は観測流量の入力で使用してください')
    if parameter=='inflow_scale' and state['mode']!='propagate':
        raise ValueError('流入量の倍率は入口から計算する場合に使用してください')
    if parameter in ('R','left','inflow_scale') and scope!='all':
        raise ValueError('分岐割合・流入量倍率は全体を対象にしてください')
    model = KagomeModel(state['n'],halo=state['halo'])
    selected = tuple(request.get('edge', []))
    if scope=='selected' and selected not in model.index:
        raise ValueError('選択した素辺が格子にありません')
    keys = set(model.edges if scope=='all' else model.inner_edges if scope=='inner' else [selected])
    if not keys:
        raise ValueError('変更対象の素辺がありません')
    result = []
    for value in values:
        if value<0 or (parameter in ('m','L','v','T','mu') and value==0):
            raise ValueError('m・L・v・T・μは正の値、その他は0以上を指定してください')
        changed = copy.deepcopy(state)
        changed['name'] = f"{state.get('name','解析')} [{parameter}={value:g}]"
        if parameter=='inflow_scale':
            for row in changed['tables']['entrances']:
                row['inflow'] = str(float(row['inflow'])*value)
        elif parameter in ('R','left'):
            key = 'R' if parameter=='R' else 'L'
            other = 'L' if key=='R' else 'R'
            for row in changed['tables']['branching']:
                if value + float(row[other]) > 1+1e-12:
                    raise ValueError('指定した分岐割合と反対側の割合の合計が1を超えます')
                row[key] = str(value)
                row['S'] = str(max(0.,1-value-float(row[other])))
        else:
            for row in changed['tables']['edges']:
                key = (row['node_type'],int(row['i']),int(row['j']),int(row['road']))
                if key in keys:
                    row[parameter] = str(value)
        result.append(changed)
    return result


def summary(workspace, result, reference_net=None):
    folder = workspace.directory(result['id'])/'result'
    report = json.loads((folder/'report.json').read_text(encoding='utf-8'))
    with (folder/'edges_result.csv').open(encoding='utf-8',newline='') as stream:
        edges = [row for row in csv.DictReader(stream) if row['inner']=='1']
    rotations = []
    if (folder/'hex_rotation.csv').exists():
        with (folder/'hex_rotation.csv').open(encoding='utf-8',newline='') as stream:
            rotations = list(csv.DictReader(stream))
    means = {}
    for component in ('cw','ccw','net'):
        vals = [float(row['now']) for row in rotations if row['component']==component]
        means[component] = math.fsum(vals)/len(vals) if vals else None
    standard = report.get('standard',{}).get('hex_rotation',{}).get('standard_mean') or {}
    ratios = [float(row['usage']) for row in edges if row.get('usage') not in (None,'') and math.isfinite(float(row['usage']))]
    scopes = report.get('direction_comparison',{}).get('scopes',{}).get('inner',{})
    return {'status':'unresolved' if result.get('adjustment_resolved') is False else 'ok',
            'result_id':result['id'], 'url':result['url'], 'archive_url':result['archive_url'],
            'mean_j':math.fsum(float(row['J']) for row in edges)/len(edges) if edges else None,
            'hex_cw_mean':means['cw'], 'hex_ccw_mean':means['ccw'], 'hex_net_mean':means['net'],
            'fixed_reference_difference':means['net']-reference_net if means['net'] is not None and reference_net is not None else None,
            'own_standard_net_mean':standard.get('net'), 'max_usage':max(ratios) if ratios else None,
            'over_capacity_edges':sum(row['over_capacity_edges'] for row in scopes.values()) if scopes else None,
            'input_sha256':report['provenance']['input_sha256'],
            'engine_sha256':report['provenance']['engine_sha256'],
            'error':result.get('adjustment_reason') if result.get('adjustment_resolved') is False else None}


def alive(pid):
    if not isinstance(pid,int) or pid<=0:return False
    if os.name=='nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False
        try:
            code=wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


class SweepManager:
    def __init__(self, workspace):
        self.workspace=workspace
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='sweep')
        self.ids=set()
        self.lock=threading.Lock()

    def start(self, state, request):
        self.workspace.validate(state)
        changed=variants(state,request)
        identifier=self.workspace.save(state)
        folder=self.workspace.directory(identifier)
        document={'schema_version':1,'id':identifier,'profile':state['profile'],'name':state.get('name','解析'),
                  'created_at':timestamp(),'pid':os.getpid(),'status':'queued','completed':0,'total':len(changed),
                  'request':copy.deepcopy(request),'reference':None,'cases':[],
                  'note':'開始時の入力を固定し、一項目を置き換える。基準差は開始時の標準平均を固定。'
                         '集計は内側の完全な六角形と内側の有向素辺。表示はCSVの丸め値に基づく。'}
        from . import __version__
        document['software_version']=__version__
        document['formula_version']=FORMULA_VERSION
        document['implementation']=code_identity()
        self._write(document)
        self.workspace.history.metadata(identifier,state,kind='sweep',has_sweep=True)
        with self.lock:self.ids.add(identifier)
        self.pool.submit(self._run,document,copy.deepcopy(state),changed)
        return self.status(identifier)

    def _write(self, document):
        folder=self.workspace.directory(document['id'])
        document['updated_at']=timestamp()
        atomic_json(folder/'sweep.json',document)
        template=(Path(__file__).parent/'sweep.html').read_text(encoding='utf-8')
        page=template.replace('__SWEEP_DATA__',json.dumps(document,ensure_ascii=False).replace('<','\\u003c'))
        (folder/'sweep.html.tmp').write_text(page,encoding='utf-8')
        replace_file(folder/'sweep.html.tmp',folder/'sweep.html')
        columns=('value','status','mean_j','hex_cw_mean','hex_ccw_mean','hex_net_mean','fixed_reference_difference','own_standard_net_mean','max_usage','over_capacity_edges','input_sha256','error')
        with (folder/'summary.csv.tmp').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(document['cases'])
        replace_file(folder/'summary.csv.tmp',folder/'summary.csv')

    def _run(self, document, state, changed):
        folder=self.workspace.directory(document['id'])
        try:
            document['status']='running';self._write(document)
            if (folder/'cancel.request').exists():
                document['status']='cancelled';return
            base_result=self.workspace.run(state)
            base=summary(self.workspace,base_result)
            document['reference']=base
            reference_net=base.get('own_standard_net_mean')
            self._write(document)
            for value, variant in zip(document['request']['values'],changed):
                if (folder/'cancel.request').exists():
                    document['status']='cancelled';break
                try:
                    result=self.workspace.run(variant)
                    row={'value':value,**summary(self.workspace,result,reference_net)}
                except Exception as error:
                    row={'value':value,'status':'error','error':str(error)}
                document['cases'].append(row)
                document['completed']=len(document['cases'])
                self._write(document)
            else:
                document['status']='completed_with_errors' if any(row['status']=='error' for row in document['cases']) else 'completed'
        except Exception as error:
            document.update(status='failed',error=str(error))
        finally:
            self._write(document)
            try:self._archive(document)
            except Exception as error:
                document['archive_error']=str(error);self._write(document)
            with self.lock:self.ids.discard(document['id'])

    def _archive(self, document):
        folder=self.workspace.directory(document['id'])
        temporary=folder/'sweep.building'
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('sweep.html','sweep.json','summary.csv','state.json'):
                archive.write(folder/name,name)
            records=[('reference',document.get('reference'))]+[(f'cases/{i+1:02d}',row) for i,row in enumerate(document['cases'])]
            for prefix, record in records:
                if not record or not record.get('result_id'):continue
                source=self.workspace.directory(record['result_id'])
                for path in source.rglob('*'):
                    if path.is_file() and path.name!='analysis.zip':archive.write(path,prefix+'/'+path.relative_to(source).as_posix())
        replace_file(temporary,folder/'sweep.zip')

    def status(self, identifier):
        folder=self.workspace.directory(identifier)
        path=folder/'sweep.json'
        if not path.exists():return None
        document=read_json(path)
        if document['status'] in ('queued','running') and not alive(document.get('pid')):
            document.update(status='interrupted',error='前の実行プロセスが停止しました。完了済みの結果は残っています。同じ条件で新しく実行できます。')
            self._write(document)
        document['url']=f'/files/{identifier}/sweep.html'
        document['csv_url']=f'/files/{identifier}/summary.csv'
        document['archive_url']=f'/files/{identifier}/sweep.zip' if (folder/'sweep.zip').exists() else None
        document['cancel_requested']=(folder/'cancel.request').exists()
        document['archiving']=document['status'] in ('completed','completed_with_errors','cancelled','failed') and not document['archive_url'] and not document.get('archive_error')
        if document['archiving'] and not alive(document.get('pid')):
            document['archiving']=False
            document['archive_error']='ZIP作成中に実行プロセスが停止しました。各条件の結果は個別に開けます。'
        return document

    def cancel(self, identifier):
        document=self.status(identifier)
        if document is None:raise ValueError('一括比較が見つかりません')
        if document['status'] in ('queued','running'):
            (self.workspace.directory(identifier)/'cancel.request').write_text('cancel',encoding='utf-8')
        return self.status(identifier)

    def close(self):
        with self.lock:
            for identifier in self.ids:
                document=self.status(identifier)
                if document and document['status'] in ('queued','running'):
                    (self.workspace.directory(identifier)/'cancel.request').write_text('cancel',encoding='utf-8')
        self.pool.shutdown(wait=False,cancel_futures=True)
