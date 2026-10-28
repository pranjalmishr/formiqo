/* Score records + unified converter: real analyses, real downloads, ownership. Synthetic resume data only. */
const {chromium}=require('playwright');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const path=require('node:path');const AxeBuilder=require('@axe-core/playwright').default;
const base=process.env.E2E_BASE_URL||'http://localhost:5173';
const RESUME=`Avery Morgan\navery@example.com | +1 555 010 1020\nProfessional Summary\nBackend engineer with 6 years building Python and PostgreSQL services.\nExperience\nSenior Software Engineer | Northstar Freight | 2021 - Present\n- Led migration of 14 billing services to FastAPI on Kubernetes, cutting latency by 38%.\n- Designed a reconciliation pipeline in Python and Kafka processing 2M records per day.\nEducation\nB.S. Computer Science | Oregon State University | 2014 - 2018\nTechnical Skills\nPython, FastAPI, PostgreSQL, Kafka, Docker, Kubernetes, AWS\n`;
const JD='Requirements: Python, PostgreSQL, Kafka, Terraform and AWS. Responsibilities: build reliable payment microservices. Nice to have: gRPC.';
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});const context=await browser.newContext({viewport:{width:1440,height:950},acceptDownloads:true});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));const dir=path.resolve('test-results');await fs.mkdir(dir,{recursive:true});let id;
 try{
  const up=await (await context.request.post(base+'/api/resumes/upload',{multipart:{file:{name:'records-avery.txt',mimeType:'text/plain',buffer:Buffer.from(RESUME)}}})).json();id=up.id;let status;for(let i=0;i<60;i++){status=await (await context.request.get(base+'/api/resumes/'+id)).json();if(status.status==='ready')break;await page.waitForTimeout(250)}
  const general=await (await context.request.post(base+'/api/ats/analyze',{data:{resume_id:id,text:status.text}})).json();
  const match=await (await context.request.post(base+'/api/ai/match-job-description',{data:{resume_id:id,job_description:JD,job_title:'Backend Engineer',company:'Records Co'}})).json();
  await page.goto(base+'/app');await page.getByRole('link',{name:'Score Records',exact:true}).click();await page.getByRole('heading',{name:'Every score, in one place.'}).waitFor();
  await page.locator('.records-table tbody tr').first().waitFor();
  assert.match(await page.locator('.records-summary').innerText(),/2/);
  const rows=page.locator('.records-table tbody tr:not(.record-detail)');assert.equal(await rows.count(),2);
  assert.match(await rows.first().innerText(),new RegExp(String(match.match_score)));assert.match(await rows.nth(1).innerText(),new RegExp(String(general.overall_score)));
  await page.getByRole('button',{name:'Job matches',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.records-table tbody tr:not(.record-detail)').length===1);
  await page.getByRole('button',{name:'All',exact:true}).click();await page.getByLabel('Search records').fill('records co');await page.waitForFunction(()=>document.querySelectorAll('.records-table tbody tr:not(.record-detail)').length===1);await page.getByLabel('Search records').fill('');
  await page.getByRole('button',{name:/Show details for records-avery/}).first().click();await page.getByRole('heading',{name:'Category breakdown'}).waitFor();
  const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();await fs.writeFile(path.join(dir,'records-accessibility.json'),JSON.stringify(axe.violations,null,2));assert.equal(axe.violations.length,0,axe.violations.map(v=>v.id).join(', '));
  await page.screenshot({path:path.join(dir,'records-desktop.png'),fullPage:true});
  const [csv]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'CSV',exact:true}).click()]);const csvText=await fs.readFile(await csv.path(),'utf8');assert.match(csvText,/analysis_id,analyzed_at,resume/);assert.ok(csvText.includes(match.id)&&csvText.includes(general.id));
  const [xlsx]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'Excel',exact:true}).click()]);const book=await fs.readFile(await xlsx.path());assert.equal(book.subarray(0,2).toString(),'PK');
  await page.getByRole('link',{name:'Open full report for records-avery.txt'}).first().click();await page.waitForURL('**/app/results/**');
  // Former PDF Tools / Image Tools links land on the single converter with the matching tab.
  await page.goto(base+'/app/image-tools');await page.waitForURL('**/app/converter?category=image');assert.equal(await page.locator('.segmented-control [aria-pressed=true]').innerText().then(t=>t.split(/\s/)[0]),'Images');
  const nav=await page.getByRole('navigation',{name:'Main navigation'}).innerText();assert.ok(!/PDF Tools|Image Tools/.test(nav)&&/Document Converter/.test(nav));
  for(const width of [375,768]){await page.setViewportSize({width,height:900});await page.goto(base+'/app/records');await page.locator('.records-table').waitFor();await page.waitForTimeout(300);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'records overflow at '+width)}
  await page.setViewportSize({width:1440,height:950});await page.goto(base+'/app/records');await page.getByRole('button',{name:'Delete record for records-avery.txt'}).first().click();await page.getByRole('button',{name:'Delete record',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.records-table tbody tr:not(.record-detail)').length===1);
  assert.deepEqual(errors,[]);console.log('PASS records: real ATS + job-match rows, filters/search, details, axe 0 violations, CSV/XLSX downloads, report link, delete, unified converter redirects, responsive.');
 }catch(error){await page.screenshot({path:path.join(dir,'records-failure.png'),fullPage:true}).catch(()=>{});throw error}finally{if(id)await context.request.delete(base+'/api/resumes/'+id).catch(()=>{});await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
