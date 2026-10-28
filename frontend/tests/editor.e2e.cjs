/* Real editor/API checks. AI suggestion responses are explicitly mocked, not a live provider. */
const {chromium}=require('playwright');
const AxeBuilder=require('@axe-core/playwright').default;
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const base=process.env.E2E_BASE_URL||'http://localhost:5173';
const sample=`Jordan Rivera
jordan@example.com
Professional Summary
Software engineer building accessible tools and reliable services for internal teams.
Experience
Acme Systems | Software Engineer | 2021 - Present
Developed Python services to support actual customer workflows and verified deployment checks.
Education
Computer Science coursework
Skills
Python, React, PostgreSQL
`;
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
 const context=await browser.newContext({viewport:{width:1536,height:1080}});const page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
 const dir=path.resolve('test-results');await fs.mkdir(dir,{recursive:true});
 try{
  await page.goto(base+'/app/editor/text');await page.getByRole('heading',{name:'Your story. A stronger first impression.'}).waitFor();
  assert.match(await page.title(),/Formiqo/);assert.ok(await page.getByRole('link',{name:'Formiqo home'}).isVisible());
  await page.getByLabel('Upload resume PDF, DOCX or TXT').setInputFiles({name:'editor-synthetic.txt',mimeType:'text/plain',buffer:Buffer.from(sample)});
  await page.getByRole('heading',{name:'Make every word work for you.'}).waitFor({timeout:120000});
  const id=new URL(page.url()).searchParams.get('resume');
  await page.getByRole('button',{name:'Professional Summary',exact:true}).click();
  const editor=()=>page.getByRole('textbox',{name:'Professional Summary content'});
  await editor().fill('Developed verified services for customer workflows and accessible internal tools.');
  await page.getByRole('button',{name:'Save draft',exact:true}).click();await page.getByRole('status').filter({hasText:'Saved · version 2'}).waitFor();
  await page.reload();await page.getByRole('button',{name:'Professional Summary',exact:true}).click();await editor().waitFor();assert.match(await editor().innerText(),/Developed verified/);
  await editor().click();await page.keyboard.press('End');await page.keyboard.insertText(' Verified detail.');
  assert.match(await editor().innerText(),/Verified detail/);
  await page.getByRole('button',{name:'Undo text change'}).click();assert.ok(!(await editor().innerText()).includes('Verified detail'));
  await page.getByRole('button',{name:'Redo text change'}).click();assert.match(await editor().innerText(),/Verified detail/);
  await page.getByLabel('Autosave to temporary workspace').check();
  await page.getByRole('status').filter({hasText:'Saved · version 3'}).waitFor({timeout:20000});await page.getByLabel('Autosave to temporary workspace').uncheck();
  await page.getByRole('button',{name:'Add section',exact:true}).click();await page.getByLabel('Section type').selectOption('Projects');await page.getByRole('dialog').getByRole('button',{name:'Add section',exact:true}).click();
  await page.getByRole('textbox',{name:'Projects content'}).fill('Built a verified Python project for internal reporting.');
  await page.getByRole('button',{name:'Move Projects up'}).click();
  await page.getByRole('button',{name:'Save draft',exact:true}).click();await page.getByRole('status').filter({hasText:'Saved · version 4'}).waitFor();
  await page.getByRole('button',{name:'Remove Projects'}).click();await page.getByRole('button',{name:'Cancel',exact:true}).click();assert.ok(await page.getByRole('button',{name:'Projects',exact:true}).isVisible());
  const pdfPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Download PDF',exact:true}).click();const pdf=await pdfPromise;await pdf.saveAs(path.join(dir,'editor-export.pdf'));assert.ok((await fs.readFile(path.join(dir,'editor-export.pdf'))).subarray(0,5).toString()==='%PDF-');
  const docxPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Download DOCX',exact:true}).click();const docx=await docxPromise;await docx.saveAs(path.join(dir,'editor-export.docx'));assert.ok((await fs.stat(path.join(dir,'editor-export.docx'))).size>1000);
  await page.getByRole('button',{name:'PDF preview',exact:true}).click();await page.getByTitle('Generated PDF resume').waitFor();assert.match(await page.getByTitle('Generated PDF resume').getAttribute('src'),/^blob:/);await page.getByRole('button',{name:'Close dialog'}).click();
  await page.screenshot({path:path.join(dir,'formiqo-editor-desktop.png'),fullPage:true});
  const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();await fs.writeFile(path.join(dir,'editor-accessibility.json'),JSON.stringify(axe.violations,null,2));assert.equal(axe.violations.length,0,axe.violations.map(v=>v.id).join(', '));
  // Enable a synthetic provider capability only in this test browser; the backend stays unconfigured.
  await page.route('**/api/config',async route=>{const response=await route.fetch();const data=await response.json();await route.fulfill({json:{...data,ai_available:true,ai_provider:'https://mock-provider.invalid'}})});
  let suggestionCount=0;
  await page.route('**/api/ai/improve',async route=>{const body=route.request().postDataJSON();suggestionCount++;await route.fulfill({json:{id:'test-only-'+suggestionCount,original:body.original,suggested:'Built a verified Python project to present actual internal reporting.',notes:['This is a mocked provider response for testing. Verify all facts.'],requires_confirmation:true,notice:'Test fixture only; no live AI provider was called.'}})});
  await page.reload();await page.getByRole('button',{name:'Projects',exact:true}).click();
  await page.getByLabel(/I consent to send this text and resume context/).check();await page.getByRole('button',{name:'Generate suggestion',exact:true}).click();await page.getByRole('heading',{name:'Before & after'}).waitFor();
  const source=await page.getByRole('textbox',{name:'Projects content'}).innerText();await page.getByRole('button',{name:'Reject',exact:true}).click();assert.equal(await page.getByRole('textbox',{name:'Projects content'}).innerText(),source);
  await page.getByRole('button',{name:'Generate suggestion',exact:true}).click();await page.getByRole('heading',{name:'Before & after'}).waitFor();await page.getByRole('button',{name:'Edit suggestion',exact:true}).click();await page.getByLabel('Suggested',{exact:true}).fill('Built a verified Python project for clear internal reporting.');
  await page.getByLabel(/I reviewed the facts/).check();await page.getByRole('button',{name:'Apply suggestion',exact:true}).click();assert.match(await page.getByRole('textbox',{name:'Projects content'}).innerText(),/clear internal reporting/);
  await page.getByRole('button',{name:'Save draft',exact:true}).click();await page.getByRole('status').filter({hasText:'Saved · version 6'}).waitFor();
  const saved=await (await context.request.get(base+'/api/editor/'+id)).json();assert.equal(saved.applied.length,1);assert.equal(saved.rejected.length,1);
  await page.getByRole('button',{name:'View original',exact:true}).click();assert.match(await page.getByRole('dialog').innerText(),/jordan@example.com/);await page.getByRole('button',{name:'Close dialog'}).click();
  await page.getByRole('button',{name:'Versions',exact:true}).click();await page.getByRole('button',{name:'Restore version 1',exact:true}).waitFor();page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'Restore version 1',exact:true}).click();assert.ok(!(await page.locator('main').innerText()).includes('clear internal reporting'));
  await page.getByRole('button',{name:'Save draft',exact:true}).click();await page.getByRole('status').filter({hasText:'Saved · version 7'}).waitFor();
  for(const width of [320,375,768,1280]){
   await page.setViewportSize({width,height:950});await page.waitForTimeout(100);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),'Overflow at '+width);
   if(width<1280){await page.getByRole('button',{name:'AI & insights',exact:true}).click();assert.ok(await page.getByRole('heading',{name:'A thoughtful second look'}).isVisible());await page.getByRole('button',{name:'Editor',exact:true}).click()}
   await page.screenshot({path:path.join(dir,'formiqo-editor-'+width+'.png'),fullPage:true});
  }
  await page.setViewportSize({width:1536,height:1080});await page.getByRole('button',{name:'Recalculate ATS score'}).click();await page.getByRole('heading',{name:'A clear view of what your resume communicates.'}).waitFor();
  await page.getByRole('link',{name:'Open improvement studio',exact:true}).click();await page.locator('.studio-toolbar').waitFor();
  await context.request.delete(base+'/api/resumes/'+id);assert.equal((await context.request.get(base+'/api/editor/'+id)).status(),404);
  assert.deepEqual(errors,[]);console.log('PASS Module 2: Formiqo branding, section editing, undo/redo, autosave/reload, reorder, cancel removal, real PDF/DOCX export + PDF preview, mocked-AI reject/edit/apply, original/version restore, responsive panels, score recalculation, ownership deletion, axe 0 violations.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
