'use strict';
const $=id=>document.getElementById(id);
const clone=value=>JSON.parse(JSON.stringify(value));
const arrows={1:'→',2:'↗',3:'↖',4:'←',5:'↙',6:'↘'};
const edgeName=row=>`${row.node_type}(${row.i},${row.j})`;
const keyName=row=>`${edgeName(row)} · 向き${row.road??row.in_road} ${arrows[row.road??row.in_road]||''}`;
let state,info,selected=0,baseline=null,baselineName='',busy=false,dirty=false;
let history=[],future=[],checkpoint='',savedCheckpoint='',page=0,zoom=1,issues=[];
const pageSize=60;
let currentSweepId=null,sweepTimer=null,sweepRunning=false,sweepCancelable=false,exampleCatalog=[];
let demonstrationStage=0,demonstrationExpected='';
$('profile').value=INITIAL_PROFILE==='auto'?'patent':INITIAL_PROFILE;
let sessionId=null,draftReady=false,draftRevision=0,draftSerial='',draftPending=null,draftTimer=null,draftSending=false,lastResult=null;

function status(message,error=false){$('status').textContent=message;$('notice').classList.toggle('error',error);$('statusIcon').textContent=error?'!':'i';}
async function api(path,data){const response=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Kagome-Token':API_TOKEN},body:JSON.stringify(data)});let value;try{value=await response.json();}catch{throw Error('サーバーに接続できません。起動用のコンソールを確認してください。');}if(!response.ok)throw Error(value.error||'操作に失敗しました');return value;}
function updateControls(){
  $('compare').disabled=busy||!baseline;$('compare').title=baseline?'変更前と現在の入力を比較します':'先に変更前の入力を固定してください';
  $('undo').disabled=busy||!history.length;$('redo').disabled=busy||!future.length;
  if($('demoNext'))$('demoNext').disabled=busy||demonstrationStage>=4;
  if(!state)return;
  updateSweepControls();
  for(const k of ['global_rule','local_rule'])$(k).disabled=busy||state.mode==='observe';
  const v=$('fields').querySelector('[aria-label="V"]');if(v)v.disabled=busy||state.mode==='propagate';
  document.querySelectorAll('#grid input[data-key="V"]').forEach(input=>input.disabled=busy||state.mode==='propagate');
  const count=filteredRows().length;$('prevPage').disabled=busy||page===0;$('nextPage').disabled=busy||(page+1)*pageSize>=count;
  $('saveState').textContent=dirty?'未保存の変更あり':'編集内容を保持';$('saveState').classList.toggle('unsaved',dirty);
}
async function action(fn){if(busy)return;busy=true;document.body.classList.add('busy');$('app').setAttribute('aria-busy','true');document.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);try{await fn();}catch(error){status(error.message,true);}finally{busy=false;document.body.classList.remove('busy');$('app').setAttribute('aria-busy','false');document.querySelectorAll('button,input,select').forEach(el=>el.disabled=false);updateControls();queueDraft();}}
function sync(){for(const k of ['mode','norm','tau','name','global_rule','local_rule'])state[k]=$(k).value;state.theta=$('theta').value===''?null:Number($('theta').value);return state;}
function resetHistory(){history=[];future=[];checkpoint=JSON.stringify(state);savedCheckpoint=checkpoint;dirty=false;updateControls();}
function record(){const value=JSON.stringify(state);if(checkpoint&&value!==checkpoint){history.push(checkpoint);if(history.length>20)history.shift();future=[];}checkpoint=value;dirty=value!==savedCheckpoint;}
function hideResult(label='入力を変更・再解析してください'){lastResult=null;$('toggleLog').hidden=true;$('runLog').hidden=true;$('result').hidden=true;$('result').removeAttribute('src');$('resultLink').hidden=true;$('archiveLink').hidden=true;$('resultSummary').hidden=true;$('resultEmpty').hidden=false;$('resultState').textContent=label;$('resultState').className='tag';$('identityPanel').hidden=true;}
function clearBaseline(){baseline=null;baselineName='';$('baseLabel').textContent='変更前は未設定';updateControls();}
function changed(message='入力を変更しました。再解析すると新しい条件の結果を確認できます。'){record();hideResult();validate();renderOverview();updateControls();status(message);queueDraft();}
function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function renderOverview(){
  $('activeProfile').textContent=info.profile.name;$('edgeCount').textContent=`${info.edges.filter(e=>e.inner).length} 本`;$('sizeSummary').textContent=`${state.n} × ${state.n}`;
  $('modeSummary').textContent=state.mode==='observe'?'素辺の観測流量':'入口から計算';
  $('modeHint').textContent=state.mode==='observe'?'全素辺のVを入力します。入口から説明できない分も結果で確認できます。':'入口表のinflowと分岐割合からVを計算します。素辺表のVは使用しません。';
  $('canvasBadge').textContent=`N = ${state.n} · ${state.halo?'余白あり':'余白なし'}`;
  $('mapMetric').options[1].textContent=state.profile==='traffic'?'車線数 m':'並列経路数 m';
}
function selectEdge(index,{focus=false}={}){if(busy)return;selected=Math.max(0,Math.min(index,state.tables.edges.length-1));$('edgeSelect').value=String(selected);fields();map();grid();if(focus)$('map').querySelector('[tabindex="0"]')?.focus();updateSweepControls();queueDraft();}
function fields(){
  const row=state.tables.edges[selected];$('fields').replaceChildren();$('occupancyFields').replaceChildren();if(!row)return;
  $('edgeTitle').textContent=`${edgeName(row)} ${arrows[row.road]||''} ${row.road}`;
  const edge=info.edges.find(e=>e.key.every((value,i)=>String(value)===String([row.node_type,row.i,row.j,row.road][i])));
  $('edgeScope').textContent=edge?.inner?'解析範囲':'余白';$('edgeDescription').textContent=state.mode==='observe'?'選んだ有向素辺の観測条件を入力します。':'Vは入口の条件から求めます。その他の条件を入力してください。';
  for(const key of ['m','L','v','V','T','mu']){
    const p=info.profile.parameters[key],label=document.createElement('label');label.className='field';const title=document.createElement('span');title.textContent=p.label;
    const symbol=document.createElement('span');symbol.className='field-symbol';symbol.textContent=key==='mu'?'μ':key;title.append(symbol);
    const unit=document.createElement('small');unit.textContent=p.unit;title.append(unit);label.title=p.meaning||'';
    const input=document.createElement('input');input.type='number';input.step='any';input.disabled=busy;input.value=row[key];input.setAttribute('aria-label',key);input.setAttribute('aria-invalid',String(issues.some(x=>x.table==='edges'&&x.index===selected&&x.key===key)));
    input.oninput=()=>{row[key]=input.value;queueDraft(true);};input.onchange=()=>{row[key]=input.value;changed();grid();map();};label.append(title,input);$('fields').append(label);
  }
  const n=document.createElement('input');n.type='number';n.step='any';n.min='0';n.setAttribute('aria-label','素片内の量 n');n.placeholder='素片内の量 n';if(row.V!==''&&Number(row.v)>0)n.value=Number(row.V)*Number(row.L)/Number(row.v);
  const button=document.createElement('button');button.className='secondary';button.textContent='nから流量Vに換算';button.onclick=()=>action(async()=>{sync();if(state.mode!=='observe')throw Error('入力方法を「各素辺の観測流量を使う」に切り替えてください。');if(n.value==='')throw Error('素片内の量nを入力してください');const value=await api('from-occupancy',{n:Number(n.value),L:Number(row.L),v:Number(row.v)});row.V=String(value.V);changed('nからVへ換算しました。必要な他の素辺も入力してください。');fields();grid();});$('occupancyFields').append(n,button);
  $('unitNote').textContent='単位は素辺ごとにそろえてください。版を変更しても数値の自動換算は行いません。';updateControls();
}
function map(){
  const svg=$('map'),ns='http://www.w3.org/2000/svg';svg.replaceChildren();if(!info.edges.length)return;
  const coords=info.edges.flatMap(e=>[e.a,e.b]),xs=coords.map(p=>p[0]),ys=coords.map(p=>-p[1]);
  const x=Math.min(...xs)-.7,y=Math.min(...ys)-.7,w=Math.max(...xs)-x+.7,h=Math.max(...ys)-y+.7;
  const chosen=info.edges.find(e=>e.key.every((v,i)=>String(v)===String([state.tables.edges[selected].node_type,state.tables.edges[selected].i,state.tables.edges[selected].j,state.tables.edges[selected].road][i])));
  const cx=zoom>1&&chosen?(chosen.a[0]+chosen.b[0])/2:x+w/2,cy=zoom>1&&chosen?-(chosen.a[1]+chosen.b[1])/2:y+h/2;
  svg.setAttribute('viewBox',`${cx-w/zoom/2} ${cy-h/zoom/2} ${w/zoom} ${h/zoom}`);$('zoomLevel').textContent=`${Math.round(zoom*100)}%`;
  const metric=$('mapMetric').value,values=state.tables.edges.map(r=>Number(r[metric])).filter(Number.isFinite),lo=Math.min(...values),hi=Math.max(...values);
  $('mapRange').textContent=metric==='network'?'有向素辺ごとに入力':`${metric}: ${lo.toLocaleString()} 〜 ${hi.toLocaleString()}`;
  const indexByKey=new Map(state.tables.edges.map((r,i)=>[[r.node_type,r.i,r.j,r.road].map(String).join(','),i]));
  for(const edge of info.edges){
    const index=indexByKey.get(edge.key.map(String).join(',')),[ax,ay]=edge.a,[bx,by]=edge.b,dx=bx-ax,dy=by-ay,len=Math.hypot(dx,dy),ux=dx/len,uy=dy/len,ox=-uy*.075,oy=ux*.075;
    let color=edge.inner?'#258a88':'#c6d7dd';if(metric!=='network'&&edge.inner){const value=Number(state.tables.edges[index][metric]),t=hi===lo?.6:(value-lo)/(hi-lo);color=`hsl(177 48% ${70-39*Math.max(0,Math.min(1,t))}%)`;}
    if(index===selected)color='#d87936';const group=document.createElementNS(ns,'g');group.classList.add('edge-shape');group.setAttribute('role','button');group.setAttribute('tabindex',index===selected?'0':'-1');group.setAttribute('aria-label',keyName(state.tables.edges[index]));group.setAttribute('aria-pressed',String(index===selected));group.dataset.index=index;
    function line(attrs){const el=document.createElementNS(ns,'line');for(const [k,v]of Object.entries(attrs))el.setAttribute(k,v);return el;}
    const points={x1:ax+.14*dx+ox,y1:-(ay+.14*dy+oy),x2:ax+.86*dx+ox,y2:-(ay+.86*dy+oy)};
    group.append(line({...points,stroke:'transparent','stroke-width':.27}));const visible=line({...points,stroke:color,'stroke-width':index===selected?.1:.055,'stroke-linecap':'round'});visible.classList.add('visible-edge');group.append(visible);
    const tip=document.createElementNS(ns,'polygon'),tx=points.x2,ty=points.y2;tip.setAttribute('points',`${tx},${ty} ${tx-.17*ux-.075*uy},${ty+.17*uy-.075*ux} ${tx-.17*ux+.075*uy},${ty+.17*uy+.075*ux}`);tip.setAttribute('fill',color);tip.setAttribute('pointer-events','none');group.append(tip);
    const title=document.createElementNS(ns,'title');title.textContent=keyName(state.tables.edges[index]);group.append(title);group.onclick=()=>selectEdge(index);
    group.onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();selectEdge(index,{focus:true});}else if(['ArrowRight','ArrowDown','ArrowLeft','ArrowUp'].includes(event.key)){event.preventDefault();selectEdge(index+(['ArrowRight','ArrowDown'].includes(event.key)?1:-1),{focus:true});}};svg.append(group);
  }
}
function filteredRows(){if(!state)return[];const row=state.tables.edges[selected],q=$('tableSearch').value.trim().toLowerCase().replaceAll(' ','');return state.tables[$('table').value].map((r,index)=>({row:r,index})).filter(({row:r})=>{
  if($('linkedRows').checked&&[r.node_type,r.i,r.j].map(String).join(',')!==[row.node_type,row.i,row.j].map(String).join(','))return false;
  return !q||`${edgeName(r)}向き${r.road??r.in_road} ${[r.node_type,r.i,r.j,r.road??r.in_road].join(',')}`.toLowerCase().replaceAll(' ','').includes(q);
});}
function grid(){
  const kind=$('table').value,rows=state.tables[kind],filtered=filteredRows(),columns=Object.keys(rows[0]||{});page=Math.min(page,Math.max(0,Math.ceil(filtered.length/pageSize)-1));const visible=filtered.slice(page*pageSize,(page+1)*pageSize);
  const old=$('bulkColumn').value;$('bulkColumn').replaceChildren(...columns.slice(4).map(key=>new Option(key,key)));if(columns.slice(4).includes(old))$('bulkColumn').value=old;
  $('bulkApply').textContent=$('bulkScope').value==='all'?'全行に適用（余白を含む）':`絞り込んだ${filtered.length}行に適用`;
  const names={node_type:'節点',i:'位置 i',j:'位置 j',road:'進む向き',in_road:'入ってくる向き',S:'直進',R:'右回り',inflow:'入口の流入量'};
  if(kind==='edges')for(const [key,p]of Object.entries(info.profile.parameters))names[key]=p.label;else if(kind==='branching')names.L='左回り';
  const table=document.createElement('table'),thead=table.createTHead(),head=thead.insertRow();for(const key of ['#',...columns]){const th=document.createElement('th');th.scope='col';th.textContent=names[key]||key;if(names[key]&&names[key]!==key){const small=document.createElement('small');small.textContent=key;th.append(small);}head.append(th);}
  const body=table.createTBody();for(const {row,index}of visible){const tr=body.insertRow();if(kind==='edges'&&index===selected)tr.classList.add('selected-row');const counter=tr.insertCell();counter.className='row-index';counter.textContent=index+1;
    for(const [col,key]of columns.entries()){const td=tr.insertCell();if(col<4){if(col===0){const select=document.createElement('button');select.className='row-select';select.textContent=row[key];select.title='この節点を格子で選ぶ';select.onclick=()=>{const edgeIndex=kind==='edges'?index:state.tables.edges.findIndex(r=>edgeName(r)===edgeName(row));if(edgeIndex>=0)selectEdge(edgeIndex);};td.append(select);}else td.textContent=key==='road'||key==='in_road'?`${row[key]} ${arrows[row[key]]||''}`:row[key];continue;}
      const input=document.createElement('input');input.type='number';input.step='any';input.disabled=busy;input.value=row[key];input.dataset.key=key;input.dataset.table=kind;input.dataset.index=index;input.setAttribute('aria-label',`${kind}-${index}-${key}`);input.setAttribute('aria-invalid',String(issues.some(x=>x.table===kind&&x.index===index&&(x.key===key||x.key==='branch'))));input.oninput=()=>{row[key]=input.value;queueDraft(true);};input.onchange=()=>{row[key]=input.value;changed();input.setAttribute('aria-invalid',String(issues.some(x=>x.table===kind&&x.index===index&&(x.key===key||x.key==='branch'))));if(kind==='edges'&&index===selected)fields();map();};td.append(input);
    }
  }
  if(!visible.length){const tr=body.insertRow(),td=tr.insertCell();td.colSpan=columns.length+1;td.textContent='一致する行がありません。検索条件を変更してください。';}
  $('grid').replaceChildren(table);$('rowCount').textContent=`${rows.length.toLocaleString()} 行`;const start=filtered.length?page*pageSize+1:0;$('pageSummary').textContent=`${start}–${Math.min((page+1)*pageSize,filtered.length)} / ${filtered.length.toLocaleString()} 行${filtered.length!==rows.length?'（絞込中）':''}`;
  $('tableHelp').textContent=kind==='branching'?'各行の S＋R＋L＝1。Lは左回りの割合です。':kind==='edges'?'場所の列は固定。素辺のLは長さです。':'入口の場所ごとに、単位時間あたりの総流入量を入力します。';updateControls();
}
function validate(){
  issues=[];function add(table,index,key,message){issues.push({table,index,key,message});}
  for(const [index,row]of state.tables.edges.entries())for(const key of ['m','L','v','V','T','mu']){
    const blank=row[key]===''||row[key]===null,value=Number(row[key]),required=['m','L'].includes(key)||(key==='v'&&state.norm!=='m')||(key==='V'&&state.mode==='observe');
    if(key==='V'&&state.mode!=='observe')continue;
    if(blank){if(required)add('edges',index,key,`${key}が未入力です`);continue;}
    if(!Number.isFinite(value))add('edges',index,key,`${key}に有限の数値を入力してください`);
    else if(['m','L','v','T','mu'].includes(key)&&value<=0)add('edges',index,key,`${key}は正の値で入力してください`);
    else if(key==='V'&&value<0)add('edges',index,key,'Vは0以上で入力してください');
  }
  for(const [index,row]of state.tables.branching.entries()){
    const nums=['S','R','L'].map(key=>row[key]===''?NaN:Number(row[key]));if(nums.some(v=>!Number.isFinite(v)||v<0)||Math.abs(nums.reduce((a,b)=>a+b,0)-1)>1e-6)add('branching',index,'branch','S・R・Lは0以上、合計1にそろえてください');
  }
  if(state.mode==='propagate')for(const [index,row]of state.tables.entrances.entries())if(row.inflow===''||!Number.isFinite(Number(row.inflow))||Number(row.inflow)<0)add('entrances',index,'inflow','流入量は0以上の数値を入力してください');
  const theta=Number(state.theta),validTheta=Number.isFinite(theta)&&theta>0&&theta<1;
  if(!validTheta)add('settings',0,'theta','θは0と1の間にしてください');
  if(validTheta)for(const [index,row]of state.tables.edges.entries()){
    if(row.mu===''||row.T==='')continue;const mu=Number(row.mu),T=Number(row.T);
    if(!Number.isFinite(mu)||!Number.isFinite(T)||mu<=0||T<=0)continue;
    const critical=mu+T*(Math.log(theta)-Math.log1p(-theta));
    if(!Number.isFinite(critical)||critical<=0)add('edges',index,'mu','臨界量ε*が0以下または非有限です。μ・T・θを変更してください（基本設定θ=0.5）');
  }
  $('validationBadge').textContent=issues.length?`入力の確認 ${issues.length}件`:'基本入力にエラーなし';$('validationBadge').className='tag '+(issues.length?'error':'ok');$('validationPanel').hidden=!issues.length;$('validationTitle').textContent=`${issues.length}件の入力を確認してください`;
  $('validationIssues').replaceChildren(...issues.slice(0,12).map(issue=>{const li=document.createElement('li'),button=document.createElement('button');const row=state.tables[issue.table]?.[issue.index];button.textContent=`${row?keyName(row):'計算設定'}：${issue.message}`;button.onclick=()=>{if(issue.table==='settings'){$('theta').focus();return;}$('table').value=issue.table;$('tableSearch').value='';$('linkedRows').checked=false;page=Math.floor(issue.index/pageSize);grid();$('dataSection').scrollIntoView({behavior:'smooth'});$('grid').querySelector(`[aria-label="${issue.table}-${issue.index}-${issue.key==='branch'?'S':issue.key}"]`)?.focus();};li.append(button);return li;}));
  if(issues.length>12){const li=document.createElement('li');li.textContent=`ほか${issues.length-12}件。同じ項目の一括入力も利用できます。`;$('validationIssues').append(li);}
  for(const input of $('grid').querySelectorAll('input[data-key]'))input.setAttribute('aria-invalid',String(issues.some(x=>x.table===input.dataset.table&&x.index===Number(input.dataset.index)&&(x.key===input.dataset.key||x.key==='branch'))));
  $('readyLabel').textContent=issues.length?'入力を修正してから解析':'現在の条件で解析';
  for(const input of $('fields').querySelectorAll('input[aria-label]'))input.setAttribute('aria-invalid',String(issues.some(x=>x.table==='edges'&&x.index===selected&&x.key===input.getAttribute('aria-label'))));
}
async function refresh({reset=false}={}){
  state.global_rule??='none';state.local_rule??='none';info=await api('info',state);for(const k of ['profile','n','halo','mode','norm','tau','theta','name','global_rule','local_rule']){if(k==='halo')$(k).checked=state[k];else $(k).value=state[k];}
  if(reset){selected=state.tables.edges.findIndex(r=>edgeName(r)==='C(2,2)'&&Number(r.road)===1);if(selected<0)selected=info.edges.findIndex(e=>e.inner);selected=Math.max(0,selected);zoom=1;page=0;$('tableSearch').value='';$('linkedRows').checked=false;}
  selected=Math.min(selected,state.tables.edges.length-1);$('edgeSelect').replaceChildren(...state.tables.edges.map((row,index)=>new Option(keyName(row),String(index))));$('edgeSelect').value=String(selected);
  $('tau').options[0].textContent=state.norm==='m'?'原資料形：jから計算':'規格化量Jから（比較用）';$('formulaNote').textContent=state.norm==='m'&&state.tau==='engine'?'j = V/m　　τ = j_in × β × L_in / (m_out × L_out)':'比較用の計算設定です。規格化の変更に合わせてμ・Tも換算します。';
  $('app').hidden=false;hideResult(reset?'未解析':'再解析が必要');renderOverview();validate();fields();map();grid();if(reset)resetHistory();updateControls();
}
async function list(){const filters={profile:$('caseProfile').value,query:$('caseQuery').value,from:$('caseFrom').value,to:$('caseTo').value},items=await api('list',filters),selectedId=$('saved').value;$('saved').replaceChildren(new Option('保存済みの入力',''));for(const item of items){const date=new Date(item.created_at).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});$('saved').add(new Option(`${item.name} / ${item.profile==='traffic'?'交通版':'特許版'} / ${date} / ${item.id.slice(0,8)}${item.has_result?' / 結果あり':item.has_sweep?' / 一括比較あり':''}`,item.id));}if(items.some(item=>item.id===selectedId))$('saved').value=selectedId;$('caseCount').textContent=`${items.length}件の保存ケース（保存日は日本時間）`;}
async function selectSaved(id){$('caseProfile').value='all';$('caseQuery').value='';$('caseFrom').value='';$('caseTo').value='';await list();$('saved').value=id;}
$('caseSearch').onclick=()=>action(list);$('caseReset').onclick=()=>action(async()=>{await selectSaved($('saved').value);});$('caseQuery').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();action(list);}};
async function undo(redo=false){if(redo?!future.length:!history.length)return;const current=JSON.stringify(state);if(redo){history.push(current);state=JSON.parse(future.pop());}else{future.push(current);state=JSON.parse(history.pop());}checkpoint=JSON.stringify(state);dirty=checkpoint!==savedCheckpoint;const previous=JSON.parse(current);if(['n','halo','profile','mode','norm','tau','theta'].some(k=>previous[k]!==state[k]))clearBaseline();await refresh();status(redo?'変更をやり直しました。':'直前の変更を元に戻しました。');}
async function replaceState(incoming){state=incoming;clearBaseline();await refresh({reset:true});}
function acceptReplace(message){return !dirty||confirm(message);}

$('new').onclick=()=>action(async()=>{if(!acceptReplace('未保存の編集を新しい入力で置き換えますか？'))return;const incoming=await api('init',{n:Number($('n').value),halo:$('halo').checked,profile:state.profile});await replaceState(incoming);await list();status('合成例を読み込みました。実際の条件に合わせて編集してください。');});
$('tutorial').onclick=()=>action(async()=>{if(!acceptReplace('未保存の編集を練習例で置き換えますか？'))return;await replaceState(await api('tutorial',{profile:state.profile}));status('解説書の練習例です。m=2、V=1600。解析するとj=800、内側の六角形は右600・左360になります。');});
$('save').onclick=()=>action(async()=>{const result=await api('save',sync());savedCheckpoint=JSON.stringify(state);dirty=false;await selectSaved(result.id);status('入力を保存しました。保存済みの入力からいつでも読み込めます。');});
$('load').onclick=()=>action(async()=>{if(!$('saved').value)throw Error('読み込む入力を選んでください');if(!acceptReplace('未保存の編集を置き換えますか？'))return;const id=$('saved').value;await replaceState(await api('load',{id}));const previous=await api('result',{id,state});if(previous)await displayResult(previous);const batch=await api('sweep-status',{id});if(batch)await showSweep(id,batch);status(previous?'保存済みの入力と解析結果を読み込みました。':'保存済みの入力を読み込みました。');});
$('duplicate').onclick=()=>action(async()=>{const id=$('saved').value;if(!id)throw Error('複製する保存ケースを選んでください');if(!acceptReplace('未保存の編集を複製したケースで置き換えますか？'))return;const copy=await api('duplicate',{id});await replaceState(copy.state);await selectSaved(copy.id);status('元のケースを残し、複製した入力を開きました。名前や条件を変えて保存できます。');});
$('download').onclick=()=>download('kagome-input.json',JSON.stringify(sync(),null,2),'application/json');
$('upload').onchange=()=>action(async()=>{const file=$('upload').files[0];if(!file)return;if(!acceptReplace('未保存の編集を読み込むJSONで置き換えますか？'))return;const incoming=JSON.parse(await file.text());await api('save',incoming);await replaceState(incoming);await list();status('入力一式を読み込み、保存しました。');$('upload').value='';});
$('csvOut').onclick=()=>{const key=$('table').value,rows=state.tables[key],columns=Object.keys(rows[0]);const escape=v=>'"'+String(v).replaceAll('"','""')+'"';download(key+'.csv','\ufeff'+[columns,...rows.map(row=>columns.map(k=>row[k]))].map(row=>row.map(escape).join(',')).join('\r\n'),'text/csv;charset=utf-8');};
$('csvIn').onchange=()=>action(async()=>{const file=$('csvIn').files[0];if(!file)return;const key=$('table').value,rows=await api('import',{table:key,csv:await file.text()}),incoming=clone(sync());incoming.tables[key]=rows;await api('save',incoming);state=incoming;changed('CSVを読み込みました。入力を確認して再解析してください。');await refresh();$('csvIn').value='';});
$('table').onchange=()=>{page=0;grid();};$('tableSearch').oninput=()=>{page=0;grid();};$('linkedRows').onchange=()=>{page=0;grid();};$('prevPage').onclick=()=>{page--;grid();};$('nextPage').onclick=()=>{page++;grid();};$('bulkScope').onchange=grid;
$('bulkApply').onclick=()=>action(async()=>{const value=$('bulkValue').value;if(value===''||!Number.isFinite(Number(value)))throw Error('一括入力する数値を入れてください');const kind=$('table').value,column=$('bulkColumn').value;if(kind==='edges'&&column==='V'&&state.mode==='propagate')throw Error('Vを直接入力する場合は「各素辺の観測流量を使う」を選んでください');const rows=$('bulkScope').value==='all'?state.tables[kind]:filteredRows().map(x=>x.row);if(!rows.length)throw Error('対象の行がありません');for(const row of rows)row[column]=value;changed(`${column}=${value} を${rows.length}行に適用しました。「元に戻す」で取り消せます。`);fields();grid();map();});
for(const k of ['theta','name','global_rule','local_rule'])$(k).onchange=()=>{sync();if(k==='theta')clearBaseline();changed();};
$('mode').onchange=()=>{if($('mode').value==='observe')for(const k of ['global_rule','local_rule'])$(k).value='none';sync();clearBaseline();changed();fields();grid();};
$('tau').onchange=()=>action(async()=>{sync();clearBaseline();changed();await refresh();});
$('norm').onchange=()=>action(async()=>{const norm=$('norm').value;try{state=await api('normalization',{state,norm});}catch(error){$('norm').value=state.norm;throw error;}clearBaseline();changed();await refresh();status('規格化とμ・Tを換算しました。Vと臨界総流量を保持しています。');});
$('sourceSettings').onclick=()=>action(async()=>{sync();state=await api('source-settings',state);clearBaseline();changed();await refresh();status('原資料の基本設定にそろえ、μ・Tを換算しました。保存して再解析してください。');});
for(const k of ['n','halo'])$(k).onchange=()=>status('サイズ・余白の変更は「合成例から新しく作る」で適用します。現在の解析条件にはまだ適用していません。');
$('profile').onchange=()=>action(async()=>{sync();state.profile=$('profile').value;clearBaseline();changed();await refresh();status(`${info.profile.name}に切り替えました。入力値と計算設定を保持しています。`);});
$('baseline').onclick=()=>action(async()=>{const saved=await api('save',sync());baseline=saved.id;baselineName=state.name;$('baseLabel').textContent=`変更前を固定：${baselineName}`;await list();status('変更前を固定しました。条件を編集して「変更前と比較」を押してください。');});$('clear').onclick=()=>{clearBaseline();status('変更前の固定を解除しました。');};
$('undo').onclick=()=>action(()=>undo());$('redo').onclick=()=>action(()=>undo(true));
$('edgeSelect').onchange=()=>selectEdge(Number($('edgeSelect').value));$('locateRow').onclick=()=>{$('table').value='edges';$('tableSearch').value='';$('linkedRows').checked=true;page=0;grid();$('dataSection').scrollIntoView({behavior:'smooth'});};
$('mapMetric').onchange=map;$('zoomIn').onclick=()=>{zoom=Math.min(4,zoom*1.25);map();};$('zoomOut').onclick=()=>{zoom=Math.max(1,zoom/1.25);map();};$('zoomReset').onclick=()=>{zoom=1;map();};
$('toggleLog').onclick=()=>{const open=$('runLog').hidden;$('runLog').hidden=!open;$('toggleLog').setAttribute('aria-expanded',String(open));};
async function displayResult(result){
    const reportResponse=await fetch(result.url.replace('viewer.html','report.json'));if(!reportResponse.ok)throw Error('計算結果は保存されましたが、要約を読み込めません。再度解析してください。');const report=await reportResponse.json();
    const rows=[['解析対象の有向素辺',`${report.geometry.inner_directed_edges} 本`],['比較する六角形',`${report.standard?.hex_rotation?.count??'—'} 個`],['入力検査の指摘',`${report.issues.length} 件`],['配分調整',result.adjustment_resolved===null?'未選択':result.adjustment_resolved?'解消':'未解消']];
    $('resultSummary').replaceChildren(...rows.map(([name,value])=>{const el=document.createElement('div'),label=document.createElement('span'),number=document.createElement('strong');label.textContent=name;number.textContent=value;el.append(label,number);return el;}));$('resultSummary').hidden=false;$('resultEmpty').hidden=true;$('resultState').textContent=result.url.includes('/scenario/')?'変更前後の比較':'解析済み';$('resultState').className='tag ok';
    $('result').src=result.url;$('result').hidden=false;$('resultLink').href=result.url;$('resultLink').hidden=false;$('archiveLink').href=result.archive_url;$('archiveLink').hidden=false;lastResult=result.id;
    const identity=report.provenance;$('identityPanel').hidden=!identity;if(identity){$('identityInfo').textContent=`ソフト ${identity.software_version}\n式の版 ${identity.formula_version}\n計算実装 SHA-256 ${identity.engine_sha256}\n入力 SHA-256 ${identity.input_sha256}\n${identity.note}`;$('identityJson').href=result.url.replace('viewer.html','provenance.json');$('identityCode').href=result.url.replace('viewer.html','engine_snapshot.zip');$('identityReplay').href=result.url.replace('viewer.html','REPRODUCE.txt');}
    $('runLog').textContent=result.log;$('toggleLog').hidden=!result.log;$('runLog').hidden=true;const unresolved=result.adjustment_resolved===false;status(unresolved?'結果を保存しました。配分調整は未解消です。'+(result.adjustment_reason||''):'解析が完了しました。結果の要約と格子図を確認できます。',unresolved);if(unresolved){$('resultState').textContent='配分調整が未解消';$('resultState').className='tag error';}

}
async function run(compare){
  sync();validate();if(issues.length){$('validationPanel').open=true;$('analysisSection').scrollIntoView({behavior:'smooth'});throw Error(`${issues.length}件の入力を確認してください。該当する場所を一覧から選べます。`);}
  hideResult('解析中');$('runText').textContent='解析しています…';status('解析しています。結果の生成までお待ちください。');
  try{const result=await api('run',{state,baseline:compare?baseline:null});await displayResult(result);savedCheckpoint=JSON.stringify(state);dirty=false;await list();$('resultsSection').scrollIntoView({behavior:'smooth'});}
  finally{$('runText').textContent='現在の入力を解析';}
}
$('name').oninput=()=>{state.name=$('name').value;queueDraft(true);};
$('theta').oninput=()=>{state.theta=$('theta').value===''?null:Number($('theta').value);clearBaseline();queueDraft(true);};
$('run').onclick=()=>action(()=>run(false));$('compare').onclick=()=>action(()=>run(true));
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
document.addEventListener('keydown',event=>{if(!(event.ctrlKey||event.metaKey))return;const editing=['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName);if(event.key.toLowerCase()==='s'){event.preventDefault();$('save').click();}else if(event.key.toLowerCase()==='z'&&!editing){event.preventDefault();action(()=>undo(event.shiftKey));}});
const observer=new IntersectionObserver(entries=>{const top=entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];if(top)document.querySelectorAll('.nav-item').forEach(link=>{const active=link.getAttribute('href')==='#'+top.target.id;link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');});},{rootMargin:'-70px 0px -55% 0px'});
for(const id of ['setup','workspace','dataSection','analysisSection','sweepSection','resultsSection'])observer.observe($(id));
function recoveryView(){return {selected,table:$('table').value,search:$('tableSearch').value,linked:$('linkedRows').checked,page,zoom,mapMetric:$('mapMetric').value,scrollY:window.scrollY,sweep_id:currentSweepId};}
function queueDraft(editing=false){
  if(!draftReady||!state||!sessionId)return;
  if(editing){dirty=true;hideResult();updateControls();}
  const content={state,dirty,baseline,view:recoveryView(),result_id:lastResult};
  const serial=JSON.stringify(content);if(serial===draftSerial&&!draftPending)return;
  if(serial!==draftSerial){draftSerial=serial;draftRevision++;draftPending=JSON.parse(serial);draftPending.session_id=sessionId;draftPending.revision=draftRevision;draftPending.updated_at=new Date().toISOString();
    try{localStorage.setItem('kagome-draft-'+sessionId,JSON.stringify(draftPending));const keys=Object.keys(localStorage).filter(k=>k.startsWith('kagome-draft-'));if(keys.length>8){const dates=keys.map(key=>{try{return {key,date:JSON.parse(localStorage.getItem(key)).updated_at||''};}catch{return {key,date:''};}}).sort((a,b)=>b.date.localeCompare(a.date));for(const item of dates.slice(8))if(item.key!=='kagome-draft-'+sessionId)localStorage.removeItem(item.key);}}catch{$('draftStatus').textContent='ブラウザ退避不可・サーバーへ保存します';}
  }
  clearTimeout(draftTimer);draftTimer=setTimeout(persistDraft,700);
}
async function persistDraft(){
  if(draftSending||!draftPending)return;draftSending=true;
  try{while(draftPending){const payload=draftPending;const ack=await api('draft',payload);if(draftPending?.revision===payload.revision)draftPending=null;draftRevision=Math.max(draftRevision,ack.revision);$('draftStatus').textContent='復元用に自動保存 '+new Date(ack.updated_at).toLocaleTimeString('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',second:'2-digit'});$('draftStatus').classList.remove('failed');}}
  catch{$('draftStatus').textContent='自動保存に失敗・JSONを書き出してください';$('draftStatus').classList.add('failed');}
  finally{draftSending=false;}
}
async function startup(){
  let tab=null;try{tab=sessionStorage.getItem('kagome-session');}catch{}
  const initial=await api('startup',{profile:INITIAL_PROFILE,session_id:tab});sessionId=initial.session_id;
  try{sessionStorage.setItem('kagome-session',sessionId);}catch{}
  let draft=initial.draft;
  try{const local=JSON.parse(localStorage.getItem('kagome-draft-'+(initial.source_session_id||sessionId))||'null');if(local&&local.revision>(draft?.revision??-1)){
    local.session_id=sessionId;await api('draft',local);draft=local;
  }}catch{} // ブラウザ側が読めない場合も、サーバーの退避・保存ケースを残す
  draftRevision=draft?.revision||0;
  state=draft?.state||await api('init',{n:3,halo:true,profile:$('profile').value});await refresh({reset:true});
  if(draft){dirty=Boolean(draft.dirty);savedCheckpoint=dirty?'':JSON.stringify(state);checkpoint=JSON.stringify(state);const view=draft.view||{};
    selected=Number.isInteger(view.selected)?Math.max(0,Math.min(view.selected,state.tables.edges.length-1)):selected;
    if(['edges','branching','entrances'].includes(view.table))$('table').value=view.table;
    $('tableSearch').value=String(view.search||'');$('linkedRows').checked=Boolean(view.linked);page=Number.isInteger(view.page)?Math.max(0,view.page):0;zoom=Number.isFinite(view.zoom)?Math.max(1,Math.min(4,view.zoom)):1;
    if(['network','m','L'].includes(view.mapMetric))$('mapMetric').value=view.mapMetric;
    $('edgeSelect').value=String(selected);fields();map();grid();
    if(draft.baseline){try{const before=await api('load',{id:draft.baseline});if(['n','halo','profile','mode','norm','tau','theta'].every(k=>before[k]===state[k])){baseline=draft.baseline;baselineName=before.name;$('baseLabel').textContent='変更前を固定：'+baselineName;}}catch{}}
    if(draft.result_id){try{const result=await api('result',{id:draft.result_id,state});if(result)await displayResult(result);}catch{}}
    status('前回の作業を復元しました。'+(dirty?'手動保存前の編集を含みます。':'保存した入力を引き続き使えます。'));
    requestAnimationFrame(()=>window.scrollTo(0,Math.max(0,Number(view.scrollY)||0)));
  }else status(initial.warning||'合成例を用意しました。練習例から始めるか、実際の条件に合わせて編集してください。',Boolean(initial.warning));
  exampleCatalog=await api('examples',{});$('exampleSelect').replaceChildren(...exampleCatalog.map(item=>new Option(item.name,item.id)));describeExample();
  if(draft?.view?.sweep_id){try{await showSweep(draft.view.sweep_id);}catch{}}
  await list();draftReady=true;$('draftStatus').textContent='復元用の自動保存が有効';
}
window.addEventListener('pagehide',()=>{queueDraft();persistDraft();});
document.addEventListener('visibilitychange',()=>{if(document.hidden){queueDraft();persistDraft();}});
for(const id of ['table','tableSearch','linkedRows','mapMetric'])$(id).addEventListener(id==='tableSearch'?'input':'change',()=>queueDraft());
for(const id of ['prevPage','nextPage','zoomIn','zoomOut','zoomReset','clear'])$(id).addEventListener('click',()=>queueDraft());
function describeExample(){const item=exampleCatalog.find(item=>item.id===$('exampleSelect').value);$('exampleDescription').textContent=item?.description||'';$('exampleCheck').textContent=item?'確認する点：'+item.check:'';}
$('exampleSelect').onchange=describeExample;
$('exampleLoad').onclick=()=>action(async()=>{if(!acceptReplace('未保存の編集を代表ケースで置き換えますか？'))return;const incoming=await api('example',{id:$('exampleSelect').value,profile:state.profile});await replaceState(incoming);status(`代表ケース「${incoming.name}」を読み込みました。合成データです。説明に沿って解析・変更前後の比較を確認できます。`);});
function updateSweepControls(){
  if(!state)return;$('sweepRun').disabled=busy||sweepRunning;$('sweepCancel').disabled=busy||!sweepCancelable;
  $('sweepParameter').querySelector('option[value="V"]').disabled=state.mode!=='observe';$('sweepParameter').querySelector('option[value="inflow_scale"]').disabled=state.mode!=='propagate';
  $('sweepParameter').querySelector('option[value="m"]').textContent=state.profile==='traffic'?'車線数 m':'並列経路数 m';
  const allOnly=['R','left','inflow_scale'].includes($('sweepParameter').value);for(const option of $('sweepScope').options)option.disabled=allOnly&&option.value!=='all';if(allOnly)$('sweepScope').value='all';
  const row=state.tables.edges[selected];$('sweepTarget').textContent=$('sweepScope').value==='selected'&&row?'対象：'+keyName(row):$('sweepScope').value==='inner'?'両端が解析範囲内にある有向素辺だけを変更します。':'余白を含む全体を変更します。開始時の入力は別に保存します。';
}
$('sweepScope').onchange=updateSweepControls;
$('sweepParameter').onchange=()=>{const suggestions={m:'1, 2, 3, 4',L:'0.25, 0.5, 1',v:'20, 40, 60',V:'800, 1600, 2400',T:'50, 100, 200',mu:'500, 1000, 1500',R:'0.1, 0.2, 0.3',left:'0.05, 0.1, 0.2',inflow_scale:'0.5, 1, 1.5'};$('sweepValues').value=suggestions[$('sweepParameter').value];updateSweepControls();};
async function showSweep(id,provided=null){
  clearTimeout(sweepTimer);currentSweepId=id;const document=provided||await api('sweep-status',{id});if(currentSweepId!==id)return;
  if(!document){sweepRunning=false;$('sweepBadge').textContent='保存した比較が見つかりません';updateSweepControls();return;}
  const statuses={queued:'待機中',running:'実行中',completed:'完了',completed_with_errors:'一部失敗',cancelled:'残りを中止',failed:'計算失敗',interrupted:'中断'};
  sweepCancelable=['queued','running'].includes(document.status);sweepRunning=sweepCancelable||document.archiving;
  $('sweepBadge').textContent=document.archiving?'ZIP作成中':statuses[document.status]||document.status;$('sweepBadge').className='tag '+(['failed','interrupted','completed_with_errors'].includes(document.status)?'error':document.status==='completed'?'ok':'');
  $('sweepProgress').textContent=`開始時の入力：${document.name}\n${document.completed}/${document.total} 条件を解析済み。${document.status==='running'&&!document.reference?'開始時の基準条件を計算しています。':''}${document.cancel_requested&&sweepCancelable?'現在の解析が終わったら、残りを中止します。':''}${document.error?'\n'+document.error:''}${document.archive_error?'\n'+document.archive_error:''}`;
  $('sweepMeter').hidden=false;$('sweepMeter').max=document.total;$('sweepMeter').value=document.completed;
  for(const [id,url] of [['sweepOpen',document.url],['sweepCsv',document.csv_url],['sweepZip',document.archive_url]]){$(id).hidden=!url;if(url)$(id).href=url;}
  updateSweepControls();
  if(sweepRunning)scheduleSweep(id,700);
}
function scheduleSweep(id,delay){clearTimeout(sweepTimer);sweepTimer=setTimeout(async()=>{if(currentSweepId!==id)return;try{await showSweep(id);}catch{if(currentSweepId===id){$('sweepProgress').textContent='進捗を取得できません。再接続を試しています。';scheduleSweep(id,2500);}}},delay);}
$('sweepRun').onclick=()=>action(async()=>{
  sync();validate();if(issues.length)throw Error('一括比較の前に、現在の入力のエラーを修正してください。');
  const text=$('sweepValues').value.trim();const values=text.split(/[,、，;\s]+/).filter(Boolean).map(Number);const row=state.tables.edges[selected];
  const request={parameter:$('sweepParameter').value,scope:$('sweepScope').value,values,edge:[row.node_type,Number(row.i),Number(row.j),Number(row.road)]};
  const document=await api('sweep',{state:clone(state),request});await showSweep(document.id,document);await list();status('開始時の入力を固定して、一括比較を始めました。進捗は「条件を振って一括比較」で確認できます。');queueDraft();
});
$('sweepCancel').onclick=()=>action(async()=>{if(currentSweepId){const document=await api('sweep-cancel',{id:currentSweepId});await showSweep(currentSweepId,document);}});
function setupDemonstration(){
  const panel=document.createElement('details');panel.id='demonstrationPanel';panel.className='panel';
  panel.innerHTML='<summary style="font-weight:700;font-size:18px">5分の操作例：Vだけを変えて比較する</summary><p class="hint">一様な合成入力を使い、現在値と2つの標準との差を読みます。既存の保存ケースは残します。</p><p id="demoInstruction" role="status"></p><div class="button-row"><button id="demoNext" class="primary"></button><button id="demoRestart" class="secondary">手順を最初に戻す</button><a class="secondary button-link" href="/demonstration.html" target="_blank" rel="noopener">説明用の台本 ↗</a></div>';
  $('setup').before(panel);
  const captions=['一様な入力を用意','解析して変更前を固定','流量を2400へ変更','変更前後を比較','実演完了'];
  const instructions=['① m=2、V=1600、μ=1000の一様な例を用意します。開始時に現在の編集内容を置き換えます。','② 解析し、基準の入力を固定します。六角形は右600・左360・正味240、標準の正味300との差は−60です。','③ Vだけを1600から2400へ変えます。本数・長さ・速度・分岐・μ・Tを保ちます。','④ 変更前後を比較します。正味回転は240→360、標準との差は−60→＋60になります。','⑤ 結果を確認してください。容量比は80%→120%。良否の判定は用途側で定めます。ZIPで入力・比較結果・計算の版を保存できます。'];
  function paint(){ $('demoNext').textContent=captions[demonstrationStage];$('demoInstruction').textContent=instructions[demonstrationStage];updateControls(); }
  $('demoRestart').onclick=()=>{demonstrationStage=0;demonstrationExpected='';paint();};
  $('demoNext').onclick=()=>action(async()=>{
    if(demonstrationStage>0&&JSON.stringify(sync())!==demonstrationExpected)throw Error('操作例の条件が変更されています。「手順を最初に戻す」から再開してください。');
    if(demonstrationStage===0){
      if(!acceptReplace('現在の未保存の編集を、操作例の一様な入力で置き換えますか？'))return;
      const incoming=await api('tutorial',{profile:state.profile});incoming.name='5分実演：Vを1600から2400へ';await replaceState(incoming);
    }else if(demonstrationStage===1){
      const result=await api('run',{state:clone(sync())});await displayResult(result);baseline=result.id;baselineName=state.name;$('baseLabel').textContent='変更前を固定：'+baselineName;await list();
    }else if(demonstrationStage===2){
      for(const row of state.tables.edges)row.V='2400';changed();await refresh();
    }else if(demonstrationStage===3){
      const result=await api('run',{state:clone(sync()),baseline});await displayResult(result);await list();$('resultsSection').scrollIntoView({behavior:'smooth'});
    }
    demonstrationStage++;demonstrationExpected=JSON.stringify(sync());paint();status(instructions[demonstrationStage]);
  });
  panel.open=new URLSearchParams(location.search).get('demo')==='flow';paint();
}
setupDemonstration();
action(startup);
