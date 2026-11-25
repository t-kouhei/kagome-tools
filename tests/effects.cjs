const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path');
const base=process.argv[2]||'http://127.0.0.1:8080/',out=path.resolve(__dirname,'../qa-output');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1100},acceptDownloads:true}),page=await context.newPage(),errors=[],records=[];
  page.on('pageerror',error=>errors.push(String(error)));page.on('dialog',dialog=>dialog.accept());
  await page.goto(base+'app.html?profile=patent&effect=bottleneck&v=1.0.2');
  await page.waitForFunction(()=>!document.getElementById('webLoading')&&!document.body.classList.contains('busy'),{timeout:120000});
  const settle=()=>page.waitForFunction(()=>!document.body.classList.contains('busy'),{timeout:120000});
  for(const id of ['bottleneck','components','reference','speed','flow']){
    await page.locator('#effectCase').selectOption(id);await page.locator('#effectRun').click();await settle();
    if(await page.locator('#notice').evaluate(el=>el.classList.contains('error')))throw Error(await page.locator('#status').innerText());
    await page.locator('#effectSummary').waitFor({state:'visible'});
    const report=await page.evaluate(async()=>{const response=await fetch(document.getElementById('result').src.replace('viewer.html','report.json'));if(!response.ok)throw Error(response.status);return response.json();});
    const values=report.comparison_summary.values;
    const cells=async key=>page.locator(`#effectSummary tr[data-metric="${key}"] td`).allTextContents();
    if(id==='bottleneck'){
      const row=await cells('over_capacity_edges');if(row.slice(1).join(',')!=='1,0,-1'&&row.slice(1).join(',')!=='1,0,−1')throw Error('Capacity effect is not visible '+row);
      if(values.inflow_total.change!==0||values.outflow_total.change>1e-6)throw Error('Demand was reduced or balance lost');
      const iframe=page.frameLocator('#result');await iframe.locator('#effectTable tbody tr').first().waitFor();
      const notes=await iframe.locator('#effectObservations').innerText();if(!notes.includes('容量超過が0本'))throw Error('Viewer omitted observation');
      await page.locator('#effectSummary').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'effects-capacity.png')});
      const promise=page.waitForEvent('download');await page.locator('#archiveLink').click();await(await promise).saveAs(path.join(out,'effects-bottleneck.zip'));
    }
    if(id==='components'&&(Math.abs(values.hex_net_mean.change)>1e-9||values.hex_cw_mean.after!==840||values.hex_ccw_mean.after!==600))throw Error('Component changes were lost');
    if(id==='reference'&&(values.standard_net_mean.after!==360||values.hex_net_mean.change!==0))throw Error('Reference change was conflated with flow');
    if(id==='speed'&&(values.equivalent_occupancy_mean.after!==10||values.hex_net_mean.change!==0))throw Error('Fixed-flow speed case is incorrect');
    if(id==='flow'&&values.hex_net_mean.after!==360)throw Error('Flow comparison incorrect');
    records.push({id,values,observations:report.comparison_summary.observations});console.log('CASE PASS',id,JSON.stringify(values.hex_net_mean));
  }
  // The selected recipe must also work with the traffic labels.
  await page.locator('#profile').selectOption('traffic');await settle();await page.locator('#effectCase').selectOption('components');await page.locator('#effectRun').click();await settle();
  if(await page.locator('#notice').evaluate(el=>el.classList.contains('error')))throw Error('Traffic profile failed');
  if(!(await page.locator('#effectSummary').innerText()).includes('840'))throw Error('Traffic results missing');
  await page.setViewportSize({width:390,height:844});await page.locator('#effectSummary').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'effects-mobile.png')});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Effect summary overflows mobile viewport');
  if(errors.length)throw Error(errors.join('\n'));
  fs.writeFileSync(path.join(out,'effects-checks.json'),JSON.stringify({base,cases:records,trafficProfile:true,mobile:true,errors},null,2));console.log('ALL EFFECT CHECKS PASS');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
