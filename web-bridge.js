(()=>{
  'use strict';
  const base=new URL('./',location.href);
  const originalFetch=window.fetch.bind(window);
  const version=globalThis.KAGOME_WEB_VERSION||'1.0.1';
  const asset=name=>new URL(name+'?v='+encodeURIComponent(version),base);
  const worker=new Worker(asset('./worker.mjs'),{type:'module'});
  let serial=0;const pending=new Map();
  worker.onmessage=({data})=>{if(data.type==='progress'){document.getElementById('webLoadingText').textContent=data.message;return;}const callback=pending.get(data.id);if(!callback)return;pending.delete(data.id);data.error?callback.reject(Error(data.error)):callback.resolve(data.value);};
  worker.onerror=event=>{const error=Error(event.message||'計算環境を起動できませんでした。');for(const callback of pending.values())callback.reject(error);pending.clear();};
  function call(type,path,data){return new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject});worker.postMessage({id,type,path,data});});}
  function relocate(value){if(typeof value==='string'&&value.startsWith('/files/'))return new URL('.'+value,base).href;if(Array.isArray(value))return value.map(relocate);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,relocate(item)]));return value;}
  window.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href);
    if(url.origin===location.origin&&url.pathname.startsWith('/api/')){
      try{const result=relocate(await call('api',url.pathname.slice(5),JSON.parse(options.body||'{}')));return new Response(JSON.stringify(result),{headers:{'Content-Type':'application/json'}});}
      catch(error){console.error(error);return new Response(JSON.stringify({error:error.message}),{status:400,headers:{'Content-Type':'application/json'}});}
    }
    return originalFetch(input,options);
  };
  async function boot(){
    if(!('serviceWorker'in navigator))throw Error('このブラウザでは実行できません。最新のChrome、Edge、Firefox、SafariでHTTPSのURLを開いてください。');
    const registration=await navigator.serviceWorker.register(new URL('./sw.js',base),{scope:base.pathname,updateViaCache:'none'});
    await navigator.serviceWorker.ready;
    if(!navigator.serviceWorker.controller)await new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
    await call('ready');
    // Both labels are display profiles of the same unchanged numerical engine.
    const sessionKey='kagome-web-session-'+INITIAL_PROFILE;
    const previousSession=sessionStorage.getItem(sessionKey);
    if(previousSession)sessionStorage.setItem('kagome-session',previousSession);else sessionStorage.removeItem('kagome-session');
    const script=document.createElement('script');script.src=asset('./assets/editor.js');script.onload=()=>document.getElementById('webLoading').remove();script.onerror=()=>showError(Error('操作画面を読み込めませんでした'));document.head.append(script);
    window.addEventListener('pagehide',()=>{const id=sessionStorage.getItem('kagome-session');if(id)sessionStorage.setItem(sessionKey,id);});
    const localLabel=document.querySelector('.local-label');if(localLabel)localLabel.title='入力・結果はこの端末のブラウザに保存します。他の端末とは共有されません。';
  }
  function showError(error){document.getElementById('webLoadingText').textContent='起動できませんでした：'+error.message;document.getElementById('webRetry').hidden=false;console.error(error);}
  boot().catch(showError);
})();
