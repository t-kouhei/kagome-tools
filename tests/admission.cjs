const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2]||'http://127.0.0.1:8765/kagome-web/';
const out=path.resolve(__dirname,'../qa-output');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1050},acceptDownloads:true});
  const page=await context.newPage(),errors=[],cases=[];page.on('pageerror',e=>errors.push(String(e)));page.on('dialog',d=>d.accept());
  await page.goto(base+'specification.html#admission');
  if(await page.locator('#admission').count()!==1)throw Error('Admission documentation anchor missing');
  for(const name of ['low','high','direction-6-off'])if(await page.locator(`article a[href$="/admission/${name}.json"]`).count()!==1)throw Error('Input JSON link missing '+name);
  await page.setViewportSize({width:390,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Admission document mobile overflow');
  await page.screenshot({path:path.join(out,'admission-document-mobile.png')});await page.setViewportSize({width:1440,height:1050});
  await page.goto(base+'app.html?profile=patent&v=1.0.3');
  const settle=()=>page.waitForFunction(()=>!document.getElementById('webLoading')&&!document.body.classList.contains('busy'),{timeout:120000});
  await settle();
  if(await page.locator('a[href="./specification.html#admission"]').count()!==1)throw Error('Workspace admission help missing');
  await page.locator('details.file-drawer summary').click();
  for(const [name,requested,admitted,rejected]of [['low',38000,38000,0],['high',228000,76000,152000],['direction-6-off',174000,58000,116000]]){
   const response=await context.request.get(base+'examples/admission/'+name+'.json');if(!response.ok())throw Error('Input fetch failed '+name);
   const buffer=await response.body();fs.writeFileSync(path.join(out,'admission-'+name+'.json'),buffer);
   await page.locator('#upload').setInputFiles({name:name+'.json',mimeType:'application/json',buffer});await settle();
   if(await page.locator('#mode').inputValue()!=='propagate'||await page.locator('#global_rule').inputValue()!=='direction'||await page.locator('#local_rule').inputValue()!=='none')throw Error('Import lost admission settings');
   await page.locator('#run').click();await settle();
   if(await page.locator('#notice').evaluate(el=>el.classList.contains('error')))throw Error(await page.locator('#status').innerText());
   const report=await page.evaluate(async()=>{const r=await fetch(document.getElementById('result').src.replace('viewer.html','report.json'));if(!r.ok)throw Error(r.status);return r.json();});
   const g=report.operations.global;
   if(g.requested!==requested||Math.abs(g.admitted_total-admitted)>1e-7||Math.abs(g.rejected_total-rejected)>1e-7)throw Error('Admission amounts differ '+JSON.stringify(g));
   if(Math.abs(report.propagation.inflow_total-admitted)>1e-7||Math.abs(report.propagation.outflow_total-admitted)>1e-7)throw Error('Flow balance failed');
   for(const row of Object.values(g.load))if(row.after>row.limit+1e-7)throw Error('Direction limit exceeded');
   const frame=page.frameLocator('#result');await frame.locator('#admissionRequested').waitFor();
   const shown=async id=>Number((await frame.locator('#'+id).innerText()).replaceAll(',',''));
   if(await shown('admissionRequested')!==requested||await shown('admissionAccepted')!==admitted||await shown('admissionRejected')!==rejected)throw Error('Visible admission summary differs');
   if(await frame.locator('#directionLoadTable tr').count()!==7||await frame.locator('#entranceAdmissionTable tr').count()!==7)throw Error('Six directions are not visible');
   if(name==='high'){
    await frame.locator('#globalCard').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'admission-high.png')});
    const download=page.waitForEvent('download');await page.locator('#archiveLink').click();await(await download).saveAs(path.join(out,'admission-high.zip'));
   }
   if(name==='direction-6-off'){
    if(g.by_direction['6'].demand!==0||g.by_direction['6'].admitted!==0||g.load['6'].limit!==82000||g.load['6'].after!==0)throw Error('Zero inlet was confused with removed infrastructure');
    const zero=await frame.locator('#entranceAdmissionTable tr[data-direction="6"] td').allTextContents();if(zero.slice(1).map(Number).some(v=>v!==0))throw Error('Zero inlet missing in visible table');
    await page.setViewportSize({width:390,height:844});await frame.locator('#globalCard').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'admission-off-mobile.png')});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Admission workspace mobile overflow');
   }
   cases.push({name,requested,admitted,rejected,by_direction:g.by_direction,load:g.load});console.log('ADMISSION CASE PASS',name,requested,admitted,rejected);
  }
  if(errors.length)throw Error(errors.join('\n'));
  fs.writeFileSync(path.join(out,'admission-checks.json'),JSON.stringify({base,cases,jsonImport:true,flowBalance:true,zeroInletRetainsReference:true,mobile:true,errors},null,2));console.log('ALL ADMISSION CHECKS PASS');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
