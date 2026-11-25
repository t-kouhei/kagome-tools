const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path');
const url=process.argv[2]||'http://127.0.0.1:8080/';
const out=path.resolve(__dirname,'../qa-output');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1050}}),page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(String(error)));page.on('dialog',dialog=>dialog.accept());
  await page.goto(url+'app.html?profile=patent&demo=flow');
  await page.waitForFunction(()=>!document.getElementById('webLoading')&&!document.body.classList.contains('busy'),{timeout:120000});
  const settle=()=>page.waitForFunction(()=>!document.body.classList.contains('busy'));
  if(!await page.locator('#demonstrationPanel').getAttribute('open')&&!(await page.locator('#demonstrationPanel').evaluate(el=>el.open)))throw Error('Demo panel is not open');
  for(let step=0;step<4;step++){
    console.log('DEMO STEP',step+1,await page.locator('#demoNext').innerText());await page.locator('#demoNext').click();await settle();
    if(await page.locator('#notice').evaluate(el=>el.classList.contains('error')))throw Error(await page.locator('#status').innerText());
  }
  if(!await page.locator('#demoNext').isDisabled())throw Error('Demo did not finish');
  const frame=page.frameLocator('#result');await frame.locator('#rotationComparison tbody tr').first().waitFor();
  const cells=await frame.locator('#rotationComparison tbody tr').first().locator('td').allTextContents();
  if(cells.slice(1).join(',')!=='360,300,60,300,60')throw Error('Unexpected demonstration comparison '+cells);
  await frame.locator('#rotationComparisonComponent').selectOption('cw');
  const right=await frame.locator('#rotationComparison tbody tr').first().locator('td').allTextContents();
  if(right.slice(1).join(',')!=='900,750,150,750,150')throw Error('Component selector did not update');
  console.log('DEMO AND COMPONENTS PASS',cells);
  await page.locator('#resultsSection').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'definitions-demo.png')});
  // Verify both client-side and server-equivalent validation of negative capacity.
  await page.evaluate(async()=>{const incoming=await api('tutorial',{profile:'patent'});for(const row of incoming.tables.edges){row.mu='100';row.T='200';}await replaceState(incoming);});
  await page.locator('#theta').fill('0.1');await page.locator('#run').focus();
  await page.locator('#theta').dispatchEvent('change');
  await page.locator('#validationPanel').evaluate(el=>el.open=true);
  if(!await page.locator('#validationIssues').innerText().then(text=>text.includes('臨界量')))throw Error('Missing input validation');
  await page.locator('#run').click();await settle();
  if(!await page.locator('#notice').evaluate(el=>el.classList.contains('error')))throw Error('GUI accepted negative capacity');
  const rejected=await page.evaluate(async()=>{try{await api('run',{state:clone(sync())});return false;}catch(error){return error.message.includes('臨界量');}});
  if(!rejected)throw Error('Calculation API accepted negative capacity');console.log('NEGATIVE CAPACITY PASS');
  // Zero reference spin must leave useful rotation output and withhold products.
  await page.evaluate(async()=>{const incoming=await api('tutorial',{profile:'patent'});for(const row of incoming.tables.branching){row.S='0.6';row.R='0.2';row.L='0.2';}await replaceState(incoming);});
  await page.locator('#run').click();await settle();
  if(await page.locator('#notice').evaluate(el=>el.classList.contains('error')))throw Error(await page.locator('#status').innerText());
  await frame.locator('#interactionCard summary').click();
  if(!await frame.locator('#interactionNote').innerText().then(text=>text.includes('算定保留')))throw Error('Missing withheld reason');
  const rowText=await frame.locator('#interactionValues tbody tr').first().locator('td').allTextContents();
  if(rowText.slice(2).some(text=>text!=='–'))throw Error('Withheld score was shown as a number');
  const report=await page.evaluate(async()=>{const url=document.getElementById('result').src.replace('viewer.html','report.json');return(await fetch(url)).json();});
  if(report.standard.spin_interactions.available!==false)throw Error('Incorrect exported availability');
  console.log('ZERO SPIN PASS');
  // At the reference itself, only the same-face differences must be zero.
  await page.evaluate(async()=>{const incoming=await api('tutorial',{profile:'patent'});for(const [i,row]of incoming.tables.edges.entries()){row.mu=String(100+i%11);row.V=String(Number(row.mu)*Number(row.m));}await replaceState(incoming);});
  await page.locator('#run').click();await settle();
  await frame.locator('#rotationComparisonComponent').selectOption('cw');
  const rows=await frame.locator('#rotationComparison tbody tr').evaluateAll(elements=>elements.map(row=>Array.from(row.cells).map(cell=>cell.textContent)));
  if(rows.some(row=>Number(row[3])!==0)||!rows.some(row=>Number(row[5])!==0))throw Error('References were conflated');
  await page.screenshot({path:path.join(out,'two-reference-comparison.png')});console.log('TWO REFERENCE MEANINGS PASS',rows);
  const scriptPage=await context.newPage();await scriptPage.goto(url+'demonstration.html');
  if(!await scriptPage.locator('h1').innerText().then(text=>text.includes('入力を一つ変えて')))throw Error('Demo script is missing');
  await scriptPage.screenshot({path:path.join(out,'demonstration-script.png'),fullPage:true});
  const link=await scriptPage.locator('a.button').first().getAttribute('href');if(!new URL(link,scriptPage.url()).href.startsWith(url+'app.html'))throw Error('Demo link escaped Pages prefix');
  await scriptPage.setViewportSize({width:390,height:844});if(await scriptPage.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile demo overflows');
  if(errors.length)throw Error(errors.join('\n'));
  fs.writeFileSync(path.join(out,'definitions-checks.json'),JSON.stringify({url,demo:true,components:true,negativeCapacity:true,zeroSpinWithheld:true,twoReferences:true,teacherScript:true,errors},null,2));
  console.log('ALL DEFINITION CHECKS PASS');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
