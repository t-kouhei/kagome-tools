const DB_NAME='kagome-web-results-v1';
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
function readFile(key){return new Promise((resolve,reject)=>{const open=indexedDB.open(DB_NAME,1);open.onupgradeneeded=()=>open.result.createObjectStore('files');open.onerror=()=>reject(open.error);open.onsuccess=()=>{const db=open.result,req=db.transaction('files').objectStore('files').get(key);req.onsuccess=()=>{resolve(req.result);db.close();};req.onerror=()=>{reject(req.error);db.close();};};});}
const types={html:'text/html; charset=utf-8',json:'application/json; charset=utf-8',csv:'text/csv; charset=utf-8',txt:'text/plain; charset=utf-8',zip:'application/zip',png:'image/png'};
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url),prefix=new URL('./files/',self.registration.scope).pathname;
  if(url.origin!==self.location.origin||!url.pathname.startsWith(prefix))return;
  event.respondWith((async()=>{
    let key;try{key=decodeURIComponent(url.pathname.slice(prefix.length));}catch{return new Response('Invalid path',{status:400});}
    if(key.split('/').some(part=>part==='.'||part==='..')||!/^[-a-f0-9]{36}\//.test(key))return new Response('Invalid path',{status:400});
    const bytes=await readFile(key);if(bytes===undefined)return new Response('このブラウザに結果がありません。解析画面で計算してから開いてください。',{status:404,headers:{'Content-Type':'text/plain; charset=utf-8'}});
    const ext=key.split('.').pop().toLowerCase(),headers={'Content-Type':types[ext]||'application/octet-stream','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
    if(ext==='zip'||ext==='csv')headers['Content-Disposition']='attachment';
    const body=ext==='html'?new TextDecoder().decode(bytes).replace(/(["'])\/files\//g,(_,quote)=>quote+prefix):bytes;
    return new Response(body,{headers});
  })().catch(()=>new Response('ブラウザの保存領域を読み込めませんでした。',{status:500,headers:{'Content-Type':'text/plain; charset=utf-8'}})));
});
