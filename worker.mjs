import {loadPyodide} from 'https://cdn.jsdelivr.net/pyodide/v314.0.8/full/pyodide.mjs';

let pyodide;
const version=new URL(import.meta.url).searchParams.get('v')||'1.0.1';
const releaseAsset=name=>name+'?v='+encodeURIComponent(version);
const published = new Map();
const filesDB = new Promise((resolve,reject)=>{
  const req=indexedDB.open('kagome-web-results-v1',1);
  req.onupgradeneeded=()=>req.result.createObjectStore('files');
  req.onsuccess=()=>resolve(req.result);
  req.onerror=()=>reject(req.error);
});
const progress=message=>postMessage({type:'progress',message});
function sync(populate){return new Promise((resolve,reject)=>pyodide.FS.syncfs(populate,error=>error?reject(error):resolve()));}
function storageLock(fn){if(!navigator.locks)throw Error('このブラウザは保存の同時更新に対応していません。最新のブラウザを使用してください。');return navigator.locks.request('kagome-workspace-v1',fn);}
async function mirrorFiles(){
  const rows=[];
  function visit(folder){for(const name of pyodide.FS.readdir(folder)){if(name==='.'||name==='..')continue;const path=folder+'/'+name,stat=pyodide.FS.stat(path);if(pyodide.FS.isDir(stat.mode))visit(path);else if(!path.includes('/sessions/')&&!path.endsWith('.tmp')){const key=path.slice('/persist/workspace/'.length),stamp=Number(stat.mtime)+':'+stat.size;if(published.get(key)!==stamp){rows.push([key,pyodide.FS.readFile(path),stamp]);}}}}
  visit('/persist/workspace');
  if(!rows.length)return;
  const db=await filesDB;
  await new Promise((resolve,reject)=>{const tx=db.transaction('files','readwrite');for(const [key,bytes] of rows)tx.objectStore('files').put(bytes,key);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('結果の保存に失敗しました'));});
  for(const [key,,stamp]of rows)published.set(key,stamp);
}
const ready=(async()=>{
  progress('計算環境を読み込んでいます（初回は通信量が多くなります）…');
  pyodide=await loadPyodide();
  progress('数値計算ライブラリを読み込んでいます…');
  await pyodide.loadPackage(['numpy','scipy']);
  const response=await fetch(releaseAsset('./engine.zip'));if(!response.ok)throw Error('計算コードを読み込めませんでした');
  pyodide.FS.mkdirTree('/app');pyodide.unpackArchive(await response.arrayBuffer(),'zip',{extractDir:'/app'});
  pyodide.FS.mkdirTree('/persist');pyodide.FS.mount(pyodide.FS.filesystems.IDBFS,{},'/persist');
  const adapter=await fetch(releaseAsset('./browser_adapter.py'));if(!adapter.ok)throw Error('ブラウザ用の接続コードを読み込めませんでした');
  pyodide.FS.writeFile('/app/browser_adapter.py',await adapter.text());
  await storageLock(async()=>{await sync(true);await pyodide.runPythonAsync("import sys\nsys.path.insert(0, '/app')\nimport browser_adapter");await sync(false);await mirrorFiles();});
  return true;
})();
let queue=Promise.resolve();
self.onmessage=({data})=>{
  queue=queue.catch(()=>{}).then(async()=>{
    try{
      await ready;
      if(data.type==='ready'){postMessage({id:data.id,value:true});return;}
      const value=await storageLock(async()=>{
        await sync(true);
        pyodide.globals.set('_web_path',data.path);pyodide.globals.set('_web_payload',JSON.stringify(data.data));
        const raw=await pyodide.runPythonAsync('browser_adapter.request(_web_path, _web_payload)');
        await sync(false);await mirrorFiles();
        return JSON.parse(raw);
      });
      postMessage({id:data.id,value});
    }catch(error){postMessage({id:data.id,error:String(error.message||error)});}
  });
};
