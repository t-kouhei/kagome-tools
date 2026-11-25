const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const qa=path.resolve(__dirname,'../qa-output');
const url=process.argv[2]||'http://127.0.0.1:8080/';
fs.mkdirSync(qa,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 try{
  const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:1050}});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>{errors.push(String(error));console.log('PAGE ERROR',String(error));});
  page.on('console',message=>{if(message.type()==='error')console.log('CONSOLE',message.text().slice(0,1800));});
  console.log('OPEN',url);
  await page.goto(url+'app.html?profile=patent',{waitUntil:'domcontentloaded'});
  for(let i=0;i<240;i++){
    if(!await page.locator('#webLoading').count())break;
    const text=await page.locator('#webLoadingText').innerText();if(i%10===0)console.log('LOADING',text);
    if(text.includes('起動できませんでした'))throw Error(text);
    await page.waitForTimeout(1000);
    if(i===239)throw Error('Startup timed out');
  }
  await page.waitForFunction(()=>document.getElementById('validationBadge').textContent.includes('エラーなし'),{timeout:60000});
  console.log('READY',await page.locator('#status').innerText());
  await page.screenshot({path:path.join(qa,'workspace.png'),fullPage:true});
  console.log('BUTTONS',(await page.locator('button').allTextContents()).slice(0,60));
  await page.locator('#run').click();
  await page.waitForFunction(()=>!document.getElementById('result').hidden||document.querySelector('#notice.error'),{timeout:120000});
  if(await page.locator('#result').isHidden())throw Error(await page.locator('#status').innerText());
  const resultURL=await page.locator('#result').getAttribute('src');console.log('RESULT',resultURL);
  const report=await page.evaluate(async url=>{const response=await fetch(url);if(!response.ok)throw Error(response.status);return response.json();},resultURL.replace('viewer.html','report.json'));
  fs.writeFileSync(path.join(qa,'browser-report.json'),JSON.stringify(report,null,2));
  console.log('VIEWER',await page.frameLocator('#result').locator('h1').allTextContents());
  await page.locator('#resultsSection').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(qa,'analysis.png')});
  const downloadPromise=page.waitForEvent('download');await page.locator('#archiveLink').click();const download=await downloadPromise;await download.saveAs(path.join(qa,'analysis.zip'));console.log('ZIP',fs.statSync(path.join(qa,'analysis.zip')).size);
  const settle=()=>page.waitForFunction(()=>!document.body.classList.contains('busy'));
  await settle();
  // Exercise the existing UI, including a generated before/after result.
  await page.locator('#tutorial').click();await settle();
  await page.locator('#baseline').click();await settle();
  await page.getByRole('spinbutton',{name:'m',exact:true}).fill('3');
  await page.locator('#compare').focus();
  await page.locator('#compare').click();await settle();
  if(await page.locator('#notice').evaluate(el=>el.classList.contains('error')))throw Error(await page.locator('#status').innerText());
  const scenarioURL=await page.locator('#result').getAttribute('src');
  if(!scenarioURL.includes('/scenario/'))throw Error('Scenario viewer was not generated');
  console.log('SCENARIO PASS',scenarioURL);
  // A sweep advances one case at a time. Cancellation can run between cases.
  await page.locator('#sweepValues').fill('1, 2');
  await page.locator('#sweepRun').click();await settle();
  await page.waitForFunction(()=>['完了','一部失敗','計算失敗'].includes(document.getElementById('sweepBadge').textContent),{timeout:120000});
  if(await page.locator('#sweepBadge').innerText()!=='完了')throw Error(await page.locator('#sweepProgress').innerText());
  console.log('SWEEP PASS',await page.locator('#sweepProgress').innerText());
  const sweepURL=await page.locator('#sweepOpen').getAttribute('href');
  const sweepPage=await context.newPage();await sweepPage.goto(sweepURL);await sweepPage.locator('#rows tr').first().waitFor();
  const caseURL=await sweepPage.locator('#rows a').first().getAttribute('href');
  if(!new URL(caseURL,sweepURL).pathname.startsWith(new URL(url).pathname+'files/'))throw Error('Nested sweep URL escaped the Pages prefix');
  console.log('SWEEP LINKS PASS',caseURL);await sweepPage.close();
  const cancelState=await page.evaluate(()=>clone(state));
  const cancelled=await page.evaluate(async s=>{const started=await api('sweep',{state:s,request:{parameter:'m',scope:'all',values:[1,2,3,4]}});await api('sweep-cancel',{id:started.id});return api('sweep-status',{id:started.id});},cancelState);
  if(cancelled.status!=='cancelled'||cancelled.completed!==0)throw Error('Sweep cancellation failed');
  console.log('CANCEL PASS');
  const interrupted=await page.evaluate(async s=>api('sweep',{state:s,request:{parameter:'m',scope:'all',values:[1,2]}}),cancelState);
  // Restore the current state and its result after a full document reload.
  await page.evaluate(async()=>{queueDraft();await persistDraft();});await page.waitForTimeout(700);
  const beforeReload=await page.evaluate(()=>JSON.stringify(state));await page.reload();
  await page.waitForFunction(()=>!document.getElementById('webLoading'),{timeout:120000});
  await settle();
  if(await page.evaluate(()=>JSON.stringify(state))!==beforeReload)throw Error('Reload changed the edited state');
  console.log('RESTORE PASS',await page.locator('#status').innerText());
  const interruption=await page.evaluate(id=>api('sweep-status',{id}),interrupted.id);
  if(interruption.status!=='interrupted')throw Error('Reload left a sweep running forever');
  console.log('INTERRUPTION PASS');
  // Keep the generic tab open while operating the traffic tab, then check both.
  const countBefore=await page.evaluate(async()=> (await api('list',{})).length);
  const traffic=await context.newPage();traffic.on('pageerror',error=>errors.push(String(error)));await traffic.goto(url+'app.html?profile=traffic');
  await traffic.waitForFunction(()=>!document.getElementById('webLoading'),{timeout:120000});
  await traffic.waitForFunction(()=>!document.body.classList.contains('busy'));
  if(await traffic.locator('#profile').inputValue()!=='traffic')throw Error('Traffic profile not selected');
  const cross=await traffic.evaluate(async()=>{const a=await api('tutorial',{profile:'patent'}),b=await api('tutorial',{profile:'traffic'});const first=await api('run',{state:a}),second=await api('run',{state:b});const read=async r=>(await(await fetch(r.url.replace('viewer.html','report.json'))).json()).provenance;return {first:await read(first),second:await read(second)};});
  if(cross.first.input_sha256!==cross.second.input_sha256)throw Error('Profiles changed numerical inputs');
  if(JSON.stringify(cross.first.output_sha256)!==JSON.stringify(cross.second.output_sha256))throw Error('Profiles changed numerical outputs');
  console.log('PROFILE PARITY PASS',cross.first.input_sha256);
  const operations=await traffic.evaluate(async()=>{
    const state=await api('example',{id:'bottleneck',profile:'traffic'});
    const results=[];
    for(const [global_rule,local_rule]of [['direction','none'],['maxflow','none'],['none','lp']]){
      const variant=clone(state);variant.global_rule=global_rule;variant.local_rule=local_rule;
      const result=await api('run',{state:variant});const response=await fetch(result.url.replace('viewer.html','report.json'));
      if(!response.ok)throw Error('Cannot read operation result');const report=await response.json();results.push({global_rule,local_rule,operations:report.operations});
    }
    return results;
  });
  fs.writeFileSync(path.join(qa,'operations.json'),JSON.stringify(operations,null,2));
  console.log('OPERATIONS PASS',operations.map(row=>[row.global_rule,row.local_rule]));
  await page.evaluate(()=>api('save',clone(state)));
  const countAfter=await traffic.evaluate(async()=> (await api('list',{})).length);
  if(countAfter<countBefore+3)throw Error('Concurrent browser tabs lost saved cases');
  console.log('MULTITAB PASS',countBefore,countAfter);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  if(overflow)throw Error('Desktop layout overflows');
  await traffic.close();await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(qa,'mobile.png')});
  fs.writeFileSync(path.join(qa,'errors.json'),JSON.stringify(errors));
  if(errors.length)throw Error('Uncaught browser errors: '+errors.join('\n'));
  fs.writeFileSync(path.join(qa,'checks.json'),JSON.stringify({url,basic:true,scenario:true,sweep:true,cancel:true,restore:true,profileParity:true,multipleTabs:true,operations:true,errors},null,2));
  console.log('ALL BROWSER CHECKS PASS');
 } finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
